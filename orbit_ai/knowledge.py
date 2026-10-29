from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path
from typing import Any

from .providers import LocalEmbedding, OpenAIEmbedding, LocalVector, QdrantVector, SupabaseVector, LocalStorage, SupabaseStorage
from .config import Settings
from .db import SQLiteRepository, SupabaseRepository
from .security import clean_filename

ALLOWED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx", ".csv"}


def parse_document(filename: str, data: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError("Unsupported file type. Accepted types: TXT, MD, PDF, DOCX, CSV")
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data), strict=False)
            return "\n\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception as exc:
            raise ValueError("Unable to parse PDF document") from exc
    if suffix == ".docx":
        try:
            from docx import Document
            doc = Document(io.BytesIO(data))
            return "\n\n".join(p.text for p in doc.paragraphs)
        except Exception as exc:
            raise ValueError("Unable to parse DOCX document") from exc
    text = data.decode("utf-8-sig", errors="replace")
    if suffix == ".csv":
        import csv
        rows = csv.reader(io.StringIO(text))
        return "\n".join(" | ".join(cell.strip() for cell in row) for row in rows if any(cell.strip() for cell in row))
    return text


def chunk_text(text: str, size: int = 900, overlap: int = 120) -> list[str]:
    source = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not source:
        return []
    step = size - overlap
    if step <= 0:
        raise ValueError("chunk overlap must be smaller than chunk size")
    if "\n" not in source:
        clean = re.sub(r"\s+", " ", source)
        result = []
        for i in range(0, len(clean), step):
            result.append(clean[i:i + size])
            if i + size >= len(clean):
                break
        return result
    blocks = [re.sub(r"\s+", " ", b).strip() for b in re.split(r"\n\s*\n+", source) if b.strip()]
    pieces: list[str] = []
    for block in blocks:
        if len(block) <= size:
            pieces.append(block)
        else:
            for i in range(0, len(block), step):
                pieces.append(block[i:i + size].strip())
                if i + size >= len(block):
                    break
    result: list[str] = []
    current = ""
    for piece in pieces:
        combined = f"{current}\n\n{piece}" if current else piece
        if len(combined) <= size:
            current = combined
        else:
            if current:
                result.append(current)
            current = piece
    if current:
        result.append(current)
    return result


class KnowledgeService:
    def __init__(self, settings: Settings, repository: SQLiteRepository | SupabaseRepository, storage: Any, embedding: Any, vector: Any):
        self.settings, self.repo, self.storage, self.embedding, self.vector = settings, repository, storage, embedding, vector

    async def _embed_batched(self, texts: list[str], batch_size: int = 128) -> list[list[float]]:
        vectors: list[list[float]] = []
        for offset in range(0, len(texts), batch_size):
            batch = texts[offset:offset + batch_size]
            result = await self.embedding.embed(batch)
            if len(result) != len(batch):
                raise RuntimeError("Embedding provider returned an unexpected item count")
            vectors.extend(result)
        return vectors

    async def upload(self, client_id: str, name: str, data: bytes) -> dict[str, Any]:
        clean_name = clean_filename(name)
        text = parse_document(clean_name, data)
        if not text.strip():
            raise ValueError("Document contains no extractable text")
        parts = chunk_text(text)
        if not parts:
            raise ValueError("Document contains no text chunks")
        vectors = await self._embed_batched(parts)
        rows = []
        for i, (part, embedding) in enumerate(zip(parts, vectors)):
            digest = hashlib.sha256(f"{client_id}\0{clean_name}\0{i}\0{part}".encode("utf-8")).hexdigest()
            rows.append({"id": digest, "clientId": client_id, "source": clean_name, "text": part, "embedding": embedding})
        preflight = getattr(self.vector, "validate_replacement", None)
        if callable(preflight):
            result = preflight(client_id, clean_name, rows)
            if hasattr(result, "__await__"):
                await result

        # Preserve the old blob if storage or index replacement fails. Each vector
        # provider's replace_source upserts first and only then removes old points.
        old_data: bytes | None = None
        old_names = await self.storage.list(client_id)
        if clean_name in old_names:
            old_data = await self.storage.read(client_id, clean_name)
        await self.storage.put(client_id, clean_name, data)
        try:
            await self.vector.replace_source(client_id, clean_name, rows)
        except Exception:
            try:
                if old_data is None:
                    await self.storage.remove(client_id, clean_name)
                else:
                    await self.storage.put(client_id, clean_name, old_data)
            except Exception:
                # Preserve the original indexing error; operator can reconcile the blob.
                pass
            raise
        self.repo.save_knowledge(client_id, clean_name, len(data), len(parts), "ready")
        return {"filename": clean_name, "size": len(data), "chunks": len(parts), "embeddingStatus": "ready"}

    async def list(self, client_id: str) -> list[dict[str, Any]]:
        metadata = self.repo.knowledge(client_id)
        if metadata:
            return [{**x, "bytes": x["size"], "embeddingStatus": x["status"]} for x in metadata]
        result = []
        for filename in await self.storage.list(client_id):
            size = len(await self.storage.read(client_id, filename))
            result.append({"filename": filename, "size": size, "bytes": size, "chunks": 0, "embeddingStatus": "unknown"})
        return result

    async def remove(self, client_id: str, filename: str) -> dict[str, Any]:
        clean_name = clean_filename(filename)
        old_data = await self.storage.read(client_id, clean_name)
        # Removing from storage first could lose the only recoverable original if
        # vector deletion failed. Delete index first, then the object and metadata.
        await self.vector.delete_source(client_id, clean_name)
        try:
            await self.storage.remove(client_id, clean_name)
        except Exception:
            # Restore its index from the still-present object when possible.
            try:
                parts = chunk_text(parse_document(clean_name, old_data))
                vectors = await self._embed_batched(parts)
                rows = []
                for i, (part, vector) in enumerate(zip(parts, vectors)):
                    digest = hashlib.sha256(f"{client_id}\0{clean_name}\0{i}\0{part}".encode("utf-8")).hexdigest()
                    rows.append({"id": digest, "clientId": client_id, "source": clean_name, "text": part, "embedding": vector})
                await self.vector.replace_source(client_id, clean_name, rows)
            except Exception:
                pass
            raise
        self.repo.remove_knowledge(client_id, clean_name)
        return await self.rebuild(client_id)

    async def rebuild(self, client_id: str) -> dict[str, Any]:
        names = sorted(await self.storage.list(client_id))
        all_parts: list[tuple[str, str]] = []
        file_sizes: dict[str, int] = {}
        for name in names:
            data = await self.storage.read(client_id, name)
            file_sizes[name] = len(data)
            parts = chunk_text(parse_document(name, data))
            all_parts.extend((name, chunk) for chunk in parts)
        vectors = await self._embed_batched([x[1] for x in all_parts])
        rows = []
        occurrence: dict[str, int] = {}
        for (source, text), vector in zip(all_parts, vectors):
            local_idx = occurrence.get(source, 0)
            occurrence[source] = local_idx + 1
            digest = hashlib.sha256(f"{client_id}\0{source}\0{local_idx}\0{text}".encode("utf-8")).hexdigest()
            rows.append({"id": digest, "clientId": client_id, "source": source, "text": text, "embedding": vector})

        replace_tenant = getattr(self.vector, "replace_tenant", None)
        if not callable(replace_tenant):
            raise RuntimeError("Vector provider does not support safe tenant index replacement")
        await replace_tenant(client_id, rows)

        existing_metadata = {item["filename"]: item for item in self.repo.knowledge(client_id)}
        for name in names:
            count = occurrence.get(name, 0)
            self.repo.save_knowledge(client_id, name, file_sizes[name], count, "ready")
        for stale_name in set(existing_metadata) - set(names):
            self.repo.remove_knowledge(client_id, stale_name)
        return {"files": len(names), "chunks": len(all_parts)}


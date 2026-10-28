from pathlib import Path
from .scanner import scan, Manifest
from .loader import load_document
from .chunker import chunk_document

def ingest(root: str | Path, data_dir: str | Path = ".rag_data", chunk_size=900, chunk_overlap=120, force=False):
    root=Path(root); manifest=Manifest(Path(data_dir)/"manifest.json"); paths=scan(root); chunks=[]; changed=[]
    for path in paths:
        if force or manifest.changed(path):
            doc=load_document(path); current=chunk_document(doc, chunk_size, chunk_overlap)
            chunks.extend(current); manifest.update(path, len(current)); changed.append(str(path))
    removed=manifest.remove_missing(paths); manifest.save()
    return chunks, {"files":len(paths),"changed":changed,"removed":removed,"chunks":len(chunks),"manifest":str(manifest.path)}

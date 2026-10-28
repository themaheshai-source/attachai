"""Recursive scanner and incremental content manifest."""
from pathlib import Path
import hashlib, json
from .loader import SUPPORTED

def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""): h.update(block)
    return h.hexdigest()

def scan(root: str | Path) -> list[Path]:
    root = Path(root)
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED and not any(x.startswith(".") for x in p.parts))

class Manifest:
    def __init__(self, path: str | Path):
        self.path = Path(path); self.items = self._read()
    def _read(self):
        try: return json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError): return {}
    def changed(self, path: Path) -> bool: return self.items.get(str(path), {}).get("sha256") != file_hash(path)
    def update(self, path: Path, chunks: int): self.items[str(path)] = {"sha256": file_hash(path), "chunks": chunks}
    def remove_missing(self, paths):
        keep={str(p) for p in paths}; removed=[k for k in self.items if k not in keep]
        self.items={k:v for k,v in self.items.items() if k in keep}; return removed
    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True); self.path.write_text(json.dumps(self.items, indent=2, sort_keys=True))

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

@dataclass
class Document:
    text: str
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class Chunk:
    text: str
    chunk_id: str
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    retrieval: dict[str, float] = field(default_factory=dict)

    def as_payload(self):
        return {"text": self.text, "chunk_id": self.chunk_id, "source": self.source, **self.metadata}

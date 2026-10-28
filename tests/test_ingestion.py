from pathlib import Path
from advanced_rag.ingestion import Document, chunk_document, scan

def test_structure_and_chunking(tmp_path):
    p=tmp_path/"a.md"; p.write_text("# Intro\n\nAlpha facts.\n\n## Detail\n\nBeta facts.")
    chunks=chunk_document(Document(p.read_text(),str(p)),size=100,overlap=10)
    assert chunks and any("Alpha" in c.text for c in chunks)
    assert scan(tmp_path)==[p]

def test_supported_scan_recursive(tmp_path):
    d=tmp_path/"nested"; d.mkdir(); (d/"x.txt").write_text("hello"); (tmp_path/"no.bin").write_bytes(b"x")
    assert scan(tmp_path)==[d/"x.txt"]

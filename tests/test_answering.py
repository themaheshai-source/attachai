from advanced_rag.answering import validate_answer
from advanced_rag.ingestion import Chunk

def test_citation_validation():
    c=[Chunk("Fact", "1", "a.txt")]
    result=validate_answer("Fact [Source 1] [Source 9]",c)
    assert result["grounded"] and "[Source 9]" in result["unknown_citations"]

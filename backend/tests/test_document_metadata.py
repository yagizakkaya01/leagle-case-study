from langchain_core.runnables import RunnableLambda

from app.schemas import LlmDocumentFields, Party
from app.services.document_metadata import extract_metadata
from app.services.pdf_processing import process_pdf
from tests.pdf_factory import make_pdf

PAGES = [
    "SERVICE AGREEMENT",
    "1. Payment",
    "The Client shall pay a monthly fee of 2,000 euros. Each invoice is payable within "
    "thirty days of receipt by bank transfer.",
    "2. Termination",
    "Either party may terminate this Agreement by giving ninety days written notice "
    "to the other party at its registered address.",
]


def _processed():
    return process_pdf(make_pdf_lines(PAGES), document_id="d", filename="a.pdf",
                       chunk_size=200, overlap=40, max_pages=10)


def make_pdf_lines(lines: list[str]) -> bytes:
    # One line per text line so headings stay on their own line.
    return make_pdf(["\n".join(lines)])


def test_rule_based_metadata_without_llm():
    meta = extract_metadata(_processed(), extractor=None)
    assert meta.llm_enriched is False
    assert meta.document_type == "other"
    assert [o.heading for o in meta.outline] == ["SERVICE AGREEMENT", "1. Payment",
                                                "2. Termination"]
    assert meta.clause_categories == {"payment": 1, "termination": 1}


def test_llm_fields_are_merged_with_rule_fields():
    seen = {}

    def fake_llm(inputs):
        seen.update(inputs)
        return LlmDocumentFields(
            document_type="contract",
            title="Service Agreement",
            parties=[Party(name="Acme Ltd", role="Client")],
        )

    meta = extract_metadata(_processed(), extractor=RunnableLambda(fake_llm))
    assert meta.llm_enriched is True
    assert meta.document_type == "contract"
    assert meta.parties[0].name == "Acme Ltd"
    assert meta.clause_categories == {"payment": 1, "termination": 1}  # rules kept
    assert "--- Page 1 ---" in seen["text"]
    assert "2. Termination (p. 1)" in seen["outline"]


def test_llm_failure_falls_back_to_rule_metadata():
    def broken(_):
        raise RuntimeError("quota exceeded")

    meta = extract_metadata(_processed(), extractor=RunnableLambda(broken))
    assert meta.llm_enriched is False
    assert meta.outline


def test_missing_tool_call_falls_back_to_rule_metadata():
    meta = extract_metadata(_processed(), extractor=RunnableLambda(lambda _: None))
    assert meta.llm_enriched is False

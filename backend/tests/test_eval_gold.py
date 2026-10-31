"""The eval's gold labels must match the documents they are about."""
import pytest

from app.services.pdf_processing import process_pdf
from app.services.text_normalize import normalize_whitespace
from eval.documents import DOCUMENTS
from eval.gold import GOLD
from eval.gold_hard import GOLD_HARD
from eval.gold_heldout import GOLD_HELDOUT
from tests.pdf_factory import make_pdf


@pytest.fixture(scope="module")
def pages():
    out = {}
    for key, (name, texts) in DOCUMENTS.items():
        processed = process_pdf(make_pdf(texts), document_id=key * 4, filename=name,
                                chunk_size=200, overlap=40, max_pages=50)
        out[key] = [normalize_whitespace(p) for p in processed.pages]
    return out


ALL = GOLD + GOLD_HARD + GOLD_HELDOUT


def test_ids_are_unique():
    ids = [g["id"] for g in ALL]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("gold", [g for g in ALL if g["found"]], ids=lambda g: g["id"])
def test_evidence_is_on_a_labelled_page(gold, pages):
    assert any(gold["evidence"] in pages[gold["doc"]][p - 1] for p in gold["pages"])


@pytest.mark.parametrize("gold", [g for g in ALL if not g["found"]], ids=lambda g: g["id"])
def test_absent_questions_have_no_page(gold):
    assert not gold["pages"] and gold["evidence"] is None

"""The eval's gold labels must match the documents they are about."""
import pytest

from app.services.pdf_processing import process_pdf
from app.services.text_normalize import normalize_whitespace
from eval.documents import DOCUMENTS
from eval.gold import GOLD
from tests.pdf_factory import make_pdf


@pytest.fixture(scope="module")
def pages():
    out = {}
    for key, (name, texts) in DOCUMENTS.items():
        processed = process_pdf(make_pdf(texts), document_id=key * 4, filename=name,
                                chunk_size=200, overlap=40, max_pages=50)
        out[key] = [normalize_whitespace(p) for p in processed.pages]
    return out


def test_ids_are_unique():
    ids = [g["id"] for g in GOLD]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("gold", [g for g in GOLD if g["found"]], ids=lambda g: g["id"])
def test_evidence_is_on_the_labelled_page(gold, pages):
    assert gold["evidence"] in pages[gold["doc"]][gold["page"] - 1]


@pytest.mark.parametrize("gold", [g for g in GOLD if not g["found"]], ids=lambda g: g["id"])
def test_absent_questions_have_no_page(gold):
    assert gold["page"] is None and gold["evidence"] is None

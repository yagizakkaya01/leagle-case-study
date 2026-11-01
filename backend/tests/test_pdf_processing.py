import pytest

from app.services.pdf_processing import (
    PdfProcessingError,
    is_valid_chunk,
    process_pdf,
    split_into_sections,
    split_text,
)
from tests.pdf_factory import make_pdf

CLAUSE = (
    "The Tenant shall pay the monthly rent of five thousand euros no later than "
    "the fifth day of each calendar month to the account designated by the Landlord."
)


def _process(data: bytes, **overrides):
    kwargs = dict(document_id="doc1", filename="lease.pdf", chunk_size=200, overlap=40,
                  max_pages=50)
    kwargs.update(overrides)
    return process_pdf(data, **kwargs)


def test_split_text_overlaps_windows():
    words = " ".join(f"w{i}" for i in range(10))
    chunks = split_text(words, chunk_size=4, overlap=1)
    assert chunks[0] == "w0 w1 w2 w3"
    assert chunks[1].startswith("w3")
    assert chunks[-1].endswith("w9")


def test_split_text_keeps_line_breaks():
    assert split_text("first line\nsecond line", chunk_size=10, overlap=2) == [
        "first line\nsecond line"
    ]


def test_is_valid_chunk_rejects_page_numbers_and_bullets():
    assert not is_valid_chunk("12\n•\n")
    assert is_valid_chunk(CLAUSE)


def test_process_pdf_keeps_page_numbers_and_reports_empty_pages():
    result = _process(make_pdf(["", CLAUSE, "Annex " + CLAUSE]))
    assert result.page_count == 3
    assert result.empty_pages == [1]
    assert [c.metadata["page"] for c in result.chunks] == [2, 3]
    assert "monthly rent" in result.chunks[0].page_content
    meta = result.chunks[0].metadata
    assert meta["chunk_id"] == "doc1-p2-c0"
    assert (meta["document_id"], meta["filename"], meta["page"]) == ("doc1", "lease.pdf", 2)
    assert result.pages[1].startswith("The Tenant")


def test_sections_split_at_headings_and_carry_over_pages():
    page1 = "MADDE 4 - FESİH\nTaraflardan her biri bu sözleşmeyi otuz gün önceden yazılı bildirimle"
    page2 = "feshedebilir ve fesih halinde kiracı taşınmazı boş olarak teslim etmekle yükümlüdür."
    sections = split_into_sections([page1, page2])
    assert [(s.page, s.heading, s.clause_number) for s in sections] == [
        (1, "MADDE 4 - FESİH", "4"),
        (2, "MADDE 4 - FESİH", "4"),
    ]
    assert sections[1].lines == [page2]


def test_process_pdf_rejects_too_many_pages():
    with pytest.raises(PdfProcessingError, match="limit is 1"):
        _process(make_pdf([CLAUSE, CLAUSE]), max_pages=1)


def test_process_pdf_rejects_garbage():
    with pytest.raises(PdfProcessingError):
        _process(b"%PDF-1.4 this is not really a pdf")

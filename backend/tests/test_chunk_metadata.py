import pytest

from app.services.chunk_metadata import (
    case_numbers,
    classify_clause,
    parse_heading,
)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("MADDE 7 - GİZLİLİK", ("MADDE 7 - GİZLİLİK", "7")),
        ("Madde 12", ("Madde 12", "12")),
        ("Article 5. Termination", ("Article 5. Termination", "5")),
        ("Section 3.2 Payment Terms", ("Section 3.2 Payment Terms", "3.2")),
        ("4.1 Governing Law", ("4.1 Governing Law", "4.1")),
        ("HÜKÜM", ("HÜKÜM", None)),
        ("TERMINATION", ("TERMINATION", None)),
    ],
)
def test_parse_heading_recognises_headings(line, expected):
    assert parse_heading(line) == expected


@pytest.mark.parametrize(
    "line",
    [
        "1. The Tenant shall keep the premises in good condition.",
        "The parties agree as follows, subject to the conditions below and in the annex",
        "2024",
        "",
    ],
)
def test_parse_heading_ignores_body_text(line):
    assert parse_heading(line) is None


def test_classify_clause_uses_heading_and_text():
    assert classify_clause("MADDE 9 - FESİH", "Taraflar sözleşmeyi feshedebilir.") == "termination"
    assert classify_clause(None, "This Agreement shall be governed by the laws of England.") == (
        "governing_law"
    )
    assert classify_clause("Gizlilik", "Taraflar bilgileri saklar.") == "confidentiality"


def test_classify_clause_needs_more_than_one_weak_hit():
    assert classify_clause(None, "Please make sure the court is informed.") == "other"


def test_case_numbers_turkish_and_english():
    text = "Esas No : 2022/16696 Karar No: 2024/1755 ... ayrıca 2021/55 E., 2021/90 K."
    assert case_numbers(text) == ["2022/16696 E.", "2024/1755 K.", "2021/55 E.", "2021/90 K."]
    assert case_numbers("Case No. CV-2023-0042 before the court") == ["Case No. CV-2023-0042"]


def test_large_font_line_is_a_heading_even_without_numbers():
    assert parse_heading("Payment Terms") is None
    assert parse_heading("Payment Terms", large_font=True) == ("Payment Terms", None)
    long_line = "This is a long sentence in a big font that goes well past the heading limit"
    assert parse_heading(long_line, large_font=True) is None


def test_referenced_clauses_in_english_and_turkish():
    from app.services.chunk_metadata import referenced_clauses
    assert referenced_clauses("In clause 2 ... In clause 7, the amount") == ["2", "7"]
    assert referenced_clauses("Subject to clause 9, the Distributor", own="6") == ["9"]
    assert referenced_clauses("see clauses 2 and 7, Section 4.1, 3. maddesi ve Madde 5") == [
        "2", "3", "4.1", "5", "7"]
    assert referenced_clauses("This clause applies", own="3") == []


def test_capitalised_lead_in_is_a_heading():
    assert parse_heading("AMENDMENT No. 1 (signed 1 July 2024)") == (
        "AMENDMENT No. 1 (signed 1 July 2024)", None)
    assert parse_heading("SIDE LETTER dated 20 January 2025")
    assert parse_heading("LCIA Rules apply to the arbitration") is None

import pytest

from app.services.pdf_processing import process_pdf
from app.services.quote_location import locate_quote
from tests.pdf_factory import make_pdf, make_positioned_pdf

# A form that draws its right column first, unlike the order a person reads it in
FORM_CELLS = [
    (300, 700, "Discharge Date :"), (400, 700, "31.08.2024"),
    (50, 700, "12345678901"),
    (50, 600, "Patient was transferred to the ward in good condition."),
]


def test_finds_a_quote_spanning_cells_drawn_in_another_order():
    quote = "12345678901 Discharge Date : 31.08.2024"
    boxes = locate_quote(make_positioned_pdf(FORM_CELLS), 1, quote)
    assert [round(b.x * 6.12) for b in boxes] == [50, 300, 400]


def test_box_sits_on_the_text_in_percent_of_the_page():
    [box] = locate_quote(make_positioned_pdf(FORM_CELLS), 1, "Patient was transferred")
    assert box.x * 6.12 == pytest.approx(50, abs=1)
    # 11 pt text on a baseline 600 pt above the bottom of a 792 pt page
    assert (box.top + box.height) / 100 * 792 == pytest.approx(792 - 600, abs=4)
    assert box.width * 6.12 == pytest.approx(112, abs=12)


def test_includes_punctuation_after_the_last_word():
    [box] = locate_quote(make_positioned_pdf(FORM_CELLS), 1, "the ward in good condition")
    [with_dot] = locate_quote(make_positioned_pdf(FORM_CELLS), 1, "the ward in good condition.")
    assert box.width == with_dot.width


def test_tolerates_a_slightly_different_quote():
    quote = "Patient was transfered to the ward in good condition"
    assert locate_quote(make_positioned_pdf(FORM_CELLS), 1, quote)


def test_ignores_case_spacing_and_turkish_letters():
    pdf = make_positioned_pdf([(50, 700, "HASTANIN GENEL DURUMU IYI")])
    assert locate_quote(pdf, 1, "hastanın  genel durumu iyi")


@pytest.mark.parametrize(("rotate", "page_width", "page_height"), [
    (0, 612, 792), (90, 792, 612), (180, 612, 792), (270, 792, 612),
])
def test_box_follows_the_page_as_displayed_when_rotated(rotate, page_width, page_height):
    pdf = make_positioned_pdf([(50, 500, "Patient was transferred")], rotate=rotate)
    [box] = locate_quote(pdf, 1, "Patient was transferred")
    assert box.x / 100 * page_width == pytest.approx(50, abs=3)
    assert (box.top + box.height) / 100 * page_height == pytest.approx(page_height - 500, abs=4)


def test_cropped_page_measures_from_the_crop():
    pdf = make_positioned_pdf(FORM_CELLS, crop=(40, 500, 580, 750))
    [box] = locate_quote(pdf, 1, "Patient was transferred")
    assert box.x / 100 * 540 == pytest.approx(10, abs=1)
    assert (box.top + box.height) / 100 * 250 == pytest.approx(750 - 600, abs=4)


@pytest.mark.parametrize("rotate", [0, 90, 180, 270])
@pytest.mark.parametrize("crop", [None, (40, 100, 560, 700)])
@pytest.mark.parametrize("media", [(0, 0, 612, 792), (10, 20, 622, 812), (-30, -50, 582, 742)])
def test_box_lands_where_a_viewer_draws_the_text(rotate, crop, media):
    # (cx, cy) is the text's origin in PDF coordinates; each rule below is how PDF viewers
    # (checked against pdf.js) turn it into a position from the top left of the visible page.
    x, y = 280, 300
    cx, cy = {0: (x, y), 90: (612 - y, x), 180: (612 - x, 792 - y), 270: (y, 792 - x)}[rotate]
    x0, y0, x1, y1 = crop or media
    x0, y0, x1, y1 = max(x0, media[0]), max(y0, media[1]), min(x1, media[2]), min(y1, media[3])
    left, baseline, width, height = {
        0: (cx - x0, y1 - cy, x1 - x0, y1 - y0),
        90: (cy - y0, cx - x0, y1 - y0, x1 - x0),
        180: (x1 - cx, cy - y0, x1 - x0, y1 - y0),
        270: (y1 - cy, x1 - cx, y1 - y0, x1 - x0),
    }[rotate]

    pdf = make_positioned_pdf([(x, y, "Patient was transferred")], rotate=rotate, crop=crop)
    media_box = f"/MediaBox [{' '.join(map(str, media))}]".encode()
    pdf = pdf.replace(b"/MediaBox [0 0 612 792]", media_box)
    [box] = locate_quote(pdf, 1, "Patient was transferred")

    assert box.x / 100 * width == pytest.approx(left, abs=1.5)
    assert (box.top + box.height) / 100 * height == pytest.approx(baseline, abs=4)


def test_finds_every_line_the_extractor_reads_in_this_order():
    # The quote comes from this text, whatever its layout, so each line must be found
    pdf = make_positioned_pdf(FORM_CELLS)
    for text in process_pdf(pdf, document_id="d", filename="f.pdf", chunk_size=500,
                            overlap=0, max_pages=5).pages[0].split("\n"):
        assert locate_quote(pdf, 1, text), text


def test_nothing_when_the_quote_is_not_on_the_page():
    pdf = make_pdf(["Some other text on this page."])
    assert locate_quote(pdf, 1, "A completely unrelated sentence about fees") == []
    assert locate_quote(pdf, 2, "Some other text") == []
    assert locate_quote(pdf, 1, "...") == []

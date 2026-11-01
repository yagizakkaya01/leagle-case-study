"""Builds tiny text PDFs in memory so tests need no binary fixtures."""
from __future__ import annotations

import textwrap
from pathlib import Path

from app.services.document_store import DocumentStore
from app.services.file_storage import FileStorage, LocalFileStorage
from app.services.persistence import Repository


def make_store(where: Path | FileStorage, repository: Repository | None = None) -> DocumentStore:
    """DocumentStore with test-sized chunking and no LLM or embeddings."""
    files = LocalFileStorage(where) if isinstance(where, Path) else where
    return DocumentStore(files, chunk_size=200, overlap=40, max_pages=10, repository=repository)


def make_pdf(pages: list[str]) -> bytes:
    """One page per string; an empty string produces a page with no text."""
    objects: list[bytes] = []
    page_count = len(pages)
    # 1: catalog, 2: pages tree, 3: font, then (page, content) pairs.
    kids = " ".join(f"{4 + i * 2} 0 R" for i in range(page_count))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    for i, text in enumerate(pages):
        content_id = 5 + i * 2
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>".encode()
        )
        # "\n" starts a new line; long lines wrap at word boundaries like real documents.
        lines = [w for p in text.split("\n") for w in (textwrap.wrap(p, 90) or [""])]
        ops = ["BT", "/F1 11 Tf", "14 TL", "50 740 Td"]
        for line in lines:
            safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            ops.append(f"({safe}) Tj T*")
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1")
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    return _assemble(objects)


def make_positioned_pdf(cells: list[tuple[int, int, str]], rotate: int = 0,
                        crop: tuple[int, int, int, int] | None = None) -> bytes:
    """One 612x792 page drawing (x, y, text) cells in the given order.

    x and y are where the text appears, from the bottom left of the page as displayed;
    a rotated page draws its text so that it reads upright, as real documents do.
    """
    place = {
        0: lambda x, y: ("1 0 0 1", x, y),
        90: lambda x, y: ("0 1 -1 0", 612 - y, x),
        180: lambda x, y: ("-1 0 0 -1", 612 - x, 792 - y),
        270: lambda x, y: ("0 -1 1 0", y, 792 - x),
    }[rotate]
    ops = ["BT", "/F1 11 Tf"]
    for x, y, text in cells:
        matrix, tx, ty = place(x, y)
        ops.append(f"{matrix} {tx} {ty} Tm ({text}) Tj")
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1")
    box = f"/CropBox [{' '.join(map(str, crop))}] " if crop else ""
    return _assemble([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] {box}/Rotate {rotate} "
        f"/Resources << /Font << /F1 3 0 R >> >> /Contents 5 0 R >>".encode(),
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ])


def _assemble(objects: list[bytes]) -> bytes:
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode()
    out += f"startxref\n{xref_at}\n%%EOF\n".encode()
    return bytes(out)

"""Regenerate the PDF sample and malformed fixtures (dev-time only).

Needs PyMuPDF (`pip install pymupdf`), which LegalLens itself does not use at
run time. The generated files are committed, so tests never need it.

    python data/samples/make_pdfs.py
"""
from pathlib import Path

import fitz  # PyMuPDF

HERE = Path(__file__).parent
BAD = HERE / "malformed"


def text_pdf(src: Path, out: Path, lines_per_page: int = 28) -> None:
    """Multi-page PDF with a running header and 'Page n of N' footer, so the
    ingester's header/footer stripping is exercised."""
    lines = src.read_text(encoding="utf-8").splitlines()
    chunks = [lines[i:i + lines_per_page] for i in range(0, len(lines), lines_per_page)]
    doc = fitz.open()
    for n, chunk in enumerate(chunks, start=1):
        page = doc.new_page(width=595, height=842)
        page.insert_text((50, 40), "Green Park Apartments - Rental Agreement", fontsize=9)
        page.insert_text((50, 80), "\n".join(chunk), fontsize=10.5, lineheight=1.35)
        page.insert_text((270, 815), f"Page {n} of {len(chunks)}", fontsize=9)
    doc.save(out)


def scanned_pdf(out: Path) -> None:
    """Image-only page: the text is rasterised, so no text layer exists."""
    src = fitz.open()
    p = src.new_page(width=595, height=842)
    p.insert_text((50, 80), "1. RENT\n1.1 The monthly rent shall be Rs. 15,000.", fontsize=14)
    pix = p.get_pixmap(dpi=40, colorspace=fitz.csGRAY)
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=pix.tobytes("jpeg", jpg_quality=40))
    doc.save(out)


def encrypted_pdf(src: Path, out: Path) -> None:
    doc = fitz.open(src)
    doc.save(out, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="owner")


if __name__ == "__main__":
    BAD.mkdir(exist_ok=True)
    text_pdf(HERE / "rental_clear.txt", HERE / "rental_clear.pdf")
    scanned_pdf(BAD / "scanned.pdf")
    encrypted_pdf(HERE / "rental_clear.pdf", BAD / "password.pdf")
    (BAD / "corrupt.pdf").write_bytes(b"%PDF-1.7\n1 0 obj << /Type /Catalog >>\nthis is not a pdf\n")
    (BAD / "empty.txt").write_bytes(b"")
    print("wrote", sorted(p.name for p in HERE.rglob("*.pdf")))

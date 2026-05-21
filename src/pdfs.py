import pymupdf


def render_pdf_pages(
    pdf_bytes: bytes,
    *,
    max_pages: int,
    dpi: int,
) -> list[bytes]:
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
        pages = document.page_count if max_pages > document.page_count else max_pages

        return [
            document.load_page(page_number)
            .get_pixmap(dpi=dpi, alpha=False)
            .tobytes("png")
            for page_number in range(pages)
        ]

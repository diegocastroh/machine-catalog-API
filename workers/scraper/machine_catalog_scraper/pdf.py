from pathlib import Path

from pypdf import PdfReader


def extract_pdf_text(path: str | Path, max_chars: int = 20000) -> str:
    reader = PdfReader(str(path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return text[:max_chars]

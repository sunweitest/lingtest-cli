"""Load human-readable requirements and API documents."""

from html.parser import HTMLParser
from pathlib import Path

from docx import Document
from openpyxl import load_workbook

MAX_DOCUMENT_CHARS = 60_000
TEXT_SUFFIXES = {".txt", ".md", ".json", ".yaml", ".yml"}
SUPPORTED_SUFFIXES = TEXT_SUFFIXES | {".docx", ".html", ".htm", ".xlsx"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.ignored_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"style", "script"}:
            self.ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"style", "script"} and self.ignored_depth:
            self.ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.ignored_depth:
            return
        text = data.strip()
        if text:
            self.parts.append(text)


def read_document(path: str | Path) -> str:
    """Return normalized text from a supported document."""
    document = Path(path)
    suffix = document.suffix.lower()
    if suffix == ".doc":
        raise ValueError("Legacy .doc is not supported; convert it to .docx first")
    if suffix not in SUPPORTED_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
        raise ValueError(f"Supported document types: {supported}")

    if suffix == ".docx":
        content = _read_docx(document)
    elif suffix == ".xlsx":
        content = _read_xlsx(document)
    elif suffix in {".html", ".htm"}:
        parser = _TextExtractor()
        parser.feed(document.read_text(encoding="utf-8"))
        content = "\n".join(parser.parts)
    else:
        content = document.read_text(encoding="utf-8")

    if not content.strip():
        raise ValueError("Document is empty")
    return content[:MAX_DOCUMENT_CHARS]


def _read_docx(path: Path) -> str:
    doc = Document(path)
    parts: list[str] = []
    for paragraph in doc.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        style = paragraph.style.name.lower() if paragraph.style else ""
        if style.startswith("heading"):
            level = "".join(char for char in style if char.isdigit()) or "1"
            text = f"{'#' * min(int(level), 6)} {text}"
        parts.append(text)
    for table in doc.tables:
        rows = [
            [" ".join(cell.text.split()).replace("|", "\\|") for cell in row.cells]
            for row in table.rows
        ]
        if not rows:
            continue
        parts.append("| " + " | ".join(rows[0]) + " |")
        parts.append("| " + " | ".join("---" for _ in rows[0]) + " |")
        parts.extend("| " + " | ".join(row) + " |" for row in rows[1:])
    return "\n\n".join(parts)


def _read_xlsx(path: Path) -> str:
    workbook = load_workbook(path, read_only=True, data_only=True)
    parts: list[str] = []
    try:
        for sheet in workbook.worksheets:
            parts.append(f"# Sheet: {sheet.title}")
            for row in sheet.iter_rows(values_only=True):
                values = ["" if value is None else str(value) for value in row]
                if any(values):
                    parts.append(" | ".join(values))
    finally:
        workbook.close()
    return "\n".join(parts)

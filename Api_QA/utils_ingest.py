# utils_ingest.py
# ---------------------------------------------
# Extracción y estructuración de texto desde adjuntos para usar como contexto
# en la generación de escenarios QA.
# - Preserva secciones y tablas cuando es posible.
# - Segmenta documentos grandes antes de consolidarlos.
# - Expone metadatos útiles para trazabilidad.
# ---------------------------------------------

from __future__ import annotations

import csv
import hashlib
import io
import platform
import re
import shutil
from typing import Dict, List, Tuple

import fitz  # PyMuPDF
import pandas as pd

try:
    from PIL import Image
    import pytesseract

    if platform.system() == "Windows":
        pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    elif shutil.which("tesseract"):
        pytesseract.pytesseract.tesseract_cmd = shutil.which("tesseract")

    _OCR_OK = True
except Exception:
    _OCR_OK = False
    Image = None
    pytesseract = None

try:
    import docx  # python-docx
except Exception:
    docx = None

SUPPORTED_DOCS = {".pdf", ".docx", ".txt", ".csv", ".xlsx"}
SUPPORTED_IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".tiff", ".tif"}


def _ext(name: str) -> str:
    idx = name.rfind(".")
    return name[idx:].lower() if idx != -1 else ""


def _sha1_8(blob: bytes) -> str:
    return hashlib.sha1(blob).hexdigest()[:8]


def _ocr_image_bytes(img_bytes: bytes, lang: str = "spa+eng") -> str:
    if not _OCR_OK:
        return ""
    image = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    return (pytesseract.image_to_string(image, lang=lang) or "").strip()


def _normalize_text_block(texto: str) -> str:
    if not isinstance(texto, str):
        return ""
    texto = texto.replace("\xa0", " ")
    texto = re.sub(r"\r\n?", "\n", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def _mark_tables(lines: List[str]) -> List[str]:
    formatted: List[str] = []
    for line in lines:
        normalized = " ".join(line.split())
        if normalized.count("|") >= 2:
            formatted.append(f"[TABLA] {normalized}")
        elif re.search(r"\b(columna|campo|valor|descripci[oó]n|importe)\b", normalized, re.IGNORECASE) and "," in normalized:
            formatted.append(f"[TABLA] {normalized}")
        else:
            formatted.append(line.strip())
    return formatted


def preserve_document_structure(texto: str) -> str:
    texto = _normalize_text_block(texto)
    if not texto:
        return ""

    lines = [line.strip() for line in texto.split("\n") if line.strip()]
    lines = _mark_tables(lines)
    structured: List[str] = []

    for line in lines:
        if re.match(r"^(?:#{1,6}\s+.+|\d+(?:\.\d+)*\s+.+)$", line):
            structured.append(f"\n[linea_seccion] {line}")
        elif line.endswith(":") and len(line) < 120:
            structured.append(f"\n[linea_seccion] {line}")
        else:
            structured.append(line)

    return "\n".join(structured).strip()


def segment_document_text(texto: str, max_chars: int = 12000, overlap: int = 600) -> List[str]:
    normalized = preserve_document_structure(texto)
    if not normalized:
        return []
    if len(normalized) <= max_chars:
        return [normalized]

    paragraphs = [part.strip() for part in re.split(r"\n{2,}", normalized) if part.strip()]
    segments: List[str] = []
    current = ""

    for paragraph in paragraphs:
        block = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(block) <= max_chars:
            current = block
            continue
        if current:
            segments.append(current)
        if len(paragraph) <= max_chars:
            current = paragraph
            continue
        start = 0
        while start < len(paragraph):
            end = min(len(paragraph), start + max_chars)
            segments.append(paragraph[start:end].strip())
            if end >= len(paragraph):
                break
            start = max(0, end - overlap)
        current = ""

    if current:
        segments.append(current)
    return segments


def _from_pdf(blob: bytes, lang: str = "spa+eng") -> str:
    try:
        doc = fitz.open(stream=blob, filetype="pdf")
    except Exception:
        return ""

    pages: List[str] = []
    for page_index, page in enumerate(doc, start=1):
        text = page.get_text("text") or ""
        if not text.strip():
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            text = _ocr_image_bytes(pix.tobytes("png"), lang=lang) or ""
        text = _normalize_text_block(text)
        if text:
            pages.append(f"[Página {page_index}]\n{text}")
    doc.close()
    return "\n\n".join(pages).strip()


def _from_docx(blob: bytes) -> str:
    if docx is None:
        return ""
    try:
        document = docx.Document(io.BytesIO(blob))
    except Exception:
        return ""

    parts: List[str] = []
    for paragraph in document.paragraphs:
        text = " ".join(paragraph.text.split())
        if text:
            parts.append(text)

    for table in document.tables:
        for row in table.rows:
            row_cells = []
            for cell in row.cells:
                text = " ".join(cell.text.split())
                if text:
                    row_cells.append(text)
            if row_cells:
                parts.append(" | ".join(row_cells))

    return "\n".join(parts).strip()


def _from_txt(blob: bytes) -> str:
    try:
        return blob.decode("utf-8", errors="ignore").strip()
    except Exception:
        return blob.decode("latin-1", errors="ignore").strip()


def _from_csv(blob: bytes) -> str:
    output: List[str] = []
    reader = csv.reader(io.StringIO(blob.decode("utf-8", errors="ignore")))
    for row_index, row in enumerate(reader, start=1):
        output.append(f"[Fila {row_index}] " + " | ".join(cell.strip() for cell in row))
        if row_index >= 2000:
            output.append("... (truncado)")
            break
    return "\n".join(output)


def _from_xlsx(blob: bytes) -> str:
    try:
        with io.BytesIO(blob) as bio:
            sheets = pd.read_excel(bio, sheet_name=None)
    except Exception:
        return ""

    chunks: List[str] = []
    for sheet_name, dataframe in sheets.items():
        chunks.append(f"[Hoja] {sheet_name}")
        chunks.append(dataframe.to_csv(index=False))
    text = "\n\n".join(chunks)
    return text[:300000] + ("... (truncado)" if len(text) > 300000 else "")


def _from_image(blob: bytes, lang: str = "spa+eng") -> str:
    if not _OCR_OK:
        return ""
    try:
        image = Image.open(io.BytesIO(blob)).convert("RGB")
    except Exception:
        return ""
    return (pytesseract.image_to_string(image, lang=lang) or "").strip()


def extract_attachment(name: str, content: bytes) -> Tuple[str, Dict]:
    ext = _ext(name)
    text = ""

    if ext in SUPPORTED_DOCS:
        if ext == ".pdf":
            text = _from_pdf(content)
        elif ext == ".docx":
            text = _from_docx(content)
        elif ext == ".txt":
            text = _from_txt(content)
        elif ext == ".csv":
            text = _from_csv(content)
        elif ext == ".xlsx":
            text = _from_xlsx(content)
    elif ext in SUPPORTED_IMAGES:
        text = _from_image(content)

    structured_text = preserve_document_structure(text)
    segments = segment_document_text(structured_text) if structured_text else []
    meta = {
        "filename": name,
        "ext": ext,
        "size_bytes": len(content),
        "sha1_8": _sha1_8(content),
        "chars": len(structured_text),
        "segments": len(segments),
    }
    return structured_text, meta


def consolidate_attachments(files: List[Tuple[str, bytes]], max_chars: int = 200000) -> Tuple[str, List[Dict]]:
    parts: List[str] = []
    metas: List[Dict] = []
    current_len = 0

    for name, content in files:
        text, meta = extract_attachment(name, content)
        metas.append(meta)
        if not text:
            continue

        segments = segment_document_text(text)
        for segment_index, segment in enumerate(segments, start=1):
            header = (
                f"\n\n### Fuente: {name} ({meta['sha1_8']})"
                f"\n### Segmento: {segment_index}/{len(segments)}"
            )
            block = f"{header}\n{segment}".strip()
            if current_len + len(block) > max_chars:
                remaining = max(0, max_chars - current_len)
                if remaining > 0:
                    parts.append(block[:remaining] + "\n... (truncado)")
                return "".join(parts).strip(), metas
            parts.append(block)
            current_len += len(block)

    return "".join(parts).strip(), metas


def ocr_diagnostics() -> Dict:
    return {
        "OCR_OK": _OCR_OK,
        "tesseract_cmd": getattr(pytesseract.pytesseract, "tesseract_cmd", None) if _OCR_OK else None,
        "engine": "PyMuPDF + Tesseract",
    }

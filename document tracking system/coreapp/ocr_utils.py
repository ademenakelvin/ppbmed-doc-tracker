import io
import os
import re
from datetime import datetime

import fitz
import pytesseract
from PIL import Image, ImageOps

ORGANIZATION_HINTS = [
    "ppbmed",
    "public procurement",
    "ministry of education",
]


COMMON_TESSERACT_PATHS = [
    os.environ.get("TESSERACT_CMD", ""),
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]


def _get_available_tesseract():
    for path in COMMON_TESSERACT_PATHS:
        if path and os.path.exists(path):
            pytesseract.pytesseract.tesseract_cmd = path
            return path
    return None


def _ocr_image(image):
    tesseract_path = _get_available_tesseract()
    if not tesseract_path:
        raise RuntimeError(
            "Tesseract OCR is not installed yet. Searchable PDFs can still be extracted, "
            "but image scans need the Tesseract executable on this computer."
        )

    prepared = ImageOps.grayscale(image)
    return pytesseract.image_to_string(prepared)


def _extract_text_from_pdf(file_bytes):
    document = fitz.open(stream=file_bytes, filetype="pdf")
    text_parts = []

    for page in document:
        page_text = page.get_text("text").strip()
        if page_text:
            text_parts.append(page_text)

    extracted_text = "\n".join(text_parts).strip()
    if len(extracted_text) >= 80:
        return extracted_text

    ocr_parts = []
    for page in document:
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        image = Image.open(io.BytesIO(pix.tobytes("png")))
        page_text = _ocr_image(image).strip()
        if page_text:
            ocr_parts.append(page_text)

    return "\n".join(ocr_parts).strip()


def _extract_text_from_image(file_bytes):
    image = Image.open(io.BytesIO(file_bytes))
    return _ocr_image(image).strip()


def extract_text_from_upload(uploaded_file):
    filename = (uploaded_file.name or "").lower()
    file_bytes = uploaded_file.read()
    uploaded_file.seek(0)

    if filename.endswith(".pdf"):
        return _extract_text_from_pdf(file_bytes)

    if filename.endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp")):
        return _extract_text_from_image(file_bytes)

    raise ValueError("Only PDF and common image files can be scanned for autofill.")


def _extract_first_match(patterns, text, flags=re.IGNORECASE):
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return match.group(1).strip(" .:-")
    return ""


def _clean_extracted_value(value):
    value = re.sub(r"\s+", " ", value).strip(" .:-,\t")
    return value


def _extract_line_after_label(labels, text):
    lines = [line.strip() for line in text.splitlines()]

    for index, line in enumerate(lines):
        normalized = re.sub(r"\s+", " ", line).strip()
        for label in labels:
            if re.match(label, normalized, re.IGNORECASE):
                inline = re.sub(label, "", normalized, count=1, flags=re.IGNORECASE).strip(" :-")
                if inline:
                    return _clean_extracted_value(inline)

                for next_line in lines[index + 1:index + 4]:
                    if next_line.strip():
                        return _clean_extracted_value(next_line)
    return ""


def _parse_date(text):
    date_patterns = [
        r"\b(\d{4}-\d{2}-\d{2})\b",
        r"\b(\d{1,2}/\d{1,2}/\d{4})\b",
        r"\b(\d{1,2}-\d{1,2}-\d{4})\b",
        r"\b(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\b",
        r"\b([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})\b",
    ]

    for pattern in date_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue

        raw_value = match.group(1).strip()
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(raw_value, fmt).date().isoformat()
            except ValueError:
                continue

    return ""


def _infer_document_type(text):
    lowered = text.lower()
    document_types = [
        "memo",
        "letter",
        "report",
        "minutes",
        "circular",
        "petition",
        "brief",
        "invoice",
        "directive",
    ]

    for item in document_types:
        if item in lowered:
            return item.title()
    return ""


def _cleanup_subject(subject):
    subject = _clean_extracted_value(subject)
    subject = re.sub(r"^(re|subject)\s*[:\-]\s*", "", subject, flags=re.IGNORECASE)
    subject = re.sub(r"\s{2,}", " ", subject)
    return subject[:255]


def _infer_subject(text):
    subject = _extract_first_match(
        [
            r"(?:subject|re)\s*[:\-]\s*(.+)",
            r"(?:title)\s*[:\-]\s*(.+)",
        ],
        text,
    )
    if subject:
        return _cleanup_subject(subject.splitlines()[0])

    subject = _extract_line_after_label(
        [r"^subject\s*[:\-]?$", r"^re\s*[:\-]?$", r"^title\s*[:\-]?$"],
        text,
    )
    if subject:
        return _cleanup_subject(subject)

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines[:12]:
        if not 12 <= len(line) <= 140:
            continue
        if re.match(r"^(from|to|date|ref|reference|our ref|your ref|dear|cc|signed)\b", line, re.IGNORECASE):
            continue
        if re.fullmatch(r"[A-Z\s]{3,}", line) and len(line.split()) <= 3:
            continue
        return _cleanup_subject(line)
    return ""


def _infer_description(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    filtered = []
    for line in lines:
        if re.match(r"^(from|to|date|ref|reference|subject|re)\b", line, re.IGNORECASE):
            continue
        filtered.append(line)

    description = " ".join(filtered[:4]).strip()
    return description[:500]


def _infer_party(text, labels, fallback_prefixes):
    direct_match = _extract_first_match(
        [rf"(?:{'|'.join(labels)})\s*[:\-]\s*(.+)"],
        text,
    )
    if direct_match:
        return _clean_extracted_value(direct_match.splitlines()[0])[:255]

    line_match = _extract_line_after_label(
        [rf"^(?:{'|'.join(labels)})\s*[:\-]?$"],
        text,
    )
    if line_match:
        return line_match[:255]

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines[:18]:
        if any(line.lower().startswith(prefix) for prefix in fallback_prefixes):
            return _clean_extracted_value(re.sub(r"^[A-Za-z\s]+[:\-]?\s*", "", line, count=1))[:255]
    return ""


def _infer_direction(origin, destination, text):
    combined = " ".join(filter(None, [origin, destination, text[:600]])).lower()

    if any(hint in destination.lower() for hint in ORGANIZATION_HINTS if destination):
        return "Incoming"

    if any(hint in origin.lower() for hint in ORGANIZATION_HINTS if origin):
        return "Outgoing"

    if "dear director" in combined or "the director" in combined:
        return "Incoming"

    if any(hint in combined for hint in ORGANIZATION_HINTS) and ("ministry" not in combined or "to:" in combined):
        return "Outgoing"

    return ""


def build_document_autofill(text):
    normalized = text.replace("\r", "\n")

    reference_id = _extract_first_match(
        [
            r"(?:reference(?:\s*no\.?)?|ref(?:erence)?(?:\s*id)?|our\s*ref|file\s*no\.?|doc(?:ument)?\s*no\.?)\s*[:#\-]?\s*([A-Z0-9\/\-.]+)",
            r"\b([A-Z]{1,6}\/[A-Z0-9\-\/]{3,})\b",
        ],
        normalized,
    )
    origin = _infer_party(normalized, ["from", "origin", "sender"], ["from", "origin", "sender"])
    destination = _infer_party(normalized, ["to", "destination", "recipient"], ["to", "destination", "recipient"])
    subject = _infer_subject(normalized)
    date_received = _parse_date(normalized)
    document_type = _infer_document_type(normalized)
    description = _infer_description(normalized)
    direction = _infer_direction(origin, destination, normalized)

    data = {
        "reference_id": reference_id[:50],
        "subject": subject[:255],
        "origin": origin[:255],
        "destination": destination[:255],
        "direction": direction,
        "document_type": document_type[:100],
        "date_received": date_received,
        "description": description,
    }

    return {key: value for key, value in data.items() if value}


def build_preview(text, max_length=280):
    compact = " ".join(text.split())
    if len(compact) <= max_length:
        return compact
    return compact[:max_length].rstrip() + "..."

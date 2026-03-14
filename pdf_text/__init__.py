"""
pdf_text — From-scratch PDF parser with semantic text extraction.

PURPOSE:
  Reads PDF object graphs directly (no external PDF library deps),
  extracts semantically-classified text chunks with font/position
  metadata, and includes a lossless byte-perfect codec.

HOW IT FITS:
  Replaces pdfplumber and pymupdf throughout rlm-bmdx for all PDF
  text extraction: fulltext retrieval, table extraction, and diff
  comparison. The only runtime dependency is zlib (stdlib).

PUBLIC API:
  - parse_pdf(path)         → list[dict]   — parse from file path
  - parse_pdf_bytes(data)   → list[dict]   — parse from raw bytes
  - chunks_to_text(chunks)  → str          — join chunks into plain text
  - chunks_to_words(chunks) → list[dict]   — split into word-level dicts
  - extract_rules(path)     → list[dict]   — horizontal line positions
  - PdfParser               — low-level parser class
  - decompose / assemble / verify — lossless byte-perfect codec
"""

# Parser: the main extraction engine
from .parse_pdf import (
    PdfParser,
    parse_pdf,
    parse_pdf_bytes,
    chunks_to_text,
    chunks_to_words,
    extract_rules,
    TableDetectionConfig,
)

# Codec: lossless decompose/assemble/verify round-trip
from .pdf_codec import decompose, assemble, verify

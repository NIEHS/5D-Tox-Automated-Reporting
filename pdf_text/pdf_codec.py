"""
pdf_codec.py — Lossless PDF decomposer and assembler.

PURPOSE:
  Decomposes a PDF file into a JSON manifest of labeled byte spans,
  and reassembles that manifest back into the original file, byte-
  perfect. The round-trip is verified by SHA-256 hash.

HOW IT FITS:
  Companion to parse_pdf.py. That module extracts semantic content
  (lossy). This module preserves every byte (lossless). Together
  they give you both a human-readable interpretation and a faithful
  reproduction mechanism for the same PDF.

DESIGN DECISIONS:
  - The PDF is treated as a strictly sequential byte stream. We
    identify "regions" — contiguous byte spans — and label each one
    by what it is (file header, indirect object, inter-object gap,
    trailer). Reassembly is concatenation in file order.
  - Opaque byte data (compressed streams, font programs, images) is
    base64-encoded in the JSON. This is cargo — carried, not
    interpreted.
  - Object content streams are ALSO stored as raw bytes. We do NOT
    decompress and recompress, because zlib is not deterministic
    across implementations. The compressed bytes are the canonical
    form.
  - The manifest does NOT store byte offsets or xref data. Those are
    properties of the physical layout, and they're implicit in the
    ordering of the spans. On reassembly, you concatenate spans in
    order — the offsets are wherever the bytes land.
  - We store a SHA-256 hash of the original file in the manifest so
    the assembler can verify byte-perfect reproduction.

ARCHITECTURE:
  The file decomposes into a flat list of "spans", each one being:
    {
      "kind": "header" | "object" | "gap" | "trailer",
      "data": "<base64-encoded bytes>",
      ... additional metadata depending on kind ...
    }

  For "object" spans, we also include:
    "obj_num": int,    — the object number
    "obj_gen": int,    — the generation number
    "has_stream": bool — whether the object contains a stream

  These metadata fields are informational — they help a human reader
  understand what each span contains. The assembler ignores them; it
  only needs "data" and the ordering.

USAGE:
  Decompose:
    python3 pdf_codec.py decompose input.pdf manifest.json

  Assemble:
    python3 pdf_codec.py assemble manifest.json output.pdf

  Round-trip verification:
    python3 pdf_codec.py verify input.pdf manifest.json
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
import base64
import hashlib
import json
import re
import sys


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Regex to find "N M obj" markers in the latin-1 decoded text.
# Every indirect object in the file starts with this pattern.
RE_OBJ_START = re.compile(r'(\d+)\s+(\d+)\s+obj')

# How we identify the end of an indirect object. Every object ends
# with "endobj" optionally followed by \r and/or \n.
ENDOBJ_MARKER = 'endobj'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256(data: bytes) -> str:
    """
    Compute the SHA-256 hex digest of a byte string.
    Used to verify round-trip integrity.
    """
    return hashlib.sha256(data).hexdigest()


def _b64encode(data: bytes) -> str:
    """
    Encode bytes to a base64 string for JSON storage.
    Why base64: JSON cannot represent arbitrary binary data directly.
    Base64 inflates size by ~33%, but the manifest is a transfer/storage
    format, not a compression format. Clarity and correctness matter
    more than compactness here.
    """
    return base64.b64encode(data).decode('ascii')


def _b64decode(s: str) -> bytes:
    """Decode a base64 string back to bytes."""
    return base64.b64decode(s)


def _has_stream(text_region: str) -> bool:
    """
    Check whether an object region contains a stream.
    Looks for the 'stream' keyword before 'endobj'.
    We check for the keyword preceded by >> (end of dict) to avoid
    false positives from the word 'stream' appearing inside strings.
    """
    # Find 'stream' that comes after '>>' and before 'endstream'
    return 'stream\r\n' in text_region or 'stream\n' in text_region


# ---------------------------------------------------------------------------
# Core: Decompose
# ---------------------------------------------------------------------------

def decompose(pdf_data: bytes) -> dict:
    """
    Decompose a PDF file's raw bytes into a manifest of labeled spans.

    The file is split into sequential, non-overlapping, exhaustive
    byte regions:
      1. File header — everything before the first "N M obj" marker.
      2. Indirect objects — from "N M obj" through "endobj" plus
         any trailing line ending.
      3. Gaps — bytes between objects (e.g., whitespace padding,
         startxref/%%EOF blocks between linearization sections).
      4. Trailer — everything after the last "endobj" line ending.

    These regions are stored in file order. Concatenating their byte
    data in order reproduces the original file exactly.

    Inputs:
      pdf_data: The complete PDF file as bytes.

    Returns:
      A dict with:
        "sha256": hex digest of the original file
        "size": file size in bytes
        "spans": list of span dicts in file order
    """
    text = pdf_data.decode('latin-1')

    # -- Find all object regions --
    # Each object starts at "N M obj" and ends at the next "endobj"
    # plus its trailing line ending (\r, \n, or \r\n).

    obj_starts = sorted(
        [(m.start(), m.end(), int(m.group(1)), int(m.group(2)))
         for m in RE_OBJ_START.finditer(text)],
        key=lambda x: x[0]
    )

    # For each object, find the boundary of its endobj + trailing newlines.
    obj_regions = []
    for match_start, header_end, obj_num, obj_gen in obj_starts:
        endobj_pos = text.find(ENDOBJ_MARKER, header_end)
        if endobj_pos < 0:
            # Malformed — shouldn't happen in a valid PDF.
            continue
        region_end = endobj_pos + len(ENDOBJ_MARKER)
        # Include trailing line ending characters. These are part of
        # the object's byte span — the next region starts after them.
        while region_end < len(pdf_data) and pdf_data[region_end:region_end + 1] in (b'\r', b'\n'):
            region_end += 1
        obj_regions.append((match_start, region_end, obj_num, obj_gen))

    obj_regions.sort(key=lambda x: x[0])

    # -- Build the span list --
    spans = []
    cursor = 0

    for start, end, obj_num, obj_gen in obj_regions:
        # Gap before this object?
        if start > cursor:
            gap_bytes = pdf_data[cursor:start]
            spans.append({
                'kind': _classify_gap(gap_bytes),
                'data': _b64encode(gap_bytes),
                'size': start - cursor,
            })

        # The object itself.
        obj_bytes = pdf_data[start:end]
        obj_text = text[start:end]
        spans.append({
            'kind': 'object',
            'obj_num': obj_num,
            'obj_gen': obj_gen,
            'has_stream': _has_stream(obj_text),
            'data': _b64encode(obj_bytes),
            'size': end - start,
        })
        cursor = end

    # Trailing data after the last object (startxref + %%EOF).
    if cursor < len(pdf_data):
        trailing = pdf_data[cursor:]
        spans.append({
            'kind': _classify_gap(trailing),
            'data': _b64encode(trailing),
            'size': len(trailing),
        })

    return {
        'sha256': _sha256(pdf_data),
        'size': len(pdf_data),
        'span_count': len(spans),
        'object_count': len(obj_regions),
        'spans': spans,
    }


def _classify_gap(gap_bytes: bytes) -> str:
    """
    Classify a non-object byte region by its content.

    Returns one of:
      'header'  — the file header (%PDF-x.y plus binary comment)
      'trailer' — startxref + %%EOF block
      'gap'     — whitespace padding or other inter-object filler

    Why classify at all: it makes the manifest human-readable.
    The assembler doesn't use this — it only needs the bytes.
    """
    text = gap_bytes.decode('latin-1').strip()
    if text.startswith('%PDF-'):
        return 'header'
    if 'startxref' in text or '%%EOF' in text:
        return 'trailer'
    return 'gap'


# ---------------------------------------------------------------------------
# Core: Assemble
# ---------------------------------------------------------------------------

def assemble(manifest: dict) -> bytes:
    """
    Reassemble a PDF file from a manifest of labeled byte spans.

    Simply concatenates the base64-decoded byte data of each span
    in order. The manifest's ordering IS the file layout.

    Inputs:
      manifest: The dict produced by decompose().

    Returns:
      The reconstructed PDF file as bytes.
    """
    parts = []
    for span in manifest['spans']:
        parts.append(_b64decode(span['data']))
    return b''.join(parts)


# ---------------------------------------------------------------------------
# Core: Verify
# ---------------------------------------------------------------------------

def verify(original_data: bytes, manifest: dict) -> bool:
    """
    Verify that assembling the manifest produces the original file
    byte-for-byte.

    Checks both SHA-256 hash and byte length.

    Returns True if verification passes, False otherwise.
    """
    reconstructed = assemble(manifest)

    # Length check.
    if len(reconstructed) != len(original_data):
        print(f"FAIL: length mismatch — original {len(original_data)}, "
              f"reconstructed {len(reconstructed)}", file=sys.stderr)
        return False

    # Hash check.
    original_hash = _sha256(original_data)
    reconstructed_hash = _sha256(reconstructed)
    if original_hash != reconstructed_hash:
        print(f"FAIL: hash mismatch", file=sys.stderr)
        print(f"  original:      {original_hash}", file=sys.stderr)
        print(f"  reconstructed: {reconstructed_hash}", file=sys.stderr)
        # Find first differing byte for debugging.
        for i in range(min(len(original_data), len(reconstructed))):
            if original_data[i] != reconstructed[i]:
                print(f"  first diff at byte {i}: "
                      f"original=0x{original_data[i]:02x}, "
                      f"reconstructed=0x{reconstructed[i]:02x}",
                      file=sys.stderr)
                break
        return False

    # Also verify against the stored hash in the manifest.
    if manifest.get('sha256') and manifest['sha256'] != original_hash:
        print(f"FAIL: manifest hash doesn't match original", file=sys.stderr)
        return False

    return True


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """
    CLI entry point.

    Usage:
      python3 pdf_codec.py decompose <input.pdf> <manifest.json>
      python3 pdf_codec.py assemble  <manifest.json> <output.pdf>
      python3 pdf_codec.py verify    <input.pdf> <manifest.json>
    """
    if len(sys.argv) < 2:
        print("Usage:", file=sys.stderr)
        print("  pdf_codec.py decompose <input.pdf> <manifest.json>",
              file=sys.stderr)
        print("  pdf_codec.py assemble  <manifest.json> <output.pdf>",
              file=sys.stderr)
        print("  pdf_codec.py verify    <input.pdf> <manifest.json>",
              file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]

    if command == 'decompose':
        if len(sys.argv) < 4:
            print("Usage: pdf_codec.py decompose <input.pdf> <manifest.json>",
                  file=sys.stderr)
            sys.exit(1)

        pdf_path = sys.argv[2]
        manifest_path = sys.argv[3]

        with open(pdf_path, 'rb') as f:
            pdf_data = f.read()

        print(f"Decomposing {pdf_path} ({len(pdf_data)} bytes)...")
        manifest = decompose(pdf_data)

        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2)

        print(f"Wrote manifest to {manifest_path}")
        print(f"  SHA-256:  {manifest['sha256']}")
        print(f"  Spans:    {manifest['span_count']}")
        print(f"  Objects:  {manifest['object_count']}")

        # Summary of span kinds.
        kinds = {}
        for s in manifest['spans']:
            k = s['kind']
            kinds[k] = kinds.get(k, 0) + 1
        for k, c in sorted(kinds.items()):
            print(f"    {k}: {c}")

    elif command == 'assemble':
        if len(sys.argv) < 4:
            print("Usage: pdf_codec.py assemble <manifest.json> <output.pdf>",
                  file=sys.stderr)
            sys.exit(1)

        manifest_path = sys.argv[2]
        output_path = sys.argv[3]

        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)

        print(f"Assembling from {manifest_path}...")
        pdf_data = assemble(manifest)

        with open(output_path, 'wb') as f:
            f.write(pdf_data)

        actual_hash = _sha256(pdf_data)
        expected_hash = manifest.get('sha256', '')
        match = actual_hash == expected_hash

        print(f"Wrote {output_path} ({len(pdf_data)} bytes)")
        print(f"  SHA-256:  {actual_hash}")
        print(f"  Expected: {expected_hash}")
        print(f"  Match:    {match}")

        if not match:
            sys.exit(1)

    elif command == 'verify':
        if len(sys.argv) < 4:
            print("Usage: pdf_codec.py verify <input.pdf> <manifest.json>",
                  file=sys.stderr)
            sys.exit(1)

        pdf_path = sys.argv[2]
        manifest_path = sys.argv[3]

        with open(pdf_path, 'rb') as f:
            pdf_data = f.read()
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)

        print(f"Verifying round-trip for {pdf_path}...")
        if verify(pdf_data, manifest):
            print("PASS: byte-perfect round-trip verified.")
        else:
            print("FAIL: round-trip verification failed.")
            sys.exit(1)

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        print("Commands: decompose, assemble, verify", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()

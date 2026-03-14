"""
parse_pdf.py — From-scratch PDF parser for Bookshelf_NBK589955.pdf

PURPOSE:
  Reads raw PDF bytes, resolves the object graph (including compressed
  Object Streams), walks the page tree, decompresses content streams,
  tokenizes PDF operators, extracts text, and classifies every chunk
  by its semantic role using the document's marked-content tags.

HOW IT FITS:
  This is the sole module. Run it directly:
      python3 parse_pdf.py Bookshelf_NBK589955.pdf [--output out.json]

DESIGN DECISIONS:
  - No external PDF libraries. We rely only on zlib (for FlateDecode)
    and the Python standard library, working directly from the PDF
    specification's object/stream/operator model.
  - The PDF uses Object Streams (ObjStm) to compress most of its ~8600
    objects. We must decode those before we can resolve page objects.
  - Tagged PDF: content streams use BDC/EMC marked-content operators
    with structure tags (/P, /H1, /H2, /Figure, /Caption, /Table,
    /TOCI, /Reference, /Artifact). We use these as the primary signal
    for semantic classification.
  - Text is encoded via TJ (kerning arrays) and Tj (simple strings)
    operators. TJ arrays interleave string literals with numeric
    kerning adjustments — we reconstruct readable text from these.
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
import re
import zlib
import json
import sys
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Regex to locate "N M obj" markers in the raw PDF text.
# We use latin-1 decoding throughout because PDF is a binary format
# where bytes 0x00–0xFF map 1:1 to characters — latin-1 preserves
# every byte without encoding errors, unlike UTF-8.
RE_OBJ_MARKER = re.compile(r'(\d+)\s+(\d+)\s+obj')

# Matches a dictionary-bearing object: "N M obj << ... >>"
# The non-greedy .*? inside << >> handles nested << >> poorly,
# so we use a custom parser for complex dicts. This regex is only
# used for quick scans of simple objects.
RE_OBJ_DICT = re.compile(
    r'(\d+)\s+0\s+obj\s*<<(.*?)>>\s*(stream|endobj)',
    re.DOTALL
)

# Matches the start of a stream right after its dictionary.
RE_STREAM_START = re.compile(
    rb'(\d+)\s+0\s+obj\s*<<(.*?)>>\s*stream(\r\n|\r|\n)',
    re.DOTALL
)

# Structure tags we recognise from the content streams' BDC operators.
# These come from the PDF's logical structure (tagged PDF).
# Why this set: we observed exactly these tags in the decoded streams.
STRUCTURE_TAGS = {
    'P',          # Paragraph
    'H1',         # Heading level 1
    'H2',         # Heading level 2
    'H3',         # Heading level 3
    'Figure',     # Image / graphic
    'Caption',    # Figure or table caption
    'Table',      # Table element
    'TOCI',       # Table-of-contents item
    'Reference',  # Cross-reference / citation
    'Artifact',   # Non-structural decoration (headers, footers, page numbers)
    'Span',       # Inline span (sometimes used for styling)
    'L',          # List
    'LI',         # List item
    'LBody',      # List item body
    'Lbl',        # List label (bullet/number)
    'TD',         # Table data cell
    'TH',         # Table header cell
    'TR',         # Table row
    'THead',      # Table head group
    'TBody',      # Table body group
    'PlacedPDF',  # Embedded PDF (logo etc.)
    'Link',       # Hyperlink
}

# Semantic classification labels we assign to each chunk.
# Why these: they map directly to the structure tags observed in
# this document, plus positional heuristics for cover elements.
CHUNK_TYPES = {
    'heading',        # H1, H2, H3
    'paragraph',      # P
    'figure',         # Figure
    'caption',        # Caption
    'table',          # Table, TD, TH, TR (from PDF tags, rare)
    'table_caption',  # "Table N." header line detected by heuristic
    'table_cell',     # Data/header cell within a table region
    'table_footnote', # Footnote text at the end of a table
    'toc_entry',      # TOCI
    'reference',      # Reference
    'header',         # Artifact with /Subtype /Header
    'footer',         # Artifact with /Subtype /Footer
    'artifact',       # Other Artifact (decorative)
    'list_item',      # LI, LBody, Lbl
    'cover_element',  # First page non-tagged or title-sized text
    'unknown',        # Fallback
}


# ---------------------------------------------------------------------------
# Type definitions
# ---------------------------------------------------------------------------

class PdfObject:
    """
    Represents a single PDF indirect object.

    Attributes:
        num: The object number (e.g., 8641 in "8641 0 obj").
        gen: The generation number (almost always 0).
        definition: The raw string content of the object's dictionary
                    or value (everything between "obj" and "endobj",
                    excluding stream data).
        stream_data: Raw bytes of the object's stream, if it has one.
                     None for non-stream objects.

    Why a class instead of a dict: we pass these around frequently
    and attribute access is clearer than string-keyed lookups.
    """
    def __init__(self, num: int, gen: int = 0, definition: str = '',
                 stream_data: bytes = None):
        self.num = num
        self.gen = gen
        self.definition = definition
        self.stream_data = stream_data

    def __repr__(self):
        has_stream = ' +stream' if self.stream_data else ''
        return f'<PdfObject {self.num} {self.gen}{has_stream}>'


class TextChunk:
    """
    A semantically classified piece of extracted text.

    Attributes:
        page: 1-based page number.
        chunk_type: One of CHUNK_TYPES (e.g., 'heading', 'paragraph').
        tag: The raw PDF structure tag (e.g., 'H1', 'P', 'Artifact').
        text: The reconstructed text content.
        font: Font name used (e.g., '/TT0', '/T1_0').
        font_size: Font size in points, from the text matrix.
        x: Horizontal position (points from left edge).
        y: Vertical position (points from bottom edge).
        mcid: Marked-content ID, linking to the structure tree.
        properties: Additional BDC properties (e.g., Lang, Subtype).

    Why all these fields: the caller can filter/sort by any dimension —
    spatial position for layout reconstruction, font_size for visual
    hierarchy, chunk_type for semantic queries.
    """
    def __init__(self):
        self.page: int = 0
        self.chunk_type: str = 'unknown'
        self.tag: str = ''
        self.text: str = ''
        self.font: str = ''
        self.font_size: float = 0.0
        self.x: float = 0.0
        self.y: float = 0.0
        self.mcid: Optional[int] = None
        self.properties: dict = {}

    def to_dict(self) -> dict:
        """Serialize to a plain dict for JSON output."""
        d = {
            'page': self.page,
            'type': self.chunk_type,
            'tag': self.tag,
            'text': self.text,
        }
        # Only include non-empty optional fields to keep output concise.
        if self.font:
            d['font'] = self.font
        if self.font_size:
            d['font_size'] = round(self.font_size, 2)
        if self.x or self.y:
            d['position'] = {'x': round(self.x, 2), 'y': round(self.y, 2)}
        if self.mcid is not None:
            d['mcid'] = self.mcid
        if self.properties:
            d['properties'] = self.properties
        return d


# ---------------------------------------------------------------------------
# Helper / utility functions (private)
# ---------------------------------------------------------------------------

def _read_file(path: str) -> bytes:
    """
    Read the entire PDF file into memory as raw bytes.

    Why read all at once: PDF requires random access (xref points to
    arbitrary offsets). Memory-mapping would also work but for a 2 MB
    file, reading it all is simpler and fast enough.
    """
    with open(path, 'rb') as f:
        return f.read()


def _decompress(stream_bytes: bytes, filter_name: str) -> bytes:
    """
    Decompress a PDF stream given its /Filter value.

    We only handle /FlateDecode because that's the only compression
    this particular PDF uses. The PDF spec also defines /ASCIIHexDecode,
    /ASCII85Decode, /LZWDecode, /RunLengthDecode, /CCITTFaxDecode,
    /JBIG2Decode, /DCTDecode, /JPXDecode, and /Crypt — but none of
    those appear in this file's content or object streams.
    """
    if 'FlateDecode' in filter_name:
        try:
            return zlib.decompress(stream_bytes)
        except zlib.error:
            # Some streams have extra bytes or bad checksums.
            # Try with wbits=-15 (raw deflate, no header).
            try:
                return zlib.decompress(stream_bytes, -15)
            except zlib.error:
                return b''
    # No compression or unknown filter — return as-is.
    return stream_bytes


def _extract_dict_value(dict_text: str, key: str) -> Optional[str]:
    """
    Extract a simple value for a /Key from a PDF dictionary string.

    This handles: /Key 123, /Key /Name, /Key(string), /Key true.
    It does NOT handle nested dictionaries or arrays — for those,
    use the tokenizer. This is a quick-and-dirty helper for pulling
    /Length, /Filter, /First, /N, etc. from object headers.

    Why regex and not a full parser here: these values are always
    simple scalars in the contexts where we call this function.
    """
    # Try numeric value
    m = re.search(rf'/{key}\s+(\d+)', dict_text)
    if m:
        return m.group(1)
    # Try name value
    m = re.search(rf'/{key}\s*/([A-Za-z0-9_.+-]+)', dict_text)
    if m:
        return m.group(1)
    # Try indirect reference
    m = re.search(rf'/{key}\s+(\d+\s+\d+\s+R)', dict_text)
    if m:
        return m.group(1)
    return None


def _parse_string_literal(s: str) -> str:
    """
    Parse a PDF string literal (parenthesised), handling escape sequences.

    PDF string escapes (Table 3 in the spec):
        \\n  -> newline
        \\r  -> carriage return
        \\t  -> tab
        \\b  -> backspace
        \\f  -> form feed
        \\(  -> literal (
        \\)  -> literal )
        \\\\  -> literal backslash
        \\DDD -> octal character code (1-3 digits)

    Balanced parentheses inside the string do NOT need escaping —
    the parser counts nesting depth. We handle that in the tokenizer;
    by the time we get here, the string boundaries are already resolved.

    Why this matters: TJ arrays contain these string literals, and
    octal escapes like \\256 encode special characters (e.g., ®).
    """
    result = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == '\\' and i + 1 < len(s):
            next_ch = s[i + 1]
            if next_ch == 'n':
                result.append('\n')
                i += 2
            elif next_ch == 'r':
                result.append('\r')
                i += 2
            elif next_ch == 't':
                result.append('\t')
                i += 2
            elif next_ch == 'b':
                result.append('\b')
                i += 2
            elif next_ch == 'f':
                result.append('\f')
                i += 2
            elif next_ch == '(':
                result.append('(')
                i += 2
            elif next_ch == ')':
                result.append(')')
                i += 2
            elif next_ch == '\\':
                result.append('\\')
                i += 2
            elif next_ch.isdigit():
                # Octal escape: 1-3 octal digits
                octal = next_ch
                j = i + 2
                while j < len(s) and j < i + 4 and s[j].isdigit() and s[j] in '01234567':
                    octal += s[j]
                    j += 1
                result.append(chr(int(octal, 8)))
                i = j
            elif next_ch == '\n':
                # Backslash at end of line: line continuation
                i += 2
            elif next_ch == '\r':
                # Line continuation (CR or CRLF)
                i += 2
                if i < len(s) and s[i] == '\n':
                    i += 1
            else:
                # Unknown escape — just include the character.
                result.append(next_ch)
                i += 2
        else:
            result.append(ch)
            i += 1
    return ''.join(result)


def _extract_parenthesised_string(text: str, start: int) -> tuple[str, int]:
    """
    Extract a balanced parenthesised string from text starting at position
    `start` (which must point to the opening '(').

    Returns (inner_content, end_position).

    Why a dedicated function: PDF allows nested parentheses without
    escaping as long as they're balanced. A simple regex can't handle
    arbitrary nesting, so we count depth manually.
    """
    assert text[start] == '('
    depth = 0
    i = start
    while i < len(text):
        ch = text[i]
        if ch == '\\':
            i += 2  # skip escaped character
            continue
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i + 1
        i += 1
    # Unbalanced — return what we have.
    return text[start + 1:], len(text)


def _extract_hex_string(text: str, start: int) -> tuple[str, int]:
    """
    Extract a hex string <...> from text starting at the '<' character.

    Returns (decoded_string, end_position).

    PDF hex strings contain pairs of hex digits. Whitespace is ignored.
    An odd final digit is treated as if followed by 0 (per spec).
    """
    assert text[start] == '<'
    end = text.index('>', start)
    hex_body = text[start + 1:end].replace(' ', '').replace('\n', '').replace('\r', '')
    if len(hex_body) % 2 == 1:
        hex_body += '0'
    chars = []
    for j in range(0, len(hex_body), 2):
        chars.append(chr(int(hex_body[j:j + 2], 16)))
    return ''.join(chars), end + 1


def _parse_cmap(cmap_text: str) -> dict[int, str]:
    """
    Parse a ToUnicode CMap stream and return a mapping from character
    codes to Unicode strings.

    CMap syntax we handle:
        beginbfchar / endbfchar — single-character mappings:
            <1F> <006600660069>  means char 0x1F → "ffi"
        beginbfrange / endbfrange — range mappings:
            <20> <7E> <0020>    means chars 0x20–0x7E map to U+0020–U+007E

    Why this matters: PDF fonts often use custom encodings where glyph
    codes don't correspond to Unicode. The ToUnicode CMap provides the
    authoritative mapping. Without it, ligatures like "ffi", "fl", "fi"
    appear as unprintable control characters.
    """
    mapping = {}

    # Parse beginbfchar...endbfchar blocks.
    for block in re.finditer(
            r'beginbfchar\s*(.*?)\s*endbfchar', cmap_text, re.DOTALL):
        body = block.group(1)
        # Each line: <srcCode> <dstUnicode>
        for line_match in re.finditer(r'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>',
                                      body):
            src = int(line_match.group(1), 16)
            dst_hex = line_match.group(2)
            # Destination can be multi-byte Unicode (e.g., 006600660069 = "ffi").
            # Each pair of hex digits is one byte of UTF-16BE.
            dst_bytes = bytes.fromhex(dst_hex)
            try:
                dst_str = dst_bytes.decode('utf-16-be')
            except (UnicodeDecodeError, ValueError):
                dst_str = dst_bytes.decode('latin-1')
            mapping[src] = dst_str

    # Parse beginbfrange...endbfrange blocks.
    for block in re.finditer(
            r'beginbfrange\s*(.*?)\s*endbfrange', cmap_text, re.DOTALL):
        body = block.group(1)
        for line_match in re.finditer(
                r'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>',
                body):
            start = int(line_match.group(1), 16)
            end = int(line_match.group(2), 16)
            dst_start_hex = line_match.group(3)
            dst_start = int(dst_start_hex, 16)
            for code in range(start, end + 1):
                char_val = dst_start + (code - start)
                mapping[code] = chr(char_val)

    return mapping


def _apply_cmap(text: str, cmap: dict[int, str],
                two_byte: bool = False) -> str:
    """
    Apply a ToUnicode CMap mapping to a string.

    In single-byte mode (default), each character is looked up by its
    ordinal in the CMap. In two-byte mode (Identity-H encoding), input
    is consumed in pairs: code = ord(text[i]) << 8 | ord(text[i+1]).

    Why two modes: standard Type1/TrueType fonts use single-byte char
    codes (one byte = one glyph). But Typst and some CID fonts use
    Identity-H encoding where glyph IDs are two-byte values. Without
    two-byte mode, "Na" (bytes 0x00,0x4E,0x00,0x61) gets processed as
    four separate single-byte lookups instead of two glyph IDs (0x004E
    = "N", 0x0061 = "a"), producing garbled "N a t i o n a l" output.
    """
    result = []
    if two_byte:
        # Two-byte (Identity-H) mode: consume pairs of characters.
        i = 0
        while i + 1 < len(text):
            code = (ord(text[i]) << 8) | ord(text[i + 1])
            if code in cmap:
                result.append(cmap[code])
            elif code > 0:
                # Fallback: try interpreting as direct Unicode codepoint
                try:
                    result.append(chr(code))
                except (ValueError, OverflowError):
                    result.append(text[i:i + 2])
            i += 2
        # If odd number of chars, handle the trailing byte.
        if i < len(text):
            code = ord(text[i])
            result.append(cmap.get(code, text[i]))
    else:
        # Single-byte mode: each character is one glyph code.
        for ch in text:
            code = ord(ch)
            if code in cmap:
                result.append(cmap[code])
            else:
                result.append(ch)
    return ''.join(result)


def _text_from_tj_array(items: list, cmap: dict[int, str] = None,
                        two_byte: bool = False) -> str:
    """
    Reconstruct readable text from a TJ array.

    A TJ array alternates between string literals and numeric kerning
    adjustments. For example:
        [(Hel) -20 (lo W) 15 (orld)]

    The numbers are in thousandths of a unit of text space. Large
    negative numbers (< -100) typically represent word spaces.
    We insert a space for those. Small adjustments are just kerning
    (letter-spacing tweaks) and are ignored.

    Why -100 as threshold: empirically, this PDF uses values around
    -200 to -300 for intentional inter-word gaps, while kerning
    adjustments are typically -20 to +20. -100 is a safe midpoint.

    Args:
        items:    List of strings and numbers from the TJ array.
        cmap:     ToUnicode CMap mapping (char code → Unicode string).
        two_byte: If True, apply CMap in two-byte (Identity-H) mode.
    """
    parts = []
    for item in items:
        if isinstance(item, str):
            parsed = _parse_string_literal(item)
            if cmap:
                parsed = _apply_cmap(parsed, cmap, two_byte=two_byte)
            parts.append(parsed)
        elif isinstance(item, (int, float)):
            # The TJ displacement is SUBTRACTED from the current
            # text position. Positive moves LEFT (tightens), negative
            # moves RIGHT (loosens). A value < -100 in 1/1000 em
            # represents an intentional word space.
            if item < -100:
                parts.append(' ')
    return ''.join(parts)


# ---------------------------------------------------------------------------
# Core logic — PDF object resolution
# ---------------------------------------------------------------------------

class PdfParser:
    """
    Low-level PDF parser that resolves the object graph and extracts
    page content streams.

    Inputs: raw PDF file bytes.
    Outputs: per-page lists of TextChunk objects.

    Architecture:
        1. _index_direct_objects(): scan file for "N 0 obj" markers,
           record byte offsets for each object number.
        2. _decode_object_streams(): find all /Type/ObjStm objects,
           decompress them, parse the embedded object definitions.
        3. _build_page_list(): walk the /Pages tree starting from the
           /Root catalog to get page objects in document order.
        4. _decode_content_stream(): for a given page, find its
           /Contents reference, decompress, return the raw operator text.
        5. _parse_content_stream(): tokenize operators and extract
           text chunks with structure tags and position info.
        6. _classify_chunk(): assign semantic type from tag + context.
    """

    def __init__(self, raw_data: bytes):
        # The complete file as bytes.
        self.raw = raw_data
        # Latin-1 decoded text for regex scanning.
        # Why latin-1: see module docstring.
        self.text = raw_data.decode('latin-1')
        # Maps object number -> byte offset in the file (for direct objects).
        self.direct_obj_offsets: dict[int, int] = {}
        # Maps object number -> definition string (for ObjStm-embedded objects).
        self.embedded_objects: dict[int, str] = {}
        # Ordered list of page object numbers.
        self.page_obj_nums: list[int] = []
        # Per-page font CMap cache: {page_obj_num: {font_name: cmap_dict}}.
        # Built lazily when processing each page.
        self._font_cmaps: dict[int, dict[str, dict[int, str]]] = {}
        # Per-page font two-byte flag: {page_obj_num: {font_name: bool}}.
        # True for Identity-H encoded fonts where CMap codes are two-byte.
        self._font_two_byte: dict[int, dict[str, bool]] = {}

    def parse(self) -> list[TextChunk]:
        """
        Main entry point. Returns a flat list of TextChunk objects,
        ordered by page number then by appearance in the content stream.
        """
        self._index_direct_objects()
        self._decode_object_streams()
        self._build_page_list()
        return self._extract_all_pages()

    # -- Step 1: Index direct objects --

    def _index_direct_objects(self):
        """
        Scan the file for "N 0 obj" markers and record each object's
        byte offset.

        Why not use the xref table/stream: this PDF's xref is a
        compressed stream (xref stream with FlateDecode + Predictor),
        which is complex to decode. Scanning for obj markers is simpler
        and sufficient — we only need to find objects that are stored
        directly in the file (as opposed to inside ObjStm streams).
        The scan runs in ~10ms for a 2 MB file.
        """
        for m in RE_OBJ_MARKER.finditer(self.text):
            obj_num = int(m.group(1))
            # Store the offset of the start of the match.
            self.direct_obj_offsets[obj_num] = m.start()

    @staticmethod
    def _find_balanced_dict(text: str, start: int) -> str:
        """
        Starting at a '<<' in text, find the matching '>>' respecting
        nesting of inner << >> pairs.

        Returns the full string from << to >> inclusive.

        Why this is needed: PDF dictionaries can nest (e.g.,
        /MarkInfo<</Marked true>>). A non-greedy regex <<(.*?)>>
        stops at the FIRST >>, which is the inner dict's closing
        delimiter — not the outer one. This function counts depth.
        """
        assert text[start:start + 2] == '<<', f"Expected '<<' at pos {start}"
        depth = 0
        i = start
        while i < len(text):
            if text[i:i + 2] == '<<':
                depth += 1
                i += 2
            elif text[i:i + 2] == '>>':
                depth -= 1
                i += 2
                if depth == 0:
                    return text[start:i]
            elif text[i] == '(':
                # Skip over parenthesised strings (they may contain < or >).
                _, i = _extract_parenthesised_string(text, i)
            else:
                i += 1
        # Unbalanced — return what we have.
        return text[start:]

    # -- Step 2: Decode Object Streams --

    def _decode_object_streams(self):
        """
        Find all Object Streams (/Type/ObjStm), decompress them, and
        parse the contained objects into self.embedded_objects.

        An Object Stream (PDF 1.5+) packs multiple non-stream objects
        into a single compressed stream. The stream's data begins with
        an index: pairs of (object_number, byte_offset) for N objects,
        taking up /First bytes. After that comes the concatenated
        object definitions.

        Why this is necessary: this PDF stores ~8400 of its ~8600
        objects in ObjStm containers. Without decoding these, we can't
        find page dictionaries, font resources, or the page tree.

        Approach: instead of using a regex that mishandles nested <<>>,
        we scan for each "N 0 obj" marker, use the balanced-dict parser
        to get the full dictionary, then check for /Type/ObjStm.
        """
        for obj_num, offset in sorted(self.direct_obj_offsets.items()):
            # Get a chunk of text starting at this object.
            chunk = self.text[offset:offset + 20000]
            obj_header = re.match(r'\d+\s+\d+\s+obj\s*', chunk)
            if not obj_header:
                continue
            after = chunk[obj_header.end():]
            if not after.startswith('<<'):
                continue

            # Parse the full dictionary with nesting support.
            full_dict = self._find_balanced_dict(after, 0)

            # Only process Object Streams.
            if '/Type' not in full_dict or 'ObjStm' not in full_dict:
                continue

            first_s = _extract_dict_value(full_dict, 'First')
            n_s = _extract_dict_value(full_dict, 'N')
            length_s = _extract_dict_value(full_dict, 'Length')
            filter_s = _extract_dict_value(full_dict, 'Filter') or ''

            if not all([first_s, n_s, length_s]):
                continue

            first = int(first_s)
            n = int(n_s)
            length = int(length_s)

            # Find stream data: it starts right after the dict + "stream\r\n".
            dict_end_in_file = offset + obj_header.end() + len(full_dict)
            rest = self.text[dict_end_in_file:dict_end_in_file + 20]
            stream_kw = rest.find('stream')
            if stream_kw < 0:
                continue
            # Skip past "stream" and the line ending (\r\n or \n).
            stream_start_text = dict_end_in_file + stream_kw + len('stream')
            # In the raw bytes, skip the line ending.
            raw_pos = stream_start_text
            if raw_pos < len(self.raw) and self.raw[raw_pos:raw_pos + 1] == b'\r':
                raw_pos += 1
            if raw_pos < len(self.raw) and self.raw[raw_pos:raw_pos + 1] == b'\n':
                raw_pos += 1

            stream_raw = self.raw[raw_pos:raw_pos + length]
            decompressed = _decompress(stream_raw, filter_s)
            if not decompressed:
                continue

            dec_text = decompressed.decode('latin-1')

            # Parse the index region: N pairs of (obj_num, offset).
            index_part = dec_text[:first]
            tokens = index_part.split()
            entries = []
            for i in range(0, min(len(tokens), n * 2), 2):
                entries.append((int(tokens[i]), int(tokens[i + 1])))

            # Extract each embedded object's definition.
            content = dec_text[first:]
            for i, (obj_num_inner, inner_offset) in enumerate(entries):
                if i + 1 < len(entries):
                    end = entries[i + 1][1]
                else:
                    end = len(content)
                self.embedded_objects[obj_num_inner] = content[inner_offset:end].strip()

    def _get_object_definition(self, obj_num: int) -> str:
        """
        Resolve an object's definition string by number.

        Checks embedded objects first (from ObjStm), then falls back
        to direct objects in the file. Returns the dictionary/value
        text without the "N 0 obj" / "endobj" wrapper.

        Why embedded first: most objects in this PDF are in ObjStm
        containers, so checking there first is faster on average.
        """
        # Check ObjStm-embedded objects.
        if obj_num in self.embedded_objects:
            return self.embedded_objects[obj_num]

        # Fall back to direct object in file.
        if obj_num in self.direct_obj_offsets:
            offset = self.direct_obj_offsets[obj_num]
            chunk = self.text[offset:offset + 20000]
            # Skip past "N 0 obj"
            obj_start = chunk.find('obj')
            if obj_start < 0:
                return ''
            after_obj = chunk[obj_start + 3:].lstrip()
            if after_obj.startswith('<<'):
                # Use balanced dict parser to handle nested <<>>.
                return self._find_balanced_dict(after_obj, 0)
            # Non-dict object — return up to endobj or stream.
            end = after_obj.find('endobj')
            if end < 0:
                end = after_obj.find('stream')
            if end < 0:
                end = 2000
            return after_obj[:end].strip()
        return ''

    def _get_stream_data(self, obj_num: int) -> Optional[bytes]:
        """
        Get the decompressed stream data for a direct (non-embedded)
        stream object.

        Returns None if the object has no stream or decompression fails.

        Why only direct objects: objects inside ObjStm containers
        cannot themselves be stream objects (per the PDF spec, §7.5.7).
        Content streams are always direct objects.
        """
        if obj_num not in self.direct_obj_offsets:
            return None

        offset = self.direct_obj_offsets[obj_num]
        chunk = self.text[offset:offset + 20000]

        # Skip past "N 0 obj".
        obj_header = re.match(r'\d+\s+\d+\s+obj\s*', chunk)
        if not obj_header:
            return None
        after = chunk[obj_header.end():]
        if not after.startswith('<<'):
            return None

        # Use balanced dict parser.
        full_dict = self._find_balanced_dict(after, 0)
        length_s = _extract_dict_value(full_dict, 'Length')
        if not length_s:
            return None
        length = int(length_s)
        filter_s = _extract_dict_value(full_dict, 'Filter') or ''

        # Find "stream" keyword after the dict.
        dict_end_abs = offset + obj_header.end() + len(full_dict)
        rest = self.text[dict_end_abs:dict_end_abs + 20]
        stream_kw = rest.find('stream')
        if stream_kw < 0:
            return None

        # Skip past "stream" and line ending.
        raw_pos = dict_end_abs + stream_kw + len('stream')
        if raw_pos < len(self.raw) and self.raw[raw_pos:raw_pos + 1] == b'\r':
            raw_pos += 1
        if raw_pos < len(self.raw) and self.raw[raw_pos:raw_pos + 1] == b'\n':
            raw_pos += 1

        stream_raw = self.raw[raw_pos:raw_pos + length]
        return _decompress(stream_raw, filter_s)

    # -- Step 3: Build page list --

    def _build_page_list(self):
        """
        Walk the /Pages tree from the catalog's /Root to collect all
        leaf /Page objects in document order.

        The page tree is a balanced tree of /Pages (intermediate) and
        /Page (leaf) nodes. Intermediate nodes have /Kids arrays listing
        children. We traverse depth-first, left-to-right, collecting
        leaf page object numbers.

        Why we need this: the page tree defines document order. Object
        numbers alone don't tell you which page is first, second, etc.
        """
        # Find the root catalog.
        # Strategy: check every known object (both embedded and direct)
        # for /Type/Catalog or /Type /Catalog. We check direct objects
        # by resolving their full (nested-dict-aware) definitions.
        root_num = None

        # Check embedded objects first (faster, most objects are here).
        for obj_num, defn in self.embedded_objects.items():
            if '/Type' in defn and '/Catalog' in defn:
                root_num = obj_num
                break

        if root_num is None:
            # Check direct objects using the balanced-dict resolver.
            for obj_num in self.direct_obj_offsets:
                defn = self._get_object_definition(obj_num)
                if '/Type' in defn and '/Catalog' in defn:
                    root_num = obj_num
                    break
        if root_num is None:
            print("ERROR: Could not find catalog object.", file=sys.stderr)
            return

        catalog = self._get_object_definition(root_num)
        pages_ref = re.search(r'/Pages\s+(\d+)\s+0\s+R', catalog)
        if not pages_ref:
            print("ERROR: Catalog has no /Pages.", file=sys.stderr)
            return

        pages_root = int(pages_ref.group(1))
        self.page_obj_nums = []
        self._walk_page_tree(pages_root)

    def _walk_page_tree(self, obj_num: int):
        """
        Recursively walk a /Pages or /Page node, appending leaf page
        object numbers to self.page_obj_nums.
        """
        defn = self._get_object_definition(obj_num)
        if not defn:
            return

        # Check if this is a leaf /Page or intermediate /Pages.
        # /Pages nodes have /Kids; /Page nodes have /Contents (or not).
        kids_match = re.search(r'/Kids\s*\[(.*?)\]', defn, re.DOTALL)
        if kids_match:
            # Intermediate /Pages node — recurse into children.
            refs = re.findall(r'(\d+)\s+0\s+R', kids_match.group(1))
            for ref in refs:
                self._walk_page_tree(int(ref))
        else:
            # Leaf /Page node.
            self.page_obj_nums.append(obj_num)

    # -- Step 4: Decode content streams --

    def _get_page_content(self, page_obj_num: int) -> Optional[str]:
        """
        For a given page object, find its /Contents reference,
        decompress the stream, and return the decoded text.

        /Contents can be:
          - A direct reference to a stream object (e.g., /Contents 8643 0 R)
          - An array of references (e.g., /Contents [8643 0 R 8644 0 R])
            which should be concatenated in order.

        Returns None if the page has no content or decompression fails.
        """
        defn = self._get_object_definition(page_obj_num)
        if not defn:
            return None

        # Try single reference first.
        single = re.search(r'/Contents\s+(\d+)\s+0\s+R', defn)
        if single:
            stream = self._get_stream_data(int(single.group(1)))
            if stream:
                return stream.decode('latin-1')
            return None

        # Try array of references.
        arr = re.search(r'/Contents\s*\[(.*?)\]', defn, re.DOTALL)
        if arr:
            refs = re.findall(r'(\d+)\s+0\s+R', arr.group(1))
            parts = []
            for ref in refs:
                stream = self._get_stream_data(int(ref))
                if stream:
                    parts.append(stream.decode('latin-1'))
            if parts:
                return '\n'.join(parts)

        return None

    # -- Step 4b: Resolve font ToUnicode CMaps --

    def _resolve_font_cmaps(self, page_obj_num: int) -> dict[str, dict[int, str]]:
        """
        For a given page object, find its /Resources/Font dictionary,
        resolve each font's /ToUnicode CMap stream, parse it, and
        return {font_name: {char_code: unicode_string}}.

        The font resource dict maps names like /TT0, /T1_0 to font
        object references. Each font object may have a /ToUnicode
        entry pointing to a CMap stream.

        Why per-page: different pages may use different font subsets
        with different ToUnicode mappings. We cache results to avoid
        re-parsing the same font across pages that share resources.
        """
        if page_obj_num in self._font_cmaps:
            return self._font_cmaps[page_obj_num]

        cmaps = {}
        defn = self._get_object_definition(page_obj_num)
        if not defn:
            self._font_cmaps[page_obj_num] = cmaps
            return cmaps

        # Find /Resources — may be inline or a reference.
        resources_ref = re.search(r'/Resources\s+(\d+)\s+0\s+R', defn)
        if resources_ref:
            resources_text = self._get_object_definition(int(resources_ref.group(1)))
        else:
            # Inline resources dict.
            res_start = defn.find('/Resources')
            if res_start < 0:
                self._font_cmaps[page_obj_num] = cmaps
                return cmaps
            # Find the << after /Resources.
            rest = defn[res_start + len('/Resources'):]
            rest = rest.lstrip()
            if rest.startswith('<<'):
                resources_text = self._find_balanced_dict(rest, 0)
            else:
                self._font_cmaps[page_obj_num] = cmaps
                return cmaps

        # Find /Font dict within resources.
        font_start = resources_text.find('/Font')
        if font_start < 0:
            self._font_cmaps[page_obj_num] = cmaps
            return cmaps

        rest = resources_text[font_start + len('/Font'):]
        rest = rest.lstrip()

        # Font dict can be inline << >> or a reference.
        font_ref = re.match(r'(\d+)\s+0\s+R', rest)
        if font_ref:
            font_dict_text = self._get_object_definition(int(font_ref.group(1)))
        elif rest.startswith('<<'):
            font_dict_text = self._find_balanced_dict(rest, 0)
        else:
            self._font_cmaps[page_obj_num] = cmaps
            return cmaps

        # Parse font name -> font object reference pairs.
        # Pattern: /FontName N 0 R
        two_byte_flags = {}
        for fm in re.finditer(r'/(\w+)\s+(\d+)\s+0\s+R', font_dict_text):
            font_name = '/' + fm.group(1)
            font_obj_num = int(fm.group(2))
            font_defn = self._get_object_definition(font_obj_num)
            if not font_defn:
                continue

            # Detect Identity-H encoding — Typst and some CID fonts use
            # two-byte glyph IDs where each character code is 2 bytes.
            # Without this, CMap application processes bytes one at a time,
            # producing garbled output like "N a t i o n a l" instead of
            # "National".
            is_two_byte = False
            if '/Identity-H' in font_defn or '/Identity-V' in font_defn:
                is_two_byte = True

            # Also detect via /Encoding reference that resolves to Identity-H.
            encoding_ref = re.search(r'/Encoding\s+(\d+)\s+0\s+R', font_defn)
            if encoding_ref:
                enc_defn = self._get_object_definition(int(encoding_ref.group(1)))
                if enc_defn and 'Identity' in enc_defn:
                    is_two_byte = True

            # Find /ToUnicode reference.
            tounicode = re.search(r'/ToUnicode\s+(\d+)\s+0\s+R', font_defn)
            if not tounicode:
                continue

            # Decode the ToUnicode CMap stream.
            cmap_data = self._get_stream_data(int(tounicode.group(1)))
            if not cmap_data:
                continue

            cmap_text = cmap_data.decode('latin-1')
            mapping = _parse_cmap(cmap_text)
            if mapping:
                cmaps[font_name] = mapping
                # Also detect two-byte from CMap source codes: if any source
                # code > 255, the CMap uses multi-byte addressing.
                if not is_two_byte and any(k > 255 for k in mapping):
                    is_two_byte = True
                two_byte_flags[font_name] = is_two_byte

        self._font_cmaps[page_obj_num] = cmaps
        self._font_two_byte[page_obj_num] = two_byte_flags
        return cmaps

    # -- Step 5: Parse content streams --

    def _extract_all_pages(self) -> list[TextChunk]:
        """
        Iterate over all pages, decode content streams, parse operators,
        and collect TextChunk objects.
        """
        all_chunks = []
        for page_idx, page_obj in enumerate(self.page_obj_nums, 1):
            content = self._get_page_content(page_obj)
            if not content:
                continue
            # Resolve font CMaps for this page so text extraction
            # can map glyph codes to proper Unicode characters.
            font_cmaps = self._resolve_font_cmaps(page_obj)
            font_two_byte = self._font_two_byte.get(page_obj, {})
            chunks = self._parse_content_stream(
                content, page_idx, font_cmaps, font_two_byte)
            all_chunks.extend(chunks)
        return all_chunks

    def _parse_content_stream(self, content: str,
                              page_num: int,
                              font_cmaps: dict[str, dict[int, str]] = None,
                              font_two_byte: dict[str, bool] = None) -> list[TextChunk]:
        """
        Tokenize a content stream and extract text chunks with their
        structure tags and positional information.

        PDF content streams are sequences of operands followed by
        operators. We track:
          - Marked content scope (BDC/EMC) to know which structure
            tag each text run belongs to.
          - Text state (Tf for font, Tm for position matrix, Td/TD
            for relative moves).
          - TJ/Tj operators for actual text extraction.

        The output is a list of TextChunks, one per marked-content
        region that contains text.

        Why not a full PDF interpreter: we only need text extraction
        and structural tagging, not rendering. We track just enough
        state to map text to positions and semantic roles.
        """
        chunks = []

        # -- State tracking --
        # Marked content stack: each entry is (tag, properties_dict).
        # BDC pushes, EMC pops. Text inherits the innermost tag.
        mc_stack = []
        # Current text state.
        current_font = ''
        current_font_size = 0.0
        current_x = 0.0
        current_y = 0.0
        # Are we inside a BT...ET text object?
        in_text = False
        # Accumulate text within a single marked-content region.
        current_text_parts = []
        # The tag/properties of the current marked-content region.
        current_mc_tag = ''
        current_mc_props = {}

        # Leading value for T* operator (set by TL operator).
        text_leading = 0.0
        # Text matrix components for position tracking.
        tm_a = 1.0  # horizontal scale
        tm_d = 1.0  # vertical scale (= font size when set via Tm)
        # Tf size set by the Tf operator (separate from Tm scale).
        # The actual rendered font size is tf_size * abs(tm_d).
        # Why track separately: NIEHS PDFs use Tf=1,Tm_d=12 (size in matrix),
        # while Typst PDFs use Tf=12.7,Tm_d=-1 (size in Tf, matrix just flips).
        # Without separating these, Typst PDFs report 1pt instead of 12.7pt.
        tf_size = 1.0

        # Tokenize the content stream.
        # We process it as a sequence of tokens separated by whitespace,
        # but we need special handling for:
        #   - String literals (...) with balanced parens and escapes
        #   - Hex strings <...>
        #   - Arrays [...]
        #   - Dictionaries << ... >> (inside BDC properties)
        #   - Comments % ...

        pos = 0
        tokens = []

        while pos < len(content):
            ch = content[pos]

            # Skip whitespace.
            if ch in ' \t\r\n\x00':
                pos += 1
                continue

            # Skip comments (% to end of line).
            if ch == '%':
                eol = content.find('\n', pos)
                if eol < 0:
                    break
                pos = eol + 1
                continue

            # String literal.
            if ch == '(':
                s, pos = _extract_parenthesised_string(content, pos)
                tokens.append(('string', s))
                continue

            # Hex string (but not a dictionary <<).
            if ch == '<' and pos + 1 < len(content) and content[pos + 1] != '<':
                s, pos = _extract_hex_string(content, pos)
                tokens.append(('hexstring', s))
                continue

            # Dictionary start <<.
            if ch == '<' and pos + 1 < len(content) and content[pos + 1] == '<':
                # Find matching >>. Handle nesting.
                depth = 0
                i = pos
                while i < len(content):
                    if content[i:i + 2] == '<<':
                        depth += 1
                        i += 2
                    elif content[i:i + 2] == '>>':
                        depth -= 1
                        i += 2
                        if depth == 0:
                            tokens.append(('dict', content[pos:i]))
                            pos = i
                            break
                    else:
                        i += 1
                else:
                    pos = len(content)
                continue

            # Array.
            if ch == '[':
                # Find matching ]. Need to handle nested () and <>.
                depth = 1
                i = pos + 1
                while i < len(content) and depth > 0:
                    c = content[i]
                    if c == '[':
                        depth += 1
                        i += 1
                    elif c == ']':
                        depth -= 1
                        i += 1
                    elif c == '(':
                        # Skip balanced parens.
                        _, i = _extract_parenthesised_string(content, i)
                    elif c == '<' and i + 1 < len(content) and content[i + 1] != '<':
                        _, i = _extract_hex_string(content, i)
                    else:
                        i += 1
                tokens.append(('array', content[pos:i]))
                pos = i
                continue

            # Name (starts with /).
            if ch == '/':
                i = pos + 1
                while i < len(content) and content[i] not in ' \t\r\n\x00/<>[](){}%':
                    i += 1
                tokens.append(('name', content[pos:i]))
                pos = i
                continue

            # Number (integer or real, possibly negative).
            if ch in '0123456789.-+':
                i = pos + 1 if ch != '.' else pos + 1
                while i < len(content) and content[i] in '0123456789.':
                    i += 1
                tok = content[pos:i]
                try:
                    if '.' in tok:
                        tokens.append(('number', float(tok)))
                    else:
                        tokens.append(('number', int(tok)))
                except ValueError:
                    tokens.append(('keyword', tok))
                pos = i
                continue

            # Keyword / operator (alphabetic).
            if ch.isalpha() or ch == "'":
                i = pos + 1
                while i < len(content) and (content[i].isalnum() or content[i] in '_*\''):
                    i += 1
                tokens.append(('keyword', content[pos:i]))
                pos = i
                continue

            # Unknown — skip.
            pos += 1

        # -- Process tokens into text chunks --
        # We walk the token list, executing operators that affect our
        # tracked state. Operands accumulate until an operator consumes them.

        operand_stack = []

        def _flush_text():
            """
            When a marked-content region ends (EMC) or changes, save
            the accumulated text as a TextChunk if non-empty.
            """
            nonlocal current_text_parts, current_mc_tag, current_mc_props
            text = ''.join(current_text_parts).strip()
            if text:
                chunk = TextChunk()
                chunk.page = page_num
                chunk.tag = current_mc_tag
                chunk.text = text
                chunk.font = current_font
                chunk.font_size = current_font_size
                chunk.x = current_x
                chunk.y = current_y
                chunk.properties = dict(current_mc_props)
                mcid = current_mc_props.get('MCID')
                if mcid is not None:
                    chunk.mcid = mcid
                chunk.chunk_type = self._classify_chunk(chunk, page_num)
                chunks.append(chunk)
            current_text_parts = []

        for tok_type, tok_val in tokens:
            if tok_type == 'keyword':
                op = tok_val

                # -- Marked content operators --
                if op == 'BDC':
                    # Begin marked content with properties.
                    # Operands: /Tag properties_dict_or_name
                    tag = ''
                    props = {}
                    for ot, ov in operand_stack:
                        if ot == 'name':
                            tag = ov.lstrip('/')
                        elif ot == 'dict':
                            props = self._parse_bdc_properties(ov)
                    # Flush any text accumulated under the previous tag.
                    _flush_text()
                    mc_stack.append((tag, props))
                    current_mc_tag = tag
                    current_mc_props = props
                    operand_stack.clear()

                elif op == 'BMC':
                    # Begin marked content (no properties).
                    tag = ''
                    for ot, ov in operand_stack:
                        if ot == 'name':
                            tag = ov.lstrip('/')
                    _flush_text()
                    mc_stack.append((tag, {}))
                    current_mc_tag = tag
                    current_mc_props = {}
                    operand_stack.clear()

                elif op == 'EMC':
                    # End marked content.
                    _flush_text()
                    if mc_stack:
                        mc_stack.pop()
                    if mc_stack:
                        current_mc_tag, current_mc_props = mc_stack[-1]
                    else:
                        current_mc_tag = ''
                        current_mc_props = {}
                    operand_stack.clear()

                # -- Text object operators --
                elif op == 'BT':
                    in_text = True
                    # Reset text matrix to identity.
                    current_x = 0.0
                    current_y = 0.0
                    tm_a = 1.0
                    tm_d = 1.0
                    operand_stack.clear()

                elif op == 'ET':
                    in_text = False
                    operand_stack.clear()

                # -- Font operator --
                elif op == 'Tf':
                    # Operands: /FontName size
                    # Store the Tf size separately — the actual rendered size
                    # is tf_size * abs(tm_d), computed when Tm is set or here
                    # as a fallback for PDFs that never issue Tm.
                    for ot, ov in operand_stack:
                        if ot == 'name':
                            current_font = ov
                        elif ot == 'number':
                            tf_size = abs(float(ov))
                            # Update font_size using current Tm scale.
                            # For NIEHS (Tf=1, Tm_d=12): 1*12 = 12pt ✓
                            # For Typst (Tf=12.7, Tm_d=-1): 12.7*1 = 12.7pt ✓
                            current_font_size = tf_size * abs(tm_d)
                    operand_stack.clear()

                # -- Text positioning operators --
                elif op == 'Tm':
                    # Set text matrix: a b c d e f Tm
                    nums = [ov for ot, ov in operand_stack if ot == 'number']
                    if len(nums) >= 6:
                        tm_a = nums[0]
                        tm_d = nums[3]
                        current_x = nums[4]
                        current_y = nums[5]
                        # Recompute font size as tf_size * abs(tm_d).
                        # This correctly handles both rendering models:
                        #   NIEHS: Tf=1, Tm_d=12 → 1*12 = 12pt
                        #   Typst: Tf=12.7, Tm_d=-1 → 12.7*1 = 12.7pt
                        if abs(tm_d) > 0.1:
                            current_font_size = tf_size * abs(tm_d)
                    operand_stack.clear()

                elif op == 'Td':
                    # Move text position: tx ty Td
                    nums = [ov for ot, ov in operand_stack if ot == 'number']
                    if len(nums) >= 2:
                        # Td moves relative to the start of the current
                        # line, scaled by the text matrix.
                        current_x += nums[0] * abs(tm_a) if abs(tm_a) > 0.01 else nums[0]
                        current_y += nums[1] * abs(tm_d) if abs(tm_d) > 0.01 else nums[1]
                    operand_stack.clear()

                elif op == 'TD':
                    # Like Td but also sets leading: tx ty TD
                    nums = [ov for ot, ov in operand_stack if ot == 'number']
                    if len(nums) >= 2:
                        current_x += nums[0] * abs(tm_a) if abs(tm_a) > 0.01 else nums[0]
                        current_y += nums[1] * abs(tm_d) if abs(tm_d) > 0.01 else nums[1]
                        text_leading = -nums[1]
                    operand_stack.clear()

                elif op == 'T*':
                    # Move to start of next line (uses leading from TL).
                    current_y -= text_leading
                    operand_stack.clear()

                elif op == 'TL':
                    # Set text leading: leading TL
                    nums = [ov for ot, ov in operand_stack if ot == 'number']
                    if nums:
                        text_leading = nums[0]
                    operand_stack.clear()

                # -- Text showing operators --
                elif op == 'TJ':
                    # Show text with kerning: array TJ
                    # Look up the active font's CMap and two-byte flag.
                    active_cmap = (font_cmaps or {}).get(current_font, None)
                    is_two_byte = (font_two_byte or {}).get(current_font, False)
                    for ot, ov in operand_stack:
                        if ot == 'array':
                            items = self._parse_tj_array(ov)
                            text = _text_from_tj_array(
                                items, active_cmap, two_byte=is_two_byte)
                            current_text_parts.append(text)
                    operand_stack.clear()

                elif op == 'Tj':
                    # Show simple string: string Tj
                    active_cmap = (font_cmaps or {}).get(current_font, None)
                    is_two_byte = (font_two_byte or {}).get(current_font, False)
                    for ot, ov in operand_stack:
                        if ot == 'string':
                            parsed = _parse_string_literal(ov)
                            if active_cmap:
                                parsed = _apply_cmap(
                                    parsed, active_cmap, two_byte=is_two_byte)
                            current_text_parts.append(parsed)
                        elif ot == 'hexstring':
                            text = ov
                            if active_cmap:
                                text = _apply_cmap(
                                    text, active_cmap, two_byte=is_two_byte)
                            current_text_parts.append(text)
                    operand_stack.clear()

                elif op == "'":
                    # Move to next line and show string: string '
                    current_y -= text_leading
                    active_cmap = (font_cmaps or {}).get(current_font, None)
                    is_two_byte = (font_two_byte or {}).get(current_font, False)
                    for ot, ov in operand_stack:
                        if ot == 'string':
                            parsed = _parse_string_literal(ov)
                            if active_cmap:
                                parsed = _apply_cmap(
                                    parsed, active_cmap, two_byte=is_two_byte)
                            current_text_parts.append(parsed)
                    operand_stack.clear()

                elif op == '"':
                    # Set spacing, move to next line, show string:
                    # aw ac string "
                    current_y -= text_leading
                    active_cmap = (font_cmaps or {}).get(current_font, None)
                    is_two_byte = (font_two_byte or {}).get(current_font, False)
                    for ot, ov in operand_stack:
                        if ot == 'string':
                            parsed = _parse_string_literal(ov)
                            if active_cmap:
                                parsed = _apply_cmap(
                                    parsed, active_cmap, two_byte=is_two_byte)
                            current_text_parts.append(parsed)
                    operand_stack.clear()

                # -- Graphics state (tracked minimally) --
                elif op in ('q', 'Q', 'cm', 'gs', 'Do', 'sh',
                            'W', 'W*', 'n', 'f', 'f*', 'F', 'B', 'B*',
                            'b', 'b*', 'S', 's',
                            'm', 'l', 'c', 'v', 'y', 'h', 're',
                            'k', 'K', 'g', 'G', 'rg', 'RG',
                            'cs', 'CS', 'sc', 'SC', 'scn', 'SCN',
                            'd', 'i', 'j', 'J', 'M', 'w',
                            'ri', 'BX', 'EX',
                            'Tc', 'Tw', 'Tz', 'Tr', 'Ts',
                            'DP', 'MP'):
                    # These operators don't produce text. Clear operands.
                    operand_stack.clear()

                else:
                    # Unknown operator — clear operands to avoid buildup.
                    operand_stack.clear()

            else:
                # Non-keyword token: push as operand.
                operand_stack.append((tok_type, tok_val))

        # Flush any remaining text.
        _flush_text()

        return chunks

    def _parse_bdc_properties(self, dict_str: str) -> dict:
        """
        Parse the properties dictionary from a BDC operator.

        Example input: '<</Lang (en-US)/MCID 1 >>'
        Example output: {'Lang': 'en-US', 'MCID': 1}

        Also handles artifact properties:
            '<</Attached [/Top ]/BBox [...]/Subtype /Header /Type /Pagination >>'

        Why a custom parser instead of reusing the tokenizer: BDC
        property dicts are small and have a predictable structure.
        A targeted regex approach is faster and simpler.
        """
        props = {}
        # Strip outer << >>
        inner = dict_str.strip()
        if inner.startswith('<<'):
            inner = inner[2:]
        if inner.endswith('>>'):
            inner = inner[:-2]

        # Extract MCID (always an integer).
        mcid = re.search(r'/MCID\s+(\d+)', inner)
        if mcid:
            props['MCID'] = int(mcid.group(1))

        # Extract Lang.
        lang = re.search(r'/Lang\s*\(([^)]*)\)', inner)
        if lang:
            props['Lang'] = lang.group(1).strip()

        # Extract Subtype (important for Artifact classification).
        subtype = re.search(r'/Subtype\s*/(\w+)', inner)
        if subtype:
            props['Subtype'] = subtype.group(1)

        # Extract Type.
        type_m = re.search(r'/Type\s*/(\w+)', inner)
        if type_m:
            props['Type'] = type_m.group(1)

        # Extract Attached (for artifacts: [/Top], [/Bottom]).
        attached = re.search(r'/Attached\s*\[([^\]]*)\]', inner)
        if attached:
            props['Attached'] = attached.group(1).strip()

        return props

    def _parse_tj_array(self, array_str: str) -> list:
        """
        Parse a TJ array string like '[(Hello) -20 (World)]' into
        a list of strings and numbers.

        Returns: list of str and float/int values.

        Why not reuse the main tokenizer: TJ arrays are self-contained
        and always appear as a single token. Parsing them inline is
        faster than re-tokenizing.
        """
        items = []
        # Strip outer [ ]
        inner = array_str.strip()
        if inner.startswith('['):
            inner = inner[1:]
        if inner.endswith(']'):
            inner = inner[:-1]

        pos = 0
        while pos < len(inner):
            ch = inner[pos]
            if ch in ' \t\r\n':
                pos += 1
                continue
            if ch == '(':
                s, pos = _extract_parenthesised_string(inner, pos)
                items.append(s)
                continue
            if ch == '<' and pos + 1 < len(inner) and inner[pos + 1] != '<':
                s, pos = _extract_hex_string(inner, pos)
                items.append(s)
                continue
            if ch in '0123456789.-+':
                j = pos + 1
                while j < len(inner) and inner[j] in '0123456789.eE+-':
                    j += 1
                try:
                    num = float(inner[pos:j])
                    items.append(num)
                except ValueError:
                    pass
                pos = j
                continue
            # Skip unknown characters.
            pos += 1

        return items

    # -- Step 6: Classify chunks --

    def _classify_chunk(self, chunk: TextChunk, page_num: int) -> str:
        """
        Assign a semantic chunk type based on the structure tag,
        artifact properties, and positional/font heuristics.

        Classification priority:
          1. Artifact with Subtype -> 'header' or 'footer'
          2. Artifact without Subtype -> 'artifact'
          3. H1, H2, H3 -> 'heading'
          4. P -> 'paragraph'
          5. Figure -> 'figure'
          6. Caption -> 'caption'
          7. Table, TD, TH, TR -> 'table'
          8. TOCI -> 'toc_entry'
          9. Reference -> 'reference'
          10. LI, LBody, Lbl, L -> 'list_item'
          11. First page (page 1) with large font -> 'cover_element'
          12. Fallback -> 'unknown'

        Why this order: Artifact detection must come first because
        artifacts can have tag names like /P but are really page
        decorations (running headers). Structure tags are authoritative
        for the rest. The cover page heuristic catches the title which
        uses a non-standard tag or large font.
        """
        tag = chunk.tag

        # Artifacts: running headers, footers, page numbers.
        if tag == 'Artifact':
            subtype = chunk.properties.get('Subtype', '')
            if subtype == 'Header':
                return 'header'
            elif subtype == 'Footer':
                return 'footer'
            else:
                return 'artifact'

        # Headings.
        if tag in ('H1', 'H2', 'H3', 'H4', 'H5', 'H6'):
            return 'heading'

        # Paragraph — but on the cover page with large font, it's a title.
        if tag == 'P':
            if page_num == 1 and chunk.font_size >= 16:
                return 'cover_element'
            return 'paragraph'

        # Figure.
        if tag == 'Figure':
            return 'figure'

        # Caption.
        if tag == 'Caption':
            return 'caption'

        # Table elements.
        if tag in ('Table', 'TD', 'TH', 'TR', 'THead', 'TBody'):
            return 'table'

        # Table of contents.
        if tag == 'TOCI':
            return 'toc_entry'

        # Reference / citation / hyperlink.
        if tag in ('Reference', 'Link'):
            return 'reference'

        # List elements.
        if tag in ('L', 'LI', 'LBody', 'Lbl'):
            return 'list_item'

        # Span (inline, treat as paragraph).
        if tag == 'Span':
            return 'paragraph'

        # Cover page heuristic: page 1 with no recognized tag.
        if page_num == 1:
            return 'cover_element'

        # PlacedPDF sub-content markers (MC0, MC1, etc.).
        if tag.startswith('MC'):
            return 'artifact'

        return 'unknown'


# ---------------------------------------------------------------------------
# Post-processing: table detection heuristic
# ---------------------------------------------------------------------------
# See table_detection_heuristic.md for the full rationale and design.
# This PDF (InDesign export) tags all table content as /P (paragraph).
# We detect tables by caption pattern + font size drop, and reclassify
# chunks as table_caption, table_cell, or table_footnote.

@dataclass
class TableDetectionConfig:
    """
    Configuration for the table detection heuristic.

    Controls how the post-processing pass identifies and classifies table
    regions in the chunk stream. The defaults work for NIEHS/NTP-style
    reports (InDesign PDFs where all table content is tagged as /P).

    Attributes:
        caption_pattern:    Regex matching the start of a table caption.
                            Default matches "Table N." and "Table X-N.".
        font_ceiling:       Font size boundary (pt). Chunks below this
                            inside a table region are classified as cells.
                            Body text is 12pt; table content is 1–10.98pt.
        body_text_min_len:  Minimum character length for a body-text
                            paragraph to terminate a table region. Short
                            chunks at body-text size could be isolated
                            labels between table sections.
        footnote_font_min:  Lower bound (pt) for footnote font size.
        footnote_font_max:  Upper bound (pt) for footnote font size.
    """
    caption_pattern: str = r'^Table\s+[A-Z]?-?\d+\.'
    font_ceiling: float = 11.5
    body_text_min_len: int = 30
    footnote_font_min: float = 8.5
    footnote_font_max: float = 9.5


# Default config instance and pre-compiled regex for backward compat.
_DEFAULT_TABLE_CONFIG = TableDetectionConfig()
RE_TABLE_CAPTION = re.compile(_DEFAULT_TABLE_CONFIG.caption_pattern)


def _detect_tables(chunks: list[TextChunk],
                   config: TableDetectionConfig = None) -> list[TextChunk]:
    """
    Post-processing pass that reclassifies paragraph chunks inside
    table regions as table_caption, table_cell, or table_footnote.

    Walks the chunk list sequentially, toggling an in_table flag:
      - ON when a caption is detected (entry signal)
      - OFF when a terminator is hit (heading, body-text paragraph,
        or non-table content after a page break)

    Chunks classified as header/footer are transparent — they are
    skipped and never trigger termination.

    The existing /TH-tagged chunk (page 67) is also reclassified to
    table_cell for consistency.

    Args:
        chunks: Flat list of TextChunk objects (mutated in place).
        config: Optional TableDetectionConfig with thresholds. Uses
                defaults if None.

    Returns:
        Same list, with chunk_type updated where appropriate.
    """
    if config is None:
        config = _DEFAULT_TABLE_CONFIG

    # Compile the caption pattern (may differ from default if caller
    # passed a custom config).
    caption_re = re.compile(config.caption_pattern)

    in_table = False
    # Track whether we've seen non-footnote cells in the current table,
    # so we can distinguish trailing footnotes from leading cells.
    saw_non_footnote_cell = False

    for i, chunk in enumerate(chunks):
        # Skip headers and footers — they are transparent to table state.
        if chunk.chunk_type in ('header', 'footer'):
            continue

        if not in_table:
            # -- Check for entry signal --
            if (chunk.chunk_type == 'paragraph'
                    and chunk.font_size < config.font_ceiling
                    and caption_re.match(chunk.text)):
                chunk.chunk_type = 'table_caption'
                in_table = True
                saw_non_footnote_cell = False
            # Also catch the lone /TH-tagged cell (page 67) as a
            # table entry point.
            elif chunk.chunk_type == 'table':
                chunk.chunk_type = 'table_cell'
                in_table = True
                saw_non_footnote_cell = True

        else:
            # -- Inside a table: classify or terminate --

            # Terminator 1: heading.
            if chunk.chunk_type == 'heading':
                in_table = False
                continue

            # Terminator 2: body-text paragraph (>= font_ceiling, long).
            if (chunk.chunk_type == 'paragraph'
                    and chunk.font_size >= config.font_ceiling
                    and len(chunk.text) > config.body_text_min_len):
                in_table = False
                continue

            # Terminator 3: non-paragraph, non-table chunk types that
            # signal a structural break (e.g., a new table caption,
            # a reference, a list item at body-text size).
            # But references and list items at small font are still
            # table content (e.g., inline citations in cells).
            if chunk.chunk_type not in ('paragraph', 'table', 'reference',
                                         'list_item', 'cover_element'):
                # Check if it's a new table caption — if so, close the
                # current table and start a new one.
                if (chunk.chunk_type == 'paragraph'
                        and caption_re.match(chunk.text)):
                    chunk.chunk_type = 'table_caption'
                    saw_non_footnote_cell = False
                    continue
                # Other structural types (toc_entry, etc.) terminate.
                in_table = False
                continue

            # Still inside the table — classify the chunk.
            if chunk.chunk_type in ('paragraph', 'table'):
                fs = chunk.font_size

                # Is this a new table caption nested inside the run?
                # (Happens when tables follow back-to-back without a
                # heading separator — not observed in this PDF, but
                # handled for robustness.)
                if caption_re.match(chunk.text):
                    chunk.chunk_type = 'table_caption'
                    saw_non_footnote_cell = False
                    continue

                # Footnote detection: font size in the footnote range,
                # starts with lowercase, and we've already seen data cells.
                if (saw_non_footnote_cell
                        and config.footnote_font_min <= fs <= config.footnote_font_max
                        and len(chunk.text) > 10
                        and chunk.text[0].islower()):
                    chunk.chunk_type = 'table_footnote'
                else:
                    chunk.chunk_type = 'table_cell'
                    if fs > 2:  # Ignore 1pt spacer elements
                        saw_non_footnote_cell = True

            # References inside tables (e.g., inline citations) stay
            # as references — they're already correctly classified.

    return chunks


# ---------------------------------------------------------------------------
# Public API / entry point
# ---------------------------------------------------------------------------

def parse_pdf(file_path: str,
              detect_tables: bool = True,
              table_config: TableDetectionConfig = None) -> list[dict]:
    """
    Parse a PDF file and return a list of semantically classified text chunks.

    Each chunk is a dict with keys: page, type, tag, text, and optionally
    font, font_size, position, mcid, properties.

    This is the main public function. It reads the file, runs the parser,
    applies the table detection heuristic, and returns structured data
    ready for JSON serialization.

    Args:
        file_path:     Path to the PDF file.
        detect_tables: Whether to run the table detection heuristic.
                       Set to False for plain-text extraction where
                       table structure doesn't matter.
        table_config:  Optional TableDetectionConfig for custom thresholds.

    Returns:
        List of chunk dictionaries.
    """
    raw = _read_file(file_path)
    parser = PdfParser(raw)
    chunks = parser.parse()
    if detect_tables:
        chunks = _detect_tables(chunks, config=table_config)
    return [c.to_dict() for c in chunks]


def parse_pdf_bytes(data: bytes,
                    detect_tables: bool = True,
                    table_config: TableDetectionConfig = None) -> list[dict]:
    """
    Parse a PDF from raw bytes (e.g., HTTP response body or in-memory buffer).

    Identical to parse_pdf() but accepts bytes instead of a file path.
    Used by fulltext.py to parse PDFs fetched from the web without
    writing them to disk first.

    Args:
        data:          Raw PDF file bytes.
        detect_tables: Whether to run the table detection heuristic.
        table_config:  Optional TableDetectionConfig for custom thresholds.

    Returns:
        List of chunk dictionaries.
    """
    parser = PdfParser(data)
    chunks = parser.parse()
    if detect_tables:
        chunks = _detect_tables(chunks, config=table_config)
    return [c.to_dict() for c in chunks]


def chunks_to_text(chunks: list[dict]) -> str:
    """
    Join parsed chunks into plain text, separated by page.

    Pages are separated by double newlines. Within a page, chunks are
    joined with single newlines. This produces readable plain text
    suitable for full-text search and LLM context.

    Args:
        chunks: List of chunk dicts as returned by parse_pdf() or
                parse_pdf_bytes().

    Returns:
        Plain text string with page breaks as double newlines.
    """
    # Group chunks by page number, preserving order within each page.
    pages: dict[int, list[str]] = {}
    for c in chunks:
        pages.setdefault(c['page'], []).append(c['text'])
    # Join within pages (single newline) and between pages (double newline).
    return '\n\n'.join(
        '\n'.join(texts)
        for _, texts in sorted(pages.items())
    )


def chunks_to_words(chunks: list[dict],
                    page_height: float = 792.0) -> list[dict]:
    """
    Split text chunks into word-level dicts with estimated x-positions.

    Produces dicts compatible with pdfplumber's word format:
        {"text": str, "top": float, "x0": float, "x1": float, "page": int}

    The "top" field uses pdfplumber convention: y=0 at the top of the page,
    increasing downward. This is the OPPOSITE of PDF-native coordinates
    (y=0 at bottom, increasing upward). We flip by subtracting from
    page_height. This ensures compatibility with diff_tables.py and
    extract_ref_tables.py which assume top-down y ordering.

    Word x-positions are estimated from the chunk's position and font size.
    The approximation (avg_char_width ≈ 0.5 * font_size) is good enough
    for the 5pt histogram quantization used in diff_tables.py's column
    detection.

    Args:
        chunks:      List of chunk dicts as returned by parse_pdf().
        page_height: Page height in points for y-flip. Default 792pt
                     (US Letter). NIEHS PDFs and Typst output both use
                     US Letter.

    Returns:
        List of word-level dicts sorted by (page, top, x0).
    """
    words = []
    for c in chunks:
        text = c.get('text', '')
        if not text.strip():
            continue

        pos = c.get('position', {})
        x = pos.get('x', 0.0)
        # Flip y from PDF-native (bottom-up) to pdfplumber-style (top-down).
        y_pdf = pos.get('y', 0.0)
        y_top = page_height - y_pdf
        font_size = c.get('font_size', 10.0)
        page = c.get('page', 1)

        # Estimate average character width as half the font size.
        # This is a reasonable approximation for proportional fonts:
        # a 10pt font has characters roughly 5pt wide on average.
        avg_char_width = 0.5 * font_size if font_size > 0 else 5.0

        # Split on whitespace and compute per-word positions.
        char_offset = 0
        for word in text.split():
            # Find where this word starts in the original text
            # (accounting for leading whitespace).
            word_start = text.find(word, char_offset)
            if word_start < 0:
                word_start = char_offset

            word_x0 = x + word_start * avg_char_width
            word_x1 = word_x0 + len(word) * avg_char_width

            words.append({
                'text': word,
                'top': y_top,
                'x0': word_x0,
                'x1': word_x1,
                'page': page,
            })

            char_offset = word_start + len(word)

    # Sort by page, then vertical position (top), then horizontal (x0).
    words.sort(key=lambda w: (w['page'], w['top'], w['x0']))
    return words


def extract_rules(path_or_data, page_height: float = 792.0) -> list[dict]:
    """
    Extract horizontal rules (thin lines/rectangles) from a PDF.

    Scans content streams for `re` (rectangle fill) and `m`/`l`/`S`/`f`
    (path ops) to detect thin horizontal lines. These are table delimiters
    in NIEHS PDFs (filled rects) and Typst PDFs (line strokes).

    The y-coordinate is flipped to pdfplumber convention (0 = page top,
    increasing downward) for compatibility with diff_tables.py.

    Args:
        path_or_data: File path (str) or raw bytes.
        page_height:  Page height in points for y-flip. Default 792pt
                      (US Letter).

    Returns:
        List of rule dicts sorted by (page, y):
            {page: int, y: float, x0: float, x1: float, width: float, height: float}
        Only includes lines where width > 100pt and height < 2pt.
    """
    if isinstance(path_or_data, (str,)):
        raw = _read_file(path_or_data)
    elif isinstance(path_or_data, bytes):
        raw = path_or_data
    else:
        raw = _read_file(str(path_or_data))

    parser = PdfParser(raw)
    parser._index_direct_objects()
    parser._decode_object_streams()
    parser._build_page_list()

    rules = []
    for page_idx, page_obj in enumerate(parser.page_obj_nums, 1):
        content = parser._get_page_content(page_obj)
        if not content:
            continue
        page_rules = _extract_rules_from_content(content, page_idx)
        # Flip y from PDF-native (bottom-up) to pdfplumber-style (top-down)
        # so that diff_tables.py's y-range comparisons work correctly.
        for r in page_rules:
            r['y'] = page_height - r['y']
        rules.extend(page_rules)

    rules.sort(key=lambda r: (r['page'], r['y']))
    return rules


def _extract_rules_from_content(content: str, page_num: int) -> list[dict]:
    """
    Scan a page's content stream for thin horizontal elements.

    Detects two types of elements:
    1. Filled rectangles via `re` operator: x y w h re
       These appear in NIEHS PDFs as thin filled rects (h < 2pt).
       A single visual rule may be composed of many small segments
       (e.g. 32pt, 42pt each) — we collect ALL thin rects without
       a width filter and let the caller cluster by y-position to
       determine the combined span.
    2. Horizontal lines via path operators: x1 y1 m x2 y2 l S
       These appear in Typst PDFs as stroked line segments.

    No width filtering is applied here — the caller (extract_rules →
    _extract_horizontal_rules_for_page) clusters segments by y-position
    and checks that the combined x-span exceeds MIN_RULE_WIDTH.

    Returns all thin horizontal elements (height < 2pt) regardless of width.
    """
    rules = []

    # Strategy: tokenize minimally — just look for rectangle and line patterns.
    # This is much faster than full content stream parsing since we only
    # need geometric primitives, not text.

    # Pattern 1: Rectangles — "x y w h re" followed by fill/stroke operator.
    # Collect ALL thin rects (h < 2pt), even narrow segments.
    for m in re.finditer(
            r'([\d.+-]+)\s+([\d.+-]+)\s+([\d.+-]+)\s+([\d.+-]+)\s+re',
            content):
        try:
            x = float(m.group(1))
            y = float(m.group(2))
            w = float(m.group(3))
            h = float(m.group(4))
        except ValueError:
            continue
        # Keep thin horizontal rectangles — no width filter, since NIEHS
        # renders single visual rules as many ~32-52pt segments.
        if abs(h) < 2 and abs(w) > 0.1:
            rules.append({
                'page': page_num,
                'y': y,
                'x0': x,
                'x1': x + abs(w),
                'width': abs(w),
                'height': abs(h),
            })

    # Pattern 2: Horizontal line segments — "x1 y1 m x2 y2 l S"
    for m in re.finditer(
            r'([\d.+-]+)\s+([\d.+-]+)\s+m\s+'
            r'([\d.+-]+)\s+([\d.+-]+)\s+l',
            content):
        try:
            x1 = float(m.group(1))
            y1 = float(m.group(2))
            x2 = float(m.group(3))
            y2 = float(m.group(4))
        except ValueError:
            continue
        # Horizontal if y-difference < 2pt.
        w = abs(x2 - x1)
        h = abs(y2 - y1)
        if h < 2 and w > 0.1:
            rules.append({
                'page': page_num,
                'y': min(y1, y2),
                'x0': min(x1, x2),
                'x1': max(x1, x2),
                'width': w,
                'height': h,
            })

    return rules


def main():
    """
    CLI entry point.

    Usage:
        python3 parse_pdf.py <pdf_file> [--output <json_file>]

    If --output is given, writes JSON to that file.
    Otherwise, prints a human-readable summary to stdout and writes
    full JSON to parsed_output.json.
    """
    if len(sys.argv) < 2:
        print("Usage: python3 parse_pdf.py <pdf_file> [--output <json_file>]",
              file=sys.stderr)
        sys.exit(1)

    pdf_path = sys.argv[1]
    output_path = 'parsed_output.json'
    if '--output' in sys.argv:
        idx = sys.argv.index('--output')
        if idx + 1 < len(sys.argv):
            output_path = sys.argv[idx + 1]

    print(f"Parsing {pdf_path}...")
    chunks = parse_pdf(pdf_path)

    # Write full JSON output.
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(chunks, f, indent=2, ensure_ascii=False)
    print(f"Wrote {len(chunks)} chunks to {output_path}")

    # Print summary.
    print(f"\n{'=' * 60}")
    print(f"DOCUMENT SUMMARY")
    print(f"{'=' * 60}")

    # Count by type.
    type_counts = {}
    for c in chunks:
        t = c['type']
        type_counts[t] = type_counts.get(t, 0) + 1
    print(f"\nChunk types:")
    for t, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {t:20s}: {count}")

    # Count by page.
    pages = set(c['page'] for c in chunks)
    print(f"\nPages with content: {len(pages)}")
    print(f"Total chunks: {len(chunks)}")

    # Show first few chunks of each type.
    print(f"\n{'=' * 60}")
    print(f"SAMPLE CHUNKS BY TYPE")
    print(f"{'=' * 60}")
    seen_types = set()
    for c in chunks:
        t = c['type']
        if t not in seen_types:
            seen_types.add(t)
            text_preview = c['text'][:120].replace('\n', ' ')
            print(f"\n[{t}] page {c['page']}, tag={c['tag']}")
            if c.get('font_size'):
                print(f"  font_size={c['font_size']}, font={c.get('font', '?')}")
            print(f"  \"{text_preview}\"")


if __name__ == '__main__':
    main()

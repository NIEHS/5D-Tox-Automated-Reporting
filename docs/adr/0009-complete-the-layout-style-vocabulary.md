# 0009 — Complete the layout-style vocabulary (roadmap)

- **Status:** Proposed (2026-07-22).
- **Deciders:** Dan Svoboda
- **Related:** [ADR-0006](0006-unify-html-latex-renderers.md) (the single tree
  walk + shared per-node styling the three surfaces resolve identically; this
  ADR extends the *vocabulary* that walk consumes); the **docx styling
  bootstrap** and **docx governance** project memories (the `.dotx` → styles.yaml
  extractor and the "rlm-bmdx owns structure + styling" model this vocabulary
  serves). Follows the title-page role-styling work that shipped the
  `title_page` sub-layer and the `basedOn`-chain resolver.

## Context

The shared styling vocabulary (`layout_style.LAYOUT_KEY_SCHEMA`, 14 per-node
keys + `DOCUMENT_KEY_SCHEMA`, 11 document keys) is the one coupling point that
lets a single `styles` config drive all three render surfaces (HTML, LaTeX,
docx). A config authored in — or bootstrap-extracted from — a Word template
flows through `resolve_layout_style` into each surface's translator
(`html_generator._layout_to_css_props`, `latex_generator._layout_to_latex`,
`docx_generator._layout_to_docx`).

The reverse-engineered NTP `.dotx` templates exercise **far more OOXML styling
than the vocabulary can express**. Measured across all paragraph styles in
`assets/templates/NIEHS-report-style-bordered.dotx`:

| OOXML property | styles using it | vocabulary key today |
|---|---|---|
| `w:spacing` (before/after) | 132 | `space_before`/`space_after` ✅ |
| `w:sz` (size) | 82 | `font_size` ✅ |
| `w:b` (bold) | 76 | `weight` ✅ |
| `w:rFonts` (font) | 43 | `font` ✅ |
| `w:outlineLvl` | 38 | — (structural, not styling) |
| `w:jc` (align) | 36 | `align` ✅ |
| `w:ind` (indent) | 31 | only `first_line_indent` ⚠️ |
| `w:numPr` (numbering) | 27 | — (bucket 3, deferred) |
| `w:tabs` (tab stops) | 24 | — (bucket 3, deferred) |
| `w:i` (italic) | 19 | `style` ✅ |
| `w:keepNext` | 11 | — (`keep_together` is keepLines, not keepNext) |
| `w:pageBreakBefore` | 8 | `break_before` ✅ |
| `w:color` | 5 | `color` ✅ |
| `w:kern` / rPr `w:spacing` | 3 / 1 | — |
| `w:contextualSpacing` | 2 | — |
| `w:caps` (all-caps) | 1 (the Title) | — |
| `w:shd` (shading) | 1 | — |

The extractor already **logs** the properties it drops to stderr, so the gap is
visible rather than silent — but the styling is lost. The title-page work needed
`caps` (the NTP `Title` is all-caps) and hit the indent/kerning gap; that made
the missing keys concrete rather than hypothetical.

Two structural findings from that work must be recorded so they are not
rediscovered:

1. **python-docx does NOT resolve `w:basedOn`.** A style that inherits its font
   from a parent (e.g. `1-03_Report_Title` → `Base_Heading` for Arial) returns
   `font=None` when read directly. Any new style-family extraction MUST walk the
   `style.base_style` chain (base-first, child-overrides) — see
   `docx_style_extract._resolved_style_props`, the reusable helper added for the
   title page. Retrofitting the heading extraction onto it is a cheap follow-up.
2. **The title-page look is structural as much as typographic.** The reference's
   tight title spacing came from emitting the whole title as ONE paragraph with
   soft line breaks (not one paragraph per line), independent of any
   line-spacing value. Vocabulary completion does not replace the need to get
   the emit *structure* right per node.

## Decision

Extend the vocabulary incrementally, prioritized by measured `.dotx` usage and
by what a title-page / body style actually needs. **Each new key is a
four-part contract** and is not "done" until all four are in place:

1. a schema entry in `layout_style.LAYOUT_KEY_SCHEMA` (with its value-kind);
2. an emit in ALL THREE translators (`_layout_to_css_props`,
   `_layout_to_latex`, `_layout_to_docx`) — a key one surface silently ignores
   is a drift bug;
3. a read in `docx_style_extract._extract_style_props` (so round-trip works);
4. a test in `test_layout_translators.py` + `test_docx_style_extract.py`.

This preserves ADR-0006's invariant: the vocabulary is the single coupling
point, and no surface may quietly diverge on what a key means.

### Phase A — title-page / display typography (highest value)

- **`text_transform`** — `enum {none, uppercase, lowercase, capitalize}`.
  docx `w:caps`/`w:smallCaps` (rPr); CSS `text-transform`; LaTeX `\MakeUppercase`
  (or `\textsc`). Needed by the NTP `Title` (all-caps).
- **`letter_spacing`** — `length`. docx rPr `w:spacing w:val` (twips) and/or
  `w:kern`; CSS `letter-spacing`; LaTeX `\textls`/`microtype` or `\addfontfeatures`.
  Note the extractor bug to avoid: character `w:spacing` (rPr) must NOT be read
  as paragraph `space_before` (pPr) — they are distinct elements.

### Phase B — body flow & indentation

- **`indent_left`, `indent_right`, `hanging_indent`** — `length`. docx `w:ind`
  (`w:left`/`w:right`/`w:hanging`); CSS `margin-left`/`margin-right`/text-indent;
  LaTeX list/`\hangindent`. Today only `first_line_indent` exists.
- **`line_spacing_exact`** — `length` (an absolute point value, e.g. `"12pt"`).
  Word has TWO line-spacing modes and the vocabulary models only one: today's
  `line_height` is a UNITLESS MULTIPLIER (docx `line_spacing = 1.2`, rule
  MULTIPLE; CSS `line-height: 1.2`; LaTeX `\linespread{1.2}`). The reference
  title page uses the OTHER mode — Word "Exactly", an absolute length that
  measured as **12pt** when set to match the reference — which no key can
  currently express. Contract: docx `pf.line_spacing = Pt(n)` (yields rule
  `EXACTLY`); CSS `line-height: 12pt` (an absolute length is valid); LaTeX
  `\baselineskip`/`\setlength`. Extractor: the currently-SKIPPED EMU branch in
  `_extract_style_props` (the `isinstance(pf.line_spacing, float)` guard drops
  exact spacing on purpose today) reads it once the key exists. `line_height`
  (multiple) and `line_spacing_exact` (absolute) are mutually exclusive on a
  given style — Word stores one `w:spacing w:lineRule` per paragraph; the
  translators must not emit both.
- **`contextual_spacing`** — `bool`. docx `w:contextualSpacing`; CSS adjacent-
  sibling margin collapse; LaTeX paragraph-skip handling.
- **Wire `break_after`** — the schema key EXISTS but the extractor never emits it
  and the translators may not honor it. Close the loop (docx already has
  `break_before` → `page_break_before`; add the symmetric after-break).
- **`keep_next`** — `bool`. docx `w:keepNext` (keep with following paragraph —
  distinct from today's `keep_together` = `w:keepLines`/keep_together). Used by
  38 NTP styles; important for headings not orphaning from their body.

### Phase C — decoration

- **`underline`** — `enum {none, single, ...}` or `bool`. docx rPr `w:u`; CSS
  `text-decoration`; LaTeX `\underline`/`ulem`.
- **`shading` / `background`** — `color`. docx pPr `w:shd w:fill`; CSS
  `background-color`; LaTeX `\colorbox`/`tcolorbox`. (The docx cover green band
  already uses `w:shd` directly — this generalizes it.)
- **`keep_lines`** — reconcile naming: today's `keep_together` maps to docx
  `keep_together` (keepLines). Keep as-is or rename for clarity alongside
  `keep_next`.

### Phase D — component geometry (EXPLICITLY DEFERRED — bucket 3)

Tab stops (`w:tabs`, ToC dot-leaders) and list numbering (`w:numPr`,
`w:ilvl`/`w:numId`) stay **per-surface** in each component renderer. This is the
documented "stop incremental-forever" line from the docx-styling-bootstrap
design: table column widths, ToC leaders, and list numbering are NOT
canonicalized into the shared vocabulary — they are component geometry, not
per-block typography. The extractor already logs these as skipped.

## Consequences

- The `.dotx` → `styles.yaml` round-trip captures progressively more of what a
  Word-authored template specifies, tightening the "author the look in Word,
  drive all surfaces" loop (docx governance model).
- Each phase is independently shippable and testable; no phase blocks another.
- The four-part contract keeps the three surfaces honest — the risk is a key
  added to the schema + one surface but not the others, which the
  `test_layout_translators.py` parity tests must guard against.
- Deferring bucket 3 keeps the vocabulary bounded; component geometry that truly
  needs per-surface control stays where it renders best.

## Non-goals

- Pixel/point-for-point fidelity with Word — the shared vocabulary is a
  semantic contract, not a layout engine (ADR-0006 stance).
- Implementing any of these keys in this ADR — this is the roadmap; each phase
  lands as its own change.
- Extracting the 38 non-title-page NTP `1-NN` styles (foreword/abstract/authors/
  peer-review) — those belong to separate front-matter nodes and are a distinct
  follow-up once those nodes gain role-addressable styling.

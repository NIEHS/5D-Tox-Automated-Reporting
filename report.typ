// =====================================================================
// report.typ — NIEHS Report 10 styled template for 5dToxReport
//
// Compiles to PDF/UA-1 (ISO 14289-1) with full StructTreeRoot, tagged
// headings (H1-H6), paragraphs (P), tables (Table/TR/TH/TD), lists
// (L/LI), links (Link), and artifacts for decorative elements.
//
// Data flows in via sys.inputs.data as a JSON string.  The Python
// export function (report_pdf.py) serializes the report state into
// this JSON and invokes typst.compile() with pdf_standards=["ua-1"].
//
// The template reproduces the complete structure of the NIEHS Report 10
// PDF (NBK589955), page for page:
//
//   Front matter (roman numerals):
//     - Inner title page (no header/footer)
//     - Foreword
//     - Table of Contents (auto-generated)
//     - Tables list (auto-generated)
//     - About This Report (authors, contributors)
//     - Peer Review
//     - Publication Details + Acknowledgments
//     - Abstract (Background/Methods/Results/Summary labeled sections)
//
//   Body (arabic numerals, restarted at 1):
//     - Background (H1)
//     - Materials and Methods (H1) with H2/H3 subsections
//     - Results (H1):
//         * Apical endpoint subsections (H2) with narrative + landscape tables
//         * Internal Dose Assessment (H2) with narrow portrait Table 7
//         * Apical Endpoint BMD Summary (H2) with Table 8
//         * Gene Set BMD Analysis (H2) with Tables 9-10 + GO descriptions
//         * Gene BMD Analysis (H2) with Tables 11-12 + gene descriptions
//     - Summary (H1)
//     - References (H1, numbered list, 10pt)
//
// Typography matches the NIEHS Report 10 PDF (NBK589955):
//   Body:     12pt Times New Roman (Liberation Serif as metric equiv)
//   Headings: Arial Bold (Liberation Sans as metric equiv)
//   Tables:   10pt body, horizontal-rule-only borders
//   Title:    20pt Liberation Sans Bold (inner title page)
// =====================================================================


// --- Parse the incoming JSON data ---
//
// Two modes of operation:
//
//   1. Production mode (from Python):
//      typst.compile() passes data via sys.inputs.data as a JSON string.
//      This is how the web app and API call the template.
//
//   2. Preview/dev mode (from typst watch / typst.app / VS Code + Tinymist):
//      When sys.inputs has no "data" key, the template loads scaffold data
//      from scaffold-data.json in the same directory.  This enables live
//      preview editing — change the .typ file, see the result instantly.
//
//      To regenerate scaffold-data.json after changing the data schema:
//        uv run python -c "
//          from report_pdf import scaffold_report_data; import json
//          data = scaffold_report_data(chemical_name='Perfluorohexanesulfonamide',
//            casrn='41997-13-1', dtxsid='DTXSID50469320')
//          open('scaffold-data.json','w').write(json.dumps(data, indent=2, default=str))
//        "
#let data = if "data" in sys.inputs {
  // Production: data injected by Python typst.compile() call
  json.decode(sys.inputs.data)
} else {
  // Dev/preview: load scaffold JSON from file for live editing
  json("scaffold-data.json")
}


// --- Document metadata ---
// These flow into the PDF's XMP metadata and the document catalog.
// PDF/UA-1 requires a non-empty title and a language tag.
#set document(
  title: data.at("title", default: "5dToxReport"),
  author: data.at("author", default: "5dToxReport"),
  date: auto,
)


// --- Language ---
// Sets /Lang in the PDF catalog — required by PDF/UA-1 for screen
// readers to select the correct pronunciation dictionary.
#set text(lang: "en")


// --- Page setup ---
// US Letter with margins extracted from the NIEHS PDF:
//   Left:   72.0pt = 1.00in (body text x-origin)
//   Right:  ~1.00in (symmetric with left)
//   Top:    First header baseline at y=47.2pt from page top.
//           Typst places the header inside the top margin, so we set
//           top margin to push body content to y≈88pt (where H1 starts),
//           and the header sits above that in the margin area.
//   Bottom: Page number baseline at y=753.4pt → 38.6pt from bottom = 0.54in
#set page(
  paper: "us-letter",
  margin: (left: 1in, right: 1in, top: 1.06in, bottom: 0.91in),
  // header-ascent controls how far the header is raised into the top
  // margin.  Default is 30% — we reduce to 20% so the first header
  // baseline lands at y=47.2pt, matching the NIEHS PDF exactly.
  header-ascent: 20%,
  footer-descent: 30%,
  // Running header — study title centered in 12pt Times New Roman (regular).
  // Extracted from NIEHS PDF: 12pt TimesNewRomanPSMT, centered, two lines,
  // at y=47.2pt and y=61.0pt.  NOT italic, NOT bold.
  // Typst marks page headers/footers as Artifacts automatically,
  // so screen readers skip them (correct PDF/UA behavior).
  //
  // The header is suppressed on the very first page (inner title page)
  // by checking the absolute page counter.  Front matter and body pages
  // all show the running header.
  header: context {
    // Suppress header on the first two physical pages (cover + inner title).
    // counter(page) tracks the logical page number, but the cover page uses
    // page() which creates its own scope.  We use the physical page counter
    // (here.page()) which counts from 1 regardless of counter resets.
    // Page 1 = cover (has its own header: none), page 2 = inner title.
    if here().page() > 2 {
      set text(size: 12pt, font: "Liberation Serif")
      // Constrain header text to ~270pt wide box, centered on page.
      // The NIEHS PDF header wraps at ~261pt text width (line 1: 242.6pt,
      // line 2: 260.9pt), so a 270pt box reproduces the same line breaks.
      //
      // Uses data.running_header (which is built from ta.forms.running_header
      // — the full name, never abbreviated).
      align(center, box(width: 270pt, align(center, data.at("running_header", default: ""))))
    }
  },
  // Page number in footer — 12pt, centered, matching NIEHS PDF (y=753.4pt)
  // Also automatically artifacted by Typst for PDF/UA.
  //
  // Front matter pages use roman numerals (ii, iii, iv, ...);
  // body pages use arabic numerals (1, 2, 3, ...).
  // The first page (title) has no footer.
  footer: context {
    // Suppress footer on cover (page 1) and inner title (page 2).
    // Same physical page check as the header.
    if here().page() > 2 {
      set text(size: 12pt, font: "Liberation Serif")
      align(center, counter(page).display())
    }
  },
)


// --- Body text ---
// 12pt Times New Roman (Liberation Serif is metrically identical).
// Leading and spacing measured from the NIEHS PDF.
#set text(
  font: "Liberation Serif",
  size: 12pt,
)
#set par(
  leading: 6pt,        // Produces 13.8pt baseline-to-baseline for 12pt text,
                       // matching the NIEHS PDF exactly (verified by compiling
                       // test docs and measuring with PyMuPDF)
  spacing: 9pt,        // Paragraph-to-paragraph extra gap: NIEHS PDF shows
                       // 22.8pt total gap vs 13.8pt normal line gap = ~9pt extra
  justify: false,      // NIEHS uses left-aligned (ragged right)
)


// --- Heading styles ---
// Exact sizes extracted from the NIEHS Report 10 PDF (NBK589955)
// using PyMuPDF text matrix analysis:
//   H1 (Background, M&M, Results, Summary): Arial-BoldMT 16.98pt
//   H2 (Study Design, Clinical Pathology):   Arial-BoldMT 15.00pt
//   H3 (Clinical Observations, RNA Isolation): Arial-BoldMT 13.02pt
//
// Gap from "Background" baseline to first body text baseline: 30.8pt.
// Since Typst's `below` is from the bottom of the heading block
// (not baseline), we subtract the descender (~3pt) and account
// for the body text's ascender, landing at ~22pt below spacing.
//
// Typst generates H1-H6 tags in the structure tree automatically.
#show heading.where(level: 1): it => {
  set text(font: "Liberation Sans", size: 17pt, weight: "bold")
  block(above: 24pt, below: 20pt, it.body)
}
#show heading.where(level: 2): it => {
  set text(font: "Liberation Sans", size: 15pt, weight: "bold")
  block(above: 18pt, below: 12pt, it.body)
}
#show heading.where(level: 3): it => {
  set text(font: "Liberation Sans", size: 13pt, weight: "bold")
  block(above: 14pt, below: 8pt, it.body)
}


// --- Link style ---
// NIEHS blue (#0563C1), underlined.
#show link: it => {
  set text(fill: rgb("#0563C1"))
  underline(it)
}


// =====================================================================
// NIEHS table builder
//
// Produces tables with horizontal-rule-only borders:
//   - Thick (1.5pt) top border above header row
//   - Thin (0.5pt) bottom border below header row
//   - Thick (1.5pt) bottom border below last data row
//   - No vertical borders, no interior horizontal borders
//
// All table content uses 10pt Liberation Serif.
// Headers are bold.  Numeric columns are right-aligned.
// =====================================================================

#let niehs-table(headers, rows, caption: none, numeric-cols: (), footnotes: (), definition: none) = {
  // Caption above the table — bold, left-aligned, 11pt
  if caption != none {
    block(spacing: 4pt, text(weight: "bold", size: 11pt, caption))
  }

  let ncols = headers.len()

  // Typst automatically tags this as Table with TR/TH/TD.
  // Font size 8.5pt with 4pt horizontal inset fits 13 columns on a
  // landscape US-letter page without wrapping — matching the NIEHS
  // reference InDesign layout (~8pt body text in data tables).
  set text(size: 8.5pt)
  table(
    // Auto-size each column to fit its widest cell content.
    // Equal-width columns (the old `columns: ncols`) forced 13 columns
    // into 1/13th of the page each (~57pt), wrapping dose headers like
    // "0.15 mg/kg" and data values like "296.5 ± 4.4".  Auto columns
    // let Typst shrink narrow columns (like "n" or "NA") and expand
    // data columns to fit their content on one line.
    columns: (auto,) * ncols,
    align: (col, _) => {
      // First column (Study Day / Endpoint) is left-aligned;
      // all numeric columns (doses, BMD, BMDL) are right-aligned,
      // matching the NIEHS reference alignment.
      if col in numeric-cols { right } else { left }
    },
    stroke: none,
    inset: (x: 4pt, y: 2.5pt),

    // Header row — Typst tags these cells as TH when inside table.header.
    // Line weights match the NIEHS reference:
    //   - Top rule (above headers): ~1pt — thicker, defines table boundary
    //   - Header separator (below headers): ~0.5pt — thin divider
    table.header(
      table.hline(stroke: 1pt + black),
      ..headers.map(h => table.cell(
        align: horizon,  // vertically center header text
        text(weight: "bold", h),
      )),
      table.hline(stroke: 0.5pt + black),
    ),

    // Data rows
    ..rows.flatten(),

    // Bottom border — same weight as top rule (~1pt), matching NIEHS
    // convention where top and bottom rules are equal weight.
    table.footer(
      table.hline(stroke: 1pt + black),
    ),
  )

  // Definition line — unnumbered paragraph below the table rule,
  // above the lettered footnotes.  Used by body weight tables for
  // the BMD/BMDL abbreviation definitions.
  if definition != none {
    set text(size: 9pt)
    set par(leading: 0.4em, spacing: 4pt)
    [#definition]
    parbreak()
  }

  // Footnotes below the table — 9pt, tight leading, lettered a,b,c...
  if footnotes.len() > 0 {
    set text(size: 9pt)
    set par(leading: 0.4em, spacing: 4pt)
    for (i, fn) in footnotes.enumerate() {
      let marker = str.from-unicode(97 + i)
      [#super(marker) #fn \ ]
    }
  }
}


// =====================================================================
// Sex-grouped table builder — bold "Male"/"Female" spanning rows
// =====================================================================

#let sex-grouped-table(headers, male-rows, female-rows, caption: none, numeric-cols: (), footnotes: ()) = {
  if caption != none {
    block(spacing: 4pt, text(weight: "bold", size: 11pt, caption))
  }

  let ncols = headers.len()

  set text(size: 8.5pt)
  table(
    columns: (auto,) * ncols,
    align: (col, _) => {
      if col in numeric-cols { right } else { left }
    },
    stroke: none,
    inset: (x: 4pt, y: 2.5pt),

    table.header(
      table.hline(stroke: 1pt + black),
      ..headers.map(h => table.cell(
        align: horizon,
        text(weight: "bold", h),
      )),
      table.hline(stroke: 0.5pt + black),
    ),

    // Male group
    ..if male-rows.len() > 0 {
      (
        table.cell(colspan: ncols, text(weight: "bold", [Male])),
        ..male-rows.flatten(),
      )
    },

    // Female group
    ..if female-rows.len() > 0 {
      (
        table.cell(colspan: ncols, text(weight: "bold", [Female])),
        ..female-rows.flatten(),
      )
    },

    table.footer(
      table.hline(stroke: 1pt + black),
    ),
  )

  if footnotes.len() > 0 {
    set text(size: 9pt)
    set par(leading: 0.4em, spacing: 4pt)
    for (i, fn) in footnotes.enumerate() {
      let marker = str.from-unicode(97 + i)
      [#super(marker) #fn \ ]
    }
  }
}


// =====================================================================
// Helper: format a numeric value — null/none becomes em dash
// =====================================================================

#let fmt-val(v) = {
  if v == none { "—" }
  else if type(v) == float { str(calc.round(v, digits: 2)) }
  else { str(v) }
}

#let fmt-val3(v) = {
  if v == none { "—" }
  else if type(v) == float { str(calc.round(v, digits: 3)) }
  else { str(v) }
}


// =====================================================================
// Convenience: extract chemical identity fields used throughout
// =====================================================================

#let chem = data.at("chemical_name", default: "Test Article")
#let casrn = data.at("casrn", default: "")
#let dtxsid = data.at("dtxsid", default: "")


// =====================================================================
// Test article name forms
//
// The NIEHS Report 10 follows strict conventions for how the test
// article is named at each structural position in the document:
//
//   title:            Full name (CASRN xxx)     — title pages
//   running_header:   Full name                 — page headers
//   section_intro:    Full name (Abbreviation)  — first sentence of each H1
//   background_intro: Full name (Abbrev) (all IDs) — Background first sentence
//   prose:            Abbreviation              — body text after introduction
//   table_caption:    Full name                 — all table captions
//   procedural:       "test article"            — methods procedural context
//   reference:        Full name                 — reference list entries
//
// These forms are pre-computed by the Python build_test_article_forms()
// function and passed in as data.test_article.forms.  The template pulls
// the .text field from the appropriate form at each position.
//
// If no test_article object is provided (backward compatibility), the
// template falls back to data.chemical_name for all positions.
// =====================================================================

#let ta = data.at("test_article", default: none)
#let ta-forms = if ta != none { ta.at("forms", default: (:)) } else { (:) }

// Helper: resolve a name form by key, with fallback to chemical_name.
// This is the single access point for all chemical name references in
// the template — ensures consistent form usage and easy auditing.
#let ta-form(key) = {
  let form = ta-forms.at(key, default: none)
  if form != none { form.at("text", default: chem) } else { chem }
}
#let report-number = data.at("report_number", default: "")
#let report-date = data.at("report_date", default: "")
#let report-series = data.at("report_series", default: "NIEHS Report Series")

// --- Section-only mode ---
// When section_only is true (set by _apply_section_filter in report_pdf.py),
// the template skips the cover page, inner title page, and all front matter
// (foreword, TOC, tables list, about, peer review, publication details,
// acknowledgments, abstract).  The result is a body-content-only PDF
// suitable for embedding in a per-tab PDF preview iframe.
#let section-only = data.at("section_only", default: false)

// In section-only mode, suppress headers and footers entirely.
// The global #set page() above defines them with page-number checks,
// but for previews we want clean content with no chrome.
// Uses content block [ ] so the set rule applies to all subsequent content.
#if section-only [
  #set page(header: none, footer: none)
]


// =====================================================================
// FRONT MATTER — roman numeral pages
//
// The NIEHS PDF uses roman numerals (ii through xi) for front matter,
// with arabic numerals starting at "Background" (page 1).  The inner
// title page (page 1 absolute) has no header or footer.
//
// Typst's counter(page).display("i") produces lowercase roman numerals.
// We set the footer format to roman here and switch to arabic at the
// body content transition.
// =====================================================================


// =====================================================================
// COVER PAGE: Green gradient background with geometric hexagon overlay
//
// NIEHS page 1: full-bleed cover with:
//   - White header band (top ~100pt) with institution name
//   - Bicolor accent bar: dark gray (#525457) left, green (#78a12e) right
//   - Sage green (#cedbb5) background with hexagonal pattern overlay
//   - Title in 30pt Liberation Sans Bold, #535557
//   - Report number and date in 12pt, #231f20
//   - No page number, no running header
//
// This page uses a completely custom layout (full-bleed background,
// zero margins, no header/footer) and is excluded from the page
// counter.  The inner title page follows on the next page.
// =====================================================================

// Cover page colors extracted from NIEHS Report 10 (NBK589955) page 1
// using PyMuPDF drawing analysis.
#let cover-dark-gray = rgb("#525457")
#let cover-green-accent = rgb("#78a12e")
#let cover-bg-sage = rgb("#cedbb5")
#let cover-title-color = rgb("#535557")
#let cover-meta-color = rgb("#231f20")

// Use page() function to create a single custom page without affecting
// subsequent pages' settings.  The zero margins give a full-bleed effect.
// Skipped in section-only mode (per-tab PDF preview).
#if not section-only [
#page(margin: 0pt, header: none, footer: none)[

  // --- White header band ---
  // Contains the institution name (no NIH logo — we use text only).
  // Occupies the top ~100pt of the page.
  #place(top + left, box(
    width: 100%,
    height: 102pt,
    fill: white,
    // Institution name positioned like the NIEHS PDF: left-aligned,
    // ~40pt from left edge, vertically centered in the white band.
    pad(left: 40pt, top: 30pt,
      text(
        font: "Liberation Sans",
        size: 12.7pt,
        weight: "bold",
        fill: cover-title-color,
        [National Institute of \ Environmental Health Sciences]
      )
    )
  ))

  // --- Bicolor accent bar ---
  // Dark gray left portion (0 to ~72pt), green for the remainder.
  // Sits at y=102pt, height ~17pt.
  #place(top + left, dy: 102pt, box(
    width: 72pt,
    height: 17pt,
    fill: cover-dark-gray,
  ))
  #place(top + left, dx: 65pt, dy: 102pt, box(
    width: 100% - 65pt,
    height: 17pt,
    fill: cover-green-accent,
  ))

  // --- Green background area ---
  // Sage green fill covering from below the accent bar to the page bottom.
  #place(top + left, dy: 119pt, box(
    width: 100%,
    height: 100% - 119pt,
    fill: cover-bg-sage,
  ))

  // --- Hexagonal geometric overlay ---
  // Semi-transparent pattern image extracted from the NIEHS PDF.
  // Positioned to fill the green area below the accent bar.
  #place(top + left, dy: 119pt,
    image("cover-bg.jpg", width: 100%, height: 100% - 119pt, fit: "cover", alt: "Decorative green geometric hexagonal pattern background")
  )

  // --- Title block ---
  // NIEHS uses Myriad Pro Bold 30pt; we use Liberation Sans (metrically
  // similar sans-serif available in all Typst environments).  Color is
  // #535557 (dark gray, not black — gives a softer look against green).
  #place(top + left, dx: 72pt, dy: 190pt, box(width: 75%)[
    #set text(font: "Liberation Sans", size: 30pt, weight: "bold", fill: cover-title-color)
    #set par(leading: 8pt)
    NIEHS Report on the \
    In Vivo Repeat Dose \
    Biological Potency Study of \
    #ta-form("title") \
    in Sprague Dawley \
    #data.at("strain", default: "(Hsd:Sprague Dawley® SD®)") \
    Rats (Gavage Studies)
  ])

  // --- Report number ---
  // Smaller text below the title, left-aligned with it.
  #place(top + left, dx: 72pt, dy: 530pt, box[
    #set text(font: "Liberation Sans", size: 12pt, fill: cover-meta-color)
    #data.at("report_number", default: "")
  ])

  // --- Date ---
  // Near the bottom of the page, left-aligned.
  #place(top + left, dx: 72pt, dy: 660pt, box[
    #set text(font: "Liberation Sans", size: 12pt, fill: cover-meta-color)
    #data.at("report_date", default: "")
  ])
]
] // end: if not section-only (cover page)


// =====================================================================
// PAGE 2: Inner title page
//
// NIEHS page 2: centered bold title, report number, date, publisher.
// No running header, no page number.
//
// Restore normal page margins and suppress header/footer on this page
// (they start on the Foreword page).  The cover page's `set page` with
// zero margins was scoped inside a block, so Typst's page settings
// revert to the defaults declared at the top of the document.
// =====================================================================

// The global header checks counter(page) > 1 to suppress on page 1.
// Since the cover added a page, we reset the counter so the inner
// title page is page 1 again (matching the original header suppression).
// In section-only mode, the inner title page, front matter pages,
// and roman numeral pagination are all skipped — we jump straight
// to body content.
#if not section-only {
  counter(page).update(1)
}

#if not section-only [
#align(center)[
  #block(below: 18pt, above: 72pt)[
    #set text(font: "Liberation Sans", size: 20pt, weight: "bold")

    // Full title: "NIEHS Report on the In Vivo Repeat Dose Biological
    // Potency Study of <Chemical> (CASRN <casrn>) in Sprague Dawley
    // (Hsd:Sprague Dawley® SD®) Rats (Gavage Studies)"
    //
    // Uses the "title" name form which includes "(CASRN xxx)" when
    // a CASRN is available.  This is the most formal identification
    // of the test article in the entire document.
    #let title-name = ta-form("title")
    #let strain = data.at("strain", default: "(Hsd:Sprague Dawley® SD®)")

    NIEHS Report on the \
    In Vivo Repeat Dose Biological Potency Study of \
    #title-name \
    in Sprague Dawley #strain Rats \
    (Gavage Studies)

    // Report number (e.g., "NIEHS Report 10")
    #if report-number != "" {
      v(12pt)
      set text(size: 12pt, weight: "regular")
      report-number
    }

    // Date
    #if report-date != "" {
      v(8pt)
      set text(size: 12pt, weight: "regular")
      report-date
    }

    // Publisher block — centered, below the title
    #v(72pt)
    #set text(size: 12pt, weight: "regular")
    National Institute of Environmental Health Sciences \
    Public Health Service \
    U.S. Department of Health and Human Services \
    #if data.at("issn", default: "") != "" {
      [ISSN: #data.at("issn", default: "")]
      linebreak()
    }
    Research Triangle Park, North Carolina, USA
  ]
]
] // end: if not section-only (inner title page)


// =====================================================================
// FRONT MATTER PAGES: Foreword, TOC, About, Peer Review, etc.
//
// All front matter pages use roman numeral pagination.  We set the
// page counter display to roman numerals and start at "ii" (the inner
// title page was "i" implicitly but had no visible footer).
// =====================================================================

// Start roman numbering at ii (title page was conceptually "i")
// Skipped in section-only mode — body content uses arabic numbering.
#if not section-only [
#set page(
  footer: context {
    set text(size: 12pt, font: "Liberation Serif")
    align(center, counter(page).display("i"))
  },
)
#counter(page).update(2)


// --- Foreword ---
// NIEHS page 3 (ii): boilerplate about the NIEHS mission and report series.
// Provided as data.foreword (paragraphs array) or omitted.
#if data.at("foreword", default: none) != none {
  pagebreak()
  heading(level: 1, "Foreword")
  for para in data.foreword.at("paragraphs", default: ()) {
    [#para]
    parbreak()
  }
}


// --- Table of Contents ---
// NIEHS pages 4-5 (iii-iv): auto-generated from heading hierarchy.
// The outline() function generates a linked TOC from all headings.
#pagebreak()
#heading(level: 1, outlined: false, "Table of Contents")
#outline(
  title: none,    // We already placed the heading above
  indent: 1.5em,  // Indent sub-sections
  depth: 3,       // Show H1, H2, H3
)

// --- Tables list ---
// NIEHS page 5 (iv): list of all tables by number.
// We use Typst's built-in figure outline for tables.
// Tables are wrapped in figure() calls with kind: "table" for this to work.
// For now, we emit a "Tables" heading; the list will populate automatically
// if/when tables are converted to figure() wrappers in a future iteration.
#v(24pt)
#heading(level: 1, outlined: false, "Tables")
#context {
  // Show outline of table figures if any exist
  let table-figs = query(figure.where(kind: table))
  if table-figs.len() > 0 {
    outline(title: none, target: figure.where(kind: table))
  } else {
    // Placeholder — table numbering is currently inline in captions
    text(style: "italic", size: 10pt, "(Table numbering follows inline captions throughout the report.)")
  }
}


// --- About This Report ---
// NIEHS pages 6-8 (v-vii): authors list with affiliations, then
// contributor roles organized by institution.  Data arrives as
// data.about_report with "authors" and "contributors" arrays.
#if data.at("about_report", default: none) != none {
  pagebreak()
  let about = data.about_report
  heading(level: 1, "About This Report")

  // Authors section
  let authors = about.at("authors", default: none)
  if authors != none {
    heading(level: 2, "Authors")
    for para in authors.at("paragraphs", default: ()) {
      [#para]
      parbreak()
    }
  }

  // Contributors section
  let contributors = about.at("contributors", default: none)
  if contributors != none {
    heading(level: 2, "Contributors")
    for para in contributors.at("paragraphs", default: ()) {
      [#para]
      parbreak()
    }
  }
}


// --- Peer Review ---
// NIEHS page 9 (viii): brief statement about the peer review process.
#if data.at("peer_review", default: none) != none {
  pagebreak()
  heading(level: 1, "Peer Review")
  for para in data.peer_review.at("paragraphs", default: ()) {
    [#para]
    parbreak()
  }
}


// --- Publication Details ---
// NIEHS page 10 (ix): publisher, ISSN, DOI, official citation.
#if data.at("publication_details", default: none) != none {
  pagebreak()
  let pub = data.publication_details
  heading(level: 1, "Publication Details")
  for para in pub.at("paragraphs", default: ()) {
    [#para]
    parbreak()
  }
}


// --- Acknowledgments ---
// NIEHS page 10 (ix): funding acknowledgment, appears on same page
// as publication details in the NIEHS PDF.
#if data.at("acknowledgments", default: none) != none {
  heading(level: 1, "Acknowledgments")
  for para in data.acknowledgments.at("paragraphs", default: ()) {
    [#para]
    parbreak()
  }
}


// --- Abstract ---
// NIEHS pages 11-12 (x-xi): structured abstract with bold inline labels
// (Background:, Methods:, Results:, Summary:).  Each label starts a
// paragraph.  The Abstract is the last front-matter section before the
// page counter resets to arabic.
#if data.at("abstract", default: none) != none {
  pagebreak()
  heading(level: 1, "Abstract")

  let abs = data.abstract
  // Each subsection has a bold label followed by body text
  for sub in abs.at("sections", default: ()) {
    let lbl = sub.at("label", default: "")
    let txt = sub.at("text", default: "")
    if lbl != "" {
      [*#lbl:* #txt]
    } else {
      [#txt]
    }
    parbreak()
  }

  // Flat paragraphs fallback (if not using labeled sections)
  for para in abs.at("paragraphs", default: ()) {
    [#para]
    parbreak()
  }
}
] // end: if not section-only (front matter)


// =====================================================================
// BODY — arabic numeral pages, counter reset to 1
//
// The NIEHS PDF resets page numbering to "1" at the Background section.
// We switch the footer display format to arabic and reset the counter.
// =====================================================================

// Reset to arabic numbering starting at page 1.
// In section-only mode, skip entirely — no page numbering setup needed.
#if not section-only [
  #set page(
    footer: context {
      set text(size: 12pt, font: "Liberation Serif")
      align(center, counter(page).display("1"))
    },
  )
  #counter(page).update(1)
]


// --- Background ---
// NIEHS page 13 (body page 1): Background H1 with body paragraphs
// containing superscript reference numbers.
// Each major section (H1) starts on a new page, matching the NIEHS PDF
// where Background (pg13), M&M (pg14), Results (pg23), and Summary (pg47)
// all begin at the top of a fresh page.
#if data.at("background", default: none) != none {
  pagebreak(weak: true)
  let bg = data.background
  heading(level: 1, "Background")
  for para in bg.at("paragraphs", default: ()) {
    [#para]
    parbreak()
  }
}


// --- Materials and Methods ---
// NIEHS pages 14-22 (body 2-10): structured hierarchy of H2/H3 subsections.
// Table 1 (Final Sample Counts) appears inline within the Transcriptomics
// subsection on page 17.
#if data.at("methods", default: none) != none {
  pagebreak()
  let methods = data.methods
  heading(level: 1, "Materials and Methods")

  // Structured sections — each has a heading level, paragraphs, and
  // optionally an inline table (e.g., Table 1 — Study Design).
  for sec in methods.at("sections", default: ()) {
    // All M&M subsections render as H2 under the H1 "Materials and Methods".
    // PDF/UA-1 forbids skipping heading levels (H1 → H3), and the data
    // may not guarantee H2 entries precede H3 entries.  Using H2 for all
    // sections is robust and the TOC still shows the full structure.
    heading(level: 2, sec.at("heading", default: ""))

    for para in sec.at("paragraphs", default: ()) {
      [#para]
      parbreak()
    }

    // Inline table (e.g., Table 1 — Study Design sample counts)
    let tbl = sec.at("table", default: none)
    if tbl != none {
      niehs-table(
        tbl.at("headers", default: ()),
        tbl.at("rows", default: ()),
        caption: tbl.at("caption", default: none),
        footnotes: tbl.at("footnotes", default: ()),
      )
    }
  }

  // Legacy flat paragraphs fallback — for methods data that hasn't
  // been structured into headed sections yet.
  if methods.at("sections", default: ()).len() == 0 {
    for para in methods.at("paragraphs", default: ()) {
      [#para]
      parbreak()
    }
  }
}


// =====================================================================
// RESULTS
//
// NIEHS pages 23-46 (body 11-34): the largest section of the report.
// Structure:
//   Results (H1)
//   ├── Animal Condition, Body Weights, and Organ Weights (H2)
//   │   ├── narrative paragraphs (portrait)
//   │   ├── Table 2: Body Weights (LANDSCAPE)
//   │   └── Table 3: Liver Weights (LANDSCAPE)
//   ├── Clinical Pathology (H2)
//   │   ├── narrative paragraphs (portrait)
//   │   ├── Table 4: Clinical Chemistry (LANDSCAPE)
//   │   ├── Table 5: Hematology (LANDSCAPE)
//   │   └── Table 6: Hormones (LANDSCAPE)
//   ├── Internal Dose Assessment (H2)
//   │   ├── narrative paragraphs
//   │   └── Table 7: Plasma Concentrations (portrait, narrow)
//   ├── Apical Endpoint BMD Summary (H2)
//   │   └── Table 8: BMD Summary (portrait, 6-col)
//   ├── Gene Set Benchmark Dose Analysis (H2)
//   │   ├── narrative paragraphs
//   │   ├── Table 9: Liver Gene Sets (portrait, multi-page)
//   │   │   └── GO process descriptions
//   │   └── Table 10: Kidney Gene Sets (portrait, multi-page)
//   │       └── GO process descriptions
//   └── Gene Benchmark Dose Analysis (H2)
//       ├── narrative paragraphs
//       ├── Table 11: Liver Genes (portrait, multi-page)
//       │   └── Gene descriptions (UniProt/Entrez)
//       └── Table 12: Kidney Genes (portrait, multi-page)
//           └── Gene descriptions (UniProt/Entrez)
// =====================================================================

// Determine whether this is a leaf preview (single table, no unified
// narratives — render only the table, no headings) vs a group preview
// (section with headings + narrative, rendered as in the full report).
#let _is-leaf-preview = (
  section-only
  and data.at("apical_sections", default: ()).len() <= 1
  and data.at("unified_narratives", default: (:)).keys().len() == 0
)
#let _skip-headings = _is-leaf-preview

// Compute whether we have any results content.
#let has-results = (
  data.at("apical_sections", default: ()).len() > 0 or
  data.at("internal_dose", default: none) != none or
  data.at("bmd_summary", default: none) != none or
  data.at("genomics_sections", default: ()).len() > 0
)

// Emit the "Results" H1 heading.
// - Full report: pagebreak + H1
// - Group preview (section-only, multiple tables): H1 only (no pagebreak)
// - Leaf preview (single table): skip entirely (no headings at all)
#if has-results and not _is-leaf-preview {
  if not section-only {
    pagebreak()
  }
  heading(level: 1, "Results")
}


// --- Apical endpoint sections ---
// NIEHS structure groups apical sections under two H2 headings:
//   1. "Animal Condition, Body Weights, and Organ Weights" — BW, OW, ClinObs
//   2. "Clinical Pathology" — Clin Chem, Hematology, Hormones
// Each heading has a unified narrative (spanning multiple tables), followed
// by per-table sections.  The unified narrative comes from the user-editable
// textarea in the UI.

// Pre-compute group membership for each apical section so we can emit
// NIEHS TOC group headings (H2) and unified narratives at the right
// transition points during the single iteration over apical_sections.
//
// The sections array is ordered by the server (BW, OW, ClinObs, CC, Hem,
// Hormones) so group transitions happen naturally.  We detect transitions
// by comparing each section's group key to the previous one.

#let _unified = data.at("unified_narratives", default: (:))

#let _group-for-platform = (
  "Body Weight": "animal_condition",
  "Organ Weight": "animal_condition",
  "Clinical Observations": "animal_condition",
  "Clinical": "animal_condition",
  "Clinical Chemistry": "clinical_pathology",
  "Hematology": "clinical_pathology",
  "Hormones": "clinical_pathology",
)

#let _group-titles = (
  "animal_condition": "Animal Condition, Body Weights, and Organ Weights",
  "clinical_pathology": "Clinical Pathology",
)

// Build an array of (group-key, section) pairs, then iterate with index
// to detect group transitions.
#let _apical-with-groups = data.at("apical_sections", default: ()).map(sec => {
  let p = sec.at("platform", default: sec.at("title", default: ""))
  let g = _group-for-platform.at(p, default: none)
  (g, sec)
})

// Track which groups we've already emitted headings for.
// Since Typst for-loops can't mutate outer variables, we pre-compute
// which indices are "first in group" before the loop.
#let _first-in-group = {
  let seen = ()
  let result = ()
  for (g, _sec) in _apical-with-groups {
    if g != none and g not in seen {
      result.push(true)
      seen.push(g)
    } else {
      result.push(false)
    }
  }
  result
}

#for (idx, pair) in _apical-with-groups.enumerate() {
  let (group-key, sec) = pair

  // In section-only mode (leaf preview), skip all headings and narratives —
  // render only the table content.  In full-report mode, emit group H2
  // headings with unified narratives at group transitions.
  if not _skip-headings {
    if _first-in-group.at(idx, default: false) {
      let group-title = _group-titles.at(group-key, default: "")
      if group-title != "" {
        heading(level: 2, group-title)
      }
      for para in _unified.at(group-key, default: ()) {
        [#para]
        parbreak()
      }
    }

  }

  // Data table — single table with Male/Female sex-group separator rows,
  // matching NIEHS Report 10 Tables 2-6 structure.  Each sex gets a bold
  // separator row spanning all columns, followed by an "n" row (sample
  // sizes per dose group) and then the endpoint data rows.
  let dose-unit = sec.at("dose_unit", default: "mg/kg")
  let male-data = sec.at("table_data", default: (:)).at("Male", default: ())
  let female-data = sec.at("table_data", default: (:)).at("Female", default: ())

  if male-data.len() > 0 or female-data.len() > 0 {
    // Caption — uses {compound} placeholder only (no {sex} since both
    // sexes are in one table).  Remove any leftover {sex} placeholder.
    // If table_number is present, prepend "Table N. " to match the NIEHS
    // reference format: "Table 2. Summary of Body Weights of ..."
    let raw-caption = sec.at("caption", default: "")
      .replace(" of {sex} Rats", " of Male and Female Rats")
      .replace("{sex}", "Male and Female")
      .replace("{compound}", ta-form("table_caption"))
    let tbl-num = sec.at("table_number", default: none)
    let caption-text = if tbl-num != none {
      "Table " + str(tbl-num) + ". " + raw-caption
    } else {
      raw-caption
    }

    // Use whichever sex has data for dose columns
    let ref-data = if male-data.len() > 0 { male-data } else { female-data }
    let doses = ref-data.at(0).at("doses", default: ())

    // Build header array.
    // The first column header comes from the section data — "Study Day"
    // for body weight tables (rows are day 0, day 5), "Endpoint" for
    // all other apical tables (rows are measured parameters).
    // Footnote markers (a,b) are appended to body weight headers per
    // NIEHS convention — superscript letters referencing table footnotes.
    let first-col = sec.at("first_col_header", default: "Endpoint")
    let first-col-display = if first-col == "Study Day" {
      [Study Day#super[a,b]]
    } else {
      first-col
    }
    let headers = (first-col-display,)
    for dose in doses {
      // Use non-breaking spaces so dose headers don't wrap across lines.
      // The reference PDF shows "0.15 mg/kg" on a single line, not split.
      let label = if dose == 0 {
        "0\u{00a0}" + dose-unit
      } else {
        str(dose) + "\u{00a0}" + dose-unit
      }
      headers += (label,)
    }
    headers += (
      "BMD₁Std (" + dose-unit + ")",
      "BMDL₁Std (" + dose-unit + ")",
    )

    let ncols = headers.len()
    let num-cols = range(1, ncols)

    // --- Build combined rows with sex group separators ---
    // Each sex block: bold "Male"/"Female" separator → n row → endpoint rows
    let tbl-rows = ()

    // Collect all footnotes (section-level + per-sex missing-animal).
    // For body weight tables ("Study Day" header), prepend the standard
    // NIEHS footnotes that the superscript a,b markers reference.
    let all-fn = sec.at("footnotes", default: ()).map(x => x)
    if first-col == "Study Day" and all-fn.len() == 0 {
      all-fn = (
        "Data are displayed as mean \u{00b1} standard error of the mean; body weight data are presented in grams.",
        "Statistical analysis performed by the Jonckheere (trend) and Williams or Dunnett (pairwise) tests.",
      )
    }
    let missing-fn = sec.at("missing_animal_footnotes", default: (:))

    for (sex, rows-data) in (("Male", male-data), ("Female", female-data)) {
      if rows-data.len() == 0 { continue }

      // Bold sex separator row spanning all columns
      tbl-rows += ((table.cell(colspan: ncols, text(weight: "bold", sex)),),)

      // Check if Python pre-built the complete row grid (sidecar path).
      // When the first row has is_n_row=true, the data contains every row
      // the table needs — including the n row — and the template just
      // renders them verbatim.  No data logic in the template.
      let has-prebuilt-grid = rows-data.at(0).at("is_n_row", default: false)

      if has-prebuilt-grid {
        // ── Pre-built grid: render rows as-is ─────────────────────────
        // Python already decided which rows exist, what each cell shows,
        // and where attrition markers go.  The template is a pure renderer.
        //
        // The `markers` dict on the n-row maps dose keys to footnote
        // letters (e.g., {"1000": "c"}).  We render these as superscripts
        // after the cell value: "4" + superscript "c" → "4ᶜ".
        for r in rows-data {
          let label = r.at("label", default: "")
          let row-markers = r.at("markers", default: (:))
          let row = (label,)
          for dose in doses {
            let val = r.at("values", default: (:)).at(str(dose), default: "")
            let marker = row-markers.at(str(dose), default: none)
            if marker != none {
              row += ([#val#super[#marker]],)
            } else {
              row += (str(val),)
            }
          }
          row += (
            str(r.at("bmd", default: "")),
            str(r.at("bmdl", default: "")),
          )
          tbl-rows += (row,)
        }
      } else {
        // ── Legacy path: template constructs n row + data rows ────────
        // For non-sidecar sections (organ weight, clinical chem, etc.)
        // the template builds the n row from per-row N counts and
        // strips SD prefixes from labels.  This path will be deprecated
        // as more platforms adopt the pre-built grid approach.
        let n-row = ("n",)
        let sex-markers = (:)
        for r in rows-data {
          let rm = r.at("attrition_markers", default: (:))
          for (dk, letter) in rm {
            sex-markers.insert(dk, letter)
          }
        }
        for dose in doses {
          let max-n = 0
          for r in rows-data {
            let nn = r.at("n", default: (:)).at(str(dose), default: 0)
            if nn > max-n { max-n = nn }
          }
          let marker = sex-markers.at(str(dose), default: none)
          if max-n > 0 {
            if marker != none {
              n-row += ([#str(max-n)#super[#marker]],)
            } else {
              n-row += (str(max-n),)
            }
          } else {
            if marker != none {
              n-row += ([–#super[#marker]],)
            } else {
              n-row += ("–",)
            }
          }
        }
        n-row += ("NA", "NA")
        tbl-rows += (n-row,)

        for r in rows-data {
          let raw-label = r.at("label", default: "")
          let label = if raw-label.starts-with("SD") {
            raw-label.slice(2)
          } else {
            raw-label
          }
          let row = (label,)
          for dose in doses {
            let val = r.at("values", default: (:)).at(str(dose), default: "–")
            row += (str(val),)
          }
          row += (
            str(r.at("bmd", default: "–")),
            str(r.at("bmdl", default: "–")),
          )
          tbl-rows += (row,)
        }
      }

      // Append per-sex missing-animal footnote if present
      let sex-fn = missing-fn.at(sex, default: none)
      if sex-fn != none {
        all-fn.push(sex-fn)
      }
    }

    // Wide tables (≥5 dose groups) get their own landscape page,
    // matching the NIEHS pattern where Tables 2-6 are landscape.
    // Narrow tables stay inline on the current portrait page.
    //
    // `set page(flipped: true/false)` implicitly triggers a page break
    // in Typst, so no explicit pagebreak() is needed.  Using both would
    // create an unwanted blank page.
    // BMD definition line — only present on tables that include it
    // (body weight tables from body_weight_table.py builder).
    let bmd-def = sec.at("bmd_definition", default: none)

    if doses.len() >= 5 {
      set page(flipped: true)
      niehs-table(
        headers,
        tbl-rows,
        caption: if caption-text != "" { caption-text },
        numeric-cols: num-cols,
        footnotes: all-fn,
        definition: bmd-def,
      )
      set page(flipped: false)
    } else {
      niehs-table(
        headers,
        tbl-rows,
        caption: if caption-text != "" { caption-text },
        numeric-cols: num-cols,
        footnotes: all-fn,
        definition: bmd-def,
      )
      v(12pt)
    }
  }
}


// --- Internal Dose Assessment ---
// NIEHS page 30 (body 18): narrative about plasma concentrations and
// half-lives, followed by Table 7 (narrow, 3-column portrait table with
// 2-hour and 24-hour postdose concentrations for 4 and 37 mg/kg groups).
#if data.at("internal_dose", default: none) != none {
  let idose = data.internal_dose
  heading(level: 2, "Internal Dose Assessment")

  // Narrative paragraphs
  for para in idose.at("paragraphs", default: ()) {
    [#para]
    parbreak()
  }

  // Table 7 — narrow portrait table
  let tbl = idose.at("table", default: none)
  if tbl != none {
    niehs-table(
      tbl.at("headers", default: ()),
      tbl.at("rows", default: ()),
      caption: tbl.at("caption", default: none),
      footnotes: tbl.at("footnotes", default: ()),
    )
    v(12pt)
  }
}


// --- Apical Endpoint BMD Summary ---
// NIEHS page 31 (body 19): Table 8 — sex-grouped 6-column portrait table
// showing BMD, BMDL, LOEL, NOEL, and direction for each endpoint.
// Preceded by a brief narrative paragraph.
#if data.at("bmd_summary", default: none) != none {
  let bmd = data.bmd_summary
  let endpoints = bmd.at("endpoints", default: ())
  if endpoints.len() > 0 {
    pagebreak()
    heading(level: 2, "Apical Endpoint Benchmark Dose Summary")

    // Optional narrative before the table
    for para in bmd.at("paragraphs", default: ()) {
      [#para]
      parbreak()
    }

    let male-eps = endpoints.filter(e => e.at("sex", default: "") == "Male")
    let female-eps = endpoints.filter(e => e.at("sex", default: "") == "Female")

    let male-rows = male-eps.map(ep => (
      ep.at("endpoint", default: ""),
      fmt-val(ep.at("bmd", default: none)),
      fmt-val(ep.at("bmdl", default: none)),
      fmt-val(ep.at("loel", default: none)),
      fmt-val(ep.at("noel", default: none)),
      ep.at("direction", default: ""),
    ))

    let female-rows = female-eps.map(ep => (
      ep.at("endpoint", default: ""),
      fmt-val(ep.at("bmd", default: none)),
      fmt-val(ep.at("bmdl", default: none)),
      fmt-val(ep.at("loel", default: none)),
      fmt-val(ep.at("noel", default: none)),
      ep.at("direction", default: ""),
    ))

    sex-grouped-table(
      ("Endpoint", "BMD₁Std", "BMDL₁Std", "LOEL", "NOEL", "Direction"),
      male-rows,
      female-rows,
      caption: bmd.at("caption", default: "BMD, BMDL, LOEL, and NOEL Summary for Apical Endpoints, Sorted by BMD or LOEL from Low to High"),
      numeric-cols: (1, 2, 3, 4),
      footnotes: bmd.at("footnotes", default: ()),
    )
  }
}


// --- Genomics Results ---
// NIEHS pages 31-46 (body 19-34): two major H2 subsections:
//   1. Gene Set Benchmark Dose Analysis — narrative + Tables 9-10 + GO descriptions
//   2. Gene Benchmark Dose Analysis — narrative + Tables 11-12 + gene descriptions
//
// Each organ (liver, kidney) has its own table.  Gene set tables use an
// 8-column layout; gene tables use a 6-column layout.  Both are portrait.
// GO descriptions and gene descriptions (UniProt/Entrez text) follow their
// respective tables as dense 9pt text blocks.
#let genomics = data.at("genomics_sections", default: ())
#if genomics.len() > 0 {

  // --- Gene Set Benchmark Dose Analysis ---
  // NIEHS page 31 (body 19): H2 heading + narrative, then Tables 9-10
  let gene-set-sections = genomics.filter(gs => gs.at("type", default: "gene_set") == "gene_set")
  let gene-sections = genomics.filter(gs => gs.at("type", default: "") == "gene")

  // If we have gene_set type sections, emit them under the Gene Set heading.
  // If the data doesn't use the "type" field, fall back to the original
  // behavior of rendering everything under a single "Transcriptomic BMD Analysis" heading.
  let has-typed-sections = gene-set-sections.len() > 0 or gene-sections.len() > 0

  if has-typed-sections {
    // --- Gene Set BMD Analysis (H2) ---
    if gene-set-sections.len() > 0 {
      pagebreak()
      heading(level: 2, "Gene Set Benchmark Dose Analysis")

      // Shared narrative for gene set analysis
      let gs-narrative = data.at("gene_set_narrative", default: none)
      if gs-narrative != none {
        for para in gs-narrative.at("paragraphs", default: ()) {
          [#para]
          parbreak()
        }
      }

      for gs-sec in gene-set-sections {
        let organ = gs-sec.at("organ", default: "")
        let sex = gs-sec.at("sex", default: "")
        let label = if organ != "" and sex != "" {
          upper(organ.first()) + organ.slice(1) + " — " + upper(sex.first()) + sex.slice(1)
        } else if organ != "" {
          upper(organ.first()) + organ.slice(1)
        } else { "" }

        if label != "" { heading(level: 3, label) }

        // Gene sets table — use the stat label from the section (e.g. "5th %ile")
        // falling back to "Median" for legacy data that doesn't carry a label.
        let gene-sets = gs-sec.at("gene_sets", default: ())
        if gene-sets.len() > 0 {
          let stat-label = gs-sec.at("bmd_stat_label", default: "Median")
          let gs-rows = gene-sets.map(gs => (
            gs.at("go_term", default: ""),
            gs.at("go_id", default: ""),
            fmt-val3(gs.at("bmd", default: gs.at("bmd_median", default: none))),
            fmt-val3(gs.at("bmdl", default: gs.at("bmdl_median", default: none))),
            str(gs.at("n_genes", default: "")),
            gs.at("direction", default: ""),
          ))

          niehs-table(
            ("GO Term", "GO ID", "BMD " + stat-label, "BMDL " + stat-label, "# Genes", "Direction"),
            gs-rows,
            caption: gs-sec.at("caption", default: "Gene Set BMD Analysis — " + label),
            numeric-cols: (2, 3, 4),
            footnotes: gs-sec.at("footnotes", default: ()),
          )
          v(8pt)
        }

        // GO process descriptions — dense 9pt text block following the table
        // In the NIEHS PDF, these appear as compact paragraphs with bold
        // GO IDs followed by their definitions.
        let go-descriptions = gs-sec.at("go_descriptions", default: ())
        if go-descriptions.len() > 0 {
          set text(size: 9pt)
          set par(leading: 0.3em, spacing: 3pt)
          for desc in go-descriptions {
            let go-id = desc.at("go_id", default: "")
            let go-name = desc.at("name", default: "")
            let definition = desc.at("definition", default: "")
            [*#go-id #go-name:* #definition]
            parbreak()
          }
        }
      }
    }

    // --- Gene BMD Analysis (H2) ---
    // NIEHS page 38 (body 26): starts on a new page
    if gene-sections.len() > 0 {
      pagebreak()
      heading(level: 2, "Gene Benchmark Dose Analysis")

      // Shared narrative for gene analysis
      let gene-narrative = data.at("gene_narrative", default: none)
      if gene-narrative != none {
        for para in gene-narrative.at("paragraphs", default: ()) {
          [#para]
          parbreak()
        }
      }

      for g-sec in gene-sections {
        let organ = g-sec.at("organ", default: "")
        let sex = g-sec.at("sex", default: "")
        let label = if organ != "" and sex != "" {
          upper(organ.first()) + organ.slice(1) + " — " + upper(sex.first()) + sex.slice(1)
        } else if organ != "" {
          upper(organ.first()) + organ.slice(1)
        } else { "" }

        if label != "" { heading(level: 3, label) }

        // Top genes table
        let top-genes = g-sec.at("top_genes", default: ())
        if top-genes.len() > 0 {
          let gene-rows = top-genes.map(g => (
            // Gene symbols are conventionally italicized in biology
            emph(g.at("gene_symbol", default: "")),
            fmt-val3(g.at("bmd", default: none)),
            fmt-val3(g.at("bmdl", default: none)),
            fmt-val(g.at("fold_change", default: none)),
            g.at("direction", default: ""),
          ))

          niehs-table(
            ("Gene", "BMD", "BMDL", "Fold Change", "Direction"),
            gene-rows,
            caption: g-sec.at("caption", default: "Gene BMD Analysis — " + label),
            numeric-cols: (1, 2, 3),
            footnotes: g-sec.at("footnotes", default: ()),
          )
          v(8pt)
        }

        // Gene descriptions — dense text block with UniProt/Entrez annotations
        // In the NIEHS PDF (pages 41-46, 44-46), each gene symbol is bold
        // followed by its functional description from public databases.
        let gene-descriptions = g-sec.at("gene_descriptions", default: ())
        if gene-descriptions.len() > 0 {
          set text(size: 9pt)
          set par(leading: 0.3em, spacing: 3pt)
          for desc in gene-descriptions {
            let symbol = desc.at("gene_symbol", default: "")
            let description = desc.at("description", default: "")
            [*#emph(symbol):* #description]
            parbreak()
          }
        }
      }
    }

  } else {
    // --- Fallback: untyped genomics sections ---
    // Original behavior — all genomics data under a single heading.
    // Used when the data doesn't distinguish gene_set vs gene types.
    pagebreak()
    heading(level: 2, "Transcriptomic BMD Analysis")

    for gs-sec in genomics {
      let organ = gs-sec.at("organ", default: "")
      let sex = gs-sec.at("sex", default: "")
      let label = upper(organ.first()) + organ.slice(1) + " — " + upper(sex.first()) + sex.slice(1)

      heading(level: 3, label)

      // Gene sets table — use the stat label from the section if available
      let gene-sets = gs-sec.at("gene_sets", default: ())
      if gene-sets.len() > 0 {
        let stat-label = gs-sec.at("bmd_stat_label", default: "Median")
        let gs-rows = gene-sets.map(gs => (
          gs.at("go_term", default: ""),
          gs.at("go_id", default: ""),
          fmt-val3(gs.at("bmd", default: gs.at("bmd_median", default: none))),
          fmt-val3(gs.at("bmdl", default: gs.at("bmdl_median", default: none))),
          str(gs.at("n_genes", default: "")),
          gs.at("direction", default: ""),
        ))

        niehs-table(
          ("GO Term", "GO ID", "BMD " + stat-label, "BMDL " + stat-label, "# Genes", "Direction"),
          gs-rows,
          caption: "Gene Set BMD Analysis — " + label,
          numeric-cols: (2, 3, 4),
        )
        v(8pt)
      }

      // GO descriptions (if provided)
      let go-descriptions = gs-sec.at("go_descriptions", default: ())
      if go-descriptions.len() > 0 {
        set text(size: 9pt)
        set par(leading: 0.3em, spacing: 3pt)
        for desc in go-descriptions {
          let go-id = desc.at("go_id", default: "")
          let go-name = desc.at("name", default: "")
          let definition = desc.at("definition", default: "")
          [*#go-id #go-name:* #definition]
          parbreak()
        }
      }

      // Top genes table
      let top-genes = gs-sec.at("top_genes", default: ())
      if top-genes.len() > 0 {
        let gene-rows = top-genes.map(g => (
          emph(g.at("gene_symbol", default: "")),
          fmt-val3(g.at("bmd", default: none)),
          fmt-val3(g.at("bmdl", default: none)),
          fmt-val(g.at("fold_change", default: none)),
          g.at("direction", default: ""),
        ))

        niehs-table(
          ("Gene", "BMD", "BMDL", "Fold Change", "Direction"),
          gene-rows,
          caption: "Gene BMD Analysis — " + label,
          numeric-cols: (1, 2, 3),
        )
        v(8pt)
      }

      // Gene descriptions (if provided)
      let gene-descriptions = gs-sec.at("gene_descriptions", default: ())
      if gene-descriptions.len() > 0 {
        set text(size: 9pt)
        set par(leading: 0.3em, spacing: 3pt)
        for desc in gene-descriptions {
          let symbol = desc.at("gene_symbol", default: "")
          let description = desc.at("description", default: "")
          [*#emph(symbol):* #description]
          parbreak()
        }
      }
    }
  }
}


// --- Summary ---
// NIEHS page 47 (body 35): concluding paragraphs synthesizing all results.
#if data.at("summary", default: none) != none {
  pagebreak()
  heading(level: 1, "Summary")
  for para in data.summary.at("paragraphs", default: ()) {
    [#para]
    parbreak()
  }
}


// --- Genomics Charts ---
// Client-captured Plotly visualizations embedded as figures.
// These appear after all genomics tables and before References.
// Each chart has a heading, the image, and an italic caption below.
//
// The chart images are written to temp PNG files alongside this template
// by build_report_pdf() in report_pdf.py.  The data dict contains their
// filenames (relative to this template's directory) and caption strings.
#let charts = data.at("genomics_charts", default: none)
#if charts != none {
  // UMAP Scatter Plot — no # prefix inside code blocks (already in code mode)
  let umap-path = charts.at("umap_path", default: none)
  if umap-path != none {
    heading(level: 2, "GO Term Semantic Map (UMAP)")
    figure(
      image(umap-path, width: 90%, alt: "UMAP scatter plot of GO Biological Process terms colored by HDBSCAN semantic cluster"),
      caption: text(size: 9pt, style: "italic", charts.at("umap_caption", default: "")),
    )
  }
  // Cluster Scatter Plot
  let cluster-path = charts.at("cluster_path", default: none)
  if cluster-path != none {
    heading(level: 2, "GO Category Cluster Scatter")
    figure(
      image(cluster-path, width: 90%, alt: "Category cluster scatter plot showing GO terms grouped by gene-overlap similarity and colored by semantic cluster"),
      caption: text(size: 9pt, style: "italic", charts.at("cluster_caption", default: "")),
    )
  }
}


// --- References ---
// NIEHS pages 48-50 (body 36-38): numbered reference list in 10pt text
// with hanging indent.  In the NIEHS PDF, references are a standalone H1
// section (not nested under Background).  URLs appear as blue links.
//
// References can be provided as:
//   1. data.references (top-level array) — preferred, standalone section
//   2. data.background.references — legacy location, backward compatible
#let refs = data.at("references", default: ())
// Fall back to background.references if no top-level references
#if refs.len() == 0 {
  refs = data.at("background", default: (:)).at("references", default: ())
}
#if refs.len() > 0 {
  pagebreak()
  heading(level: 1, "References")
  set text(size: 10pt)
  set par(hanging-indent: 2em)  // Hanging indent for reference entries
  for (i, ref) in refs.enumerate() {
    [#(i + 1). #ref]
    parbreak()
  }
}

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
// Typography matches the NIEHS Report 10 PDF (NBK589955):
//   Body:     12pt Times New Roman (Liberation Serif as metric equiv)
//   Headings: Arial Bold (Liberation Sans as metric equiv)
//   Tables:   10pt body, horizontal-rule-only borders
//   Title:    24pt Myriad Pro / Liberation Sans fallback
// =====================================================================


// --- Parse the incoming JSON data ---
// sys.inputs is a dictionary of string key-value pairs passed from
// the Python caller.  "data" contains the full report as a JSON string.
#let data = json.decode(sys.inputs.data)


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
  header: context {
    // Skip header on the first page (title page)
    if counter(page).get().first() > 1 {
      set text(size: 12pt, font: "Liberation Serif")
      // Constrain header text to ~270pt wide box, centered on page.
      // The NIEHS PDF header wraps at ~261pt text width (line 1: 242.6pt,
      // line 2: 260.9pt), so a 270pt box reproduces the same line breaks.
      align(center, box(width: 270pt, align(center, data.at("running_header", default: ""))))
    }
  },
  // Page number in footer — 12pt, centered, matching NIEHS PDF (y=753.4pt)
  // Also automatically artifacted by Typst for PDF/UA
  footer: context {
    set text(size: 12pt, font: "Liberation Serif")
    align(center, counter(page).display())
  },
)


// --- Body text ---
// 12pt Times New Roman (Liberation Serif is metrically identical).
// 1.5x line spacing matches the NIEHS report.
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

#let niehs-table(headers, rows, caption: none, numeric-cols: (), footnotes: ()) = {
  // Caption above the table — bold, left-aligned, 11pt
  if caption != none {
    block(spacing: 4pt, text(weight: "bold", size: 11pt, caption))
  }

  let ncols = headers.len()

  // Typst automatically tags this as Table with TR/TH/TD
  set text(size: 10pt)
  table(
    columns: ncols,
    align: (col, _) => {
      if col in numeric-cols { right } else { left }
    },
    stroke: none,
    inset: (x: 6pt, y: 3pt),

    // Header row — Typst tags these cells as TH when inside table.header
    table.header(
      table.hline(stroke: 1.5pt + black),
      ..headers.map(h => table.cell(text(weight: "bold", h))),
      table.hline(stroke: 0.5pt + black),
    ),

    // Data rows
    ..rows.flatten(),

    // Bottom border (thick)
    table.footer(
      table.hline(stroke: 1.5pt + black),
    ),
  )

  // Footnotes below the table — 9pt, tight leading
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

  set text(size: 10pt)
  table(
    columns: ncols,
    align: (col, _) => {
      if col in numeric-cols { right } else { left }
    },
    stroke: none,
    inset: (x: 6pt, y: 3pt),

    table.header(
      table.hline(stroke: 1.5pt + black),
      ..headers.map(h => table.cell(text(weight: "bold", h))),
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
      table.hline(stroke: 1.5pt + black),
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
// DOCUMENT BODY — assembled from the JSON data
// =====================================================================


// --- Title block ---
// Matches the NIEHS inner title page (page 2):
//   20pt bold, centered, full study title including chemical name,
//   CASRN in parentheses, strain, and species.
#align(center)[
  #block(below: 18pt, above: 0pt)[
    #set text(font: "Liberation Sans", size: 20pt, weight: "bold")

    // Full title: "In Vivo Repeat Dose Biological Potency Study of
    //              <Chemical> (CASRN <casrn>) in Sprague Dawley Rats"
    #let chem = data.at("chemical_name", default: "Test Article")
    #let casrn = data.at("casrn", default: "")
    #let casrn-part = if casrn != "" { " (CASRN " + casrn + ")" } else { "" }

    In Vivo Repeat Dose Biological Potency Study of
    #chem#casrn-part
    in Sprague Dawley Rats

    // Report number and date, matching NIEHS format
    #v(12pt)
    #set text(size: 12pt, weight: "regular")
    #data.at("author", default: "5dToxReport")
  ]
]


// --- Background ---
// Each major section (H1) starts on a new page, matching the NIEHS PDF
// where Background (pg13), M&M (pg14), Results (pg23), and Summary (pg47)
// all begin at the top of a fresh page.
#if data.at("background", default: none) != none {
  pagebreak()
  let bg = data.background
  heading(level: 1, "Background")
  for para in bg.at("paragraphs", default: ()) {
    [#para]
    parbreak()
  }

  // References
  let refs = bg.at("references", default: ())
  if refs.len() > 0 {
    heading(level: 2, "References")
    set text(size: 10pt)
    for (i, ref) in refs.enumerate() {
      [#(i + 1). #ref]
      parbreak()
    }
  }
}


// --- Materials and Methods ---
#if data.at("methods", default: none) != none {
  pagebreak()
  let methods = data.methods
  heading(level: 1, "Materials and Methods")

  // Structured sections
  for sec in methods.at("sections", default: ()) {
    let lvl = sec.at("level", default: 3)
    if lvl <= 3 {
      heading(level: 2, sec.at("heading", default: ""))
    } else {
      heading(level: 3, sec.at("heading", default: ""))
    }

    for para in sec.at("paragraphs", default: ()) {
      [#para]
      parbreak()
    }

    // Inline table (e.g., Table 1 — Study Design)
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

  // Legacy flat paragraphs fallback
  if methods.at("sections", default: ()).len() == 0 {
    for para in methods.at("paragraphs", default: ()) {
      [#para]
      parbreak()
    }
  }
}


// --- Results ---
// Compute whether we have any results content.  This variable is
// used below to conditionally emit the "Results" H1 heading.
#let has-results = (
  data.at("apical_sections", default: ()).len() > 0 or
  data.at("bmd_summary", default: none) != none or
  data.at("genomics_sections", default: ()).len() > 0
)

#if has-results {
  pagebreak()
  heading(level: 1, "Results")
}

// --- Apical endpoint sections ---
// NIEHS pattern: narrative on portrait page, then each wide dose-response
// table gets its own landscape page.  Tables with many dose columns (≥5)
// are too wide for portrait orientation.  The NIEHS PDF (NBK589955) uses
// landscape for Tables 2-6 (body weights, liver weights, clinical chem,
// hematology, hormones) and portrait for narrower tables (Table 7 plasma
// concentrations, Table 8 BMD summary).
//
// We reproduce this by:
//   1. Emitting narrative paragraphs in portrait mode
//   2. For each sex's dose-response table: pagebreak → landscape → table → pagebreak → portrait
//   3. The landscape threshold is ≥5 dose groups (matching NIEHS behavior)
#for sec in data.at("apical_sections", default: ()) {
  heading(level: 2, sec.at("title", default: "Apical Endpoints"))

  // Narrative paragraphs — always portrait
  for para in sec.at("narrative", default: ()) {
    [#para]
    parbreak()
  }

  // Data tables — one per sex, potentially on landscape pages
  let dose-unit = sec.at("dose_unit", default: "mg/kg")
  for sex in ("Male", "Female") {
    let rows-data = sec.at("table_data", default: (:)).at(sex, default: ())
    if rows-data.len() > 0 {
      let caption-text = sec.at("caption", default: "")
        .replace("{sex}", sex)
        .replace("{compound}", sec.at("compound", default: "Test Compound"))

      let doses = rows-data.at(0).at("doses", default: ())

      // Build header array
      let headers = ("Endpoint",)
      for dose in doses {
        let label = if dose == 0 {
          "0 " + dose-unit
        } else {
          str(dose) + " " + dose-unit
        }
        headers += (label,)
      }
      headers += (
        "BMD₁Std (" + dose-unit + ")",
        "BMDL₁Std (" + dose-unit + ")",
      )

      let num-cols = range(1, headers.len())

      // Build data rows
      let tbl-rows = ()

      // "n" row — sample sizes per dose group
      let n-row = ("n",)
      for dose in doses {
        let max-n = 0
        for r in rows-data {
          let nn = r.at("n", default: (:)).at(str(dose), default: 0)
          if nn > max-n { max-n = nn }
        }
        n-row += (str(max-n),)
      }
      n-row += ("NA", "NA")
      tbl-rows += (n-row,)

      // Endpoint data rows
      for r in rows-data {
        let row = (r.at("label", default: ""),)
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

      // Wide tables (≥5 dose groups) get their own landscape page,
      // matching the NIEHS pattern where Tables 2-6 are landscape.
      // Narrow tables stay inline on the current portrait page.
      //
      // `set page(flipped: true/false)` implicitly triggers a page break
      // in Typst, so no explicit pagebreak() is needed.  Using both would
      // create an unwanted blank page.
      if doses.len() >= 5 {
        // --- Switch to landscape for this table ---
        set page(flipped: true)
        niehs-table(
          headers,
          tbl-rows,
          caption: if caption-text != "" { caption-text },
          numeric-cols: num-cols,
        )
        // --- Return to portrait after the table ---
        // The next `set page(flipped: false)` (or any subsequent content
        // that uses portrait) will trigger the page break back.
        set page(flipped: false)
      } else {
        // Narrow table — stays inline on portrait page
        niehs-table(
          headers,
          tbl-rows,
          caption: if caption-text != "" { caption-text },
          numeric-cols: num-cols,
        )
        v(12pt)
      }
    }
  }
}


// --- BMD Summary ---
// In the NIEHS PDF, the BMD summary (Table 8) appears on page 31 after
// the Internal Dose Assessment text.  It's a 6-column portrait table.
// We place it on its own page to match the NIEHS pattern of keeping
// each major results subsection visually separated.
#if data.at("bmd_summary", default: none) != none {
  let bmd = data.bmd_summary
  let endpoints = bmd.at("endpoints", default: ())
  if endpoints.len() > 0 {
    pagebreak()
    heading(level: 2, "Apical Endpoint BMD Summary")

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
      caption: "Apical Endpoint BMD Summary",
      numeric-cols: (1, 2, 3, 4),
    )
  }
}


// --- Genomics Results ---
// In the NIEHS PDF, "Gene Set Benchmark Dose Analysis" (H2) starts on
// page 31 after the BMD summary table.  "Gene Benchmark Dose Analysis"
// (H2) starts on a new page (page 38).  Each organ's gene set table
// (Tables 9-10) and gene table (Tables 11-12) flow continuously in
// portrait orientation.
#let genomics = data.at("genomics_sections", default: ())
#if genomics.len() > 0 {
  pagebreak()
  heading(level: 2, "Transcriptomic BMD Analysis")

  for gs-sec in genomics {
    let organ = gs-sec.at("organ", default: "")
    let sex = gs-sec.at("sex", default: "")
    let label = upper(organ.first()) + organ.slice(1) + " — " + upper(sex.first()) + sex.slice(1)

    heading(level: 3, label)

    // Gene sets table
    let gene-sets = gs-sec.at("gene_sets", default: ())
    if gene-sets.len() > 0 {
      let gs-rows = gene-sets.map(gs => (
        gs.at("go_term", default: ""),
        gs.at("go_id", default: ""),
        fmt-val3(gs.at("bmd_median", default: none)),
        fmt-val3(gs.at("bmdl_median", default: none)),
        str(gs.at("n_genes", default: "")),
        gs.at("direction", default: ""),
      ))

      niehs-table(
        ("GO Term", "GO ID", "BMD Median", "BMDL Median", "# Genes", "Direction"),
        gs-rows,
        caption: "Gene Set BMD Analysis — " + label,
        numeric-cols: (2, 3, 4),
      )
      v(8pt)
    }

    // Top genes table
    let top-genes = gs-sec.at("top_genes", default: ())
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
        caption: "Gene BMD Analysis — " + label,
        numeric-cols: (1, 2, 3),
      )
      v(8pt)
    }
  }
}


// --- Summary ---
#if data.at("summary", default: none) != none {
  pagebreak()
  heading(level: 1, "Summary")
  for para in data.summary.at("paragraphs", default: ()) {
    [#para]
    parbreak()
  }
}

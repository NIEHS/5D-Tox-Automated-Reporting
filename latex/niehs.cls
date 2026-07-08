% =====================================================================
% niehs.cls — NIEHS biological potency report document class.
%
% Companion to latex_generator.py, which emits report.tex against this
% class.  This file owns the visual presentation of the report:
% page geometry, fonts, table chrome, footnote styling.
%
% Why a custom class
% ------------------
% Per the Option B grilling session (2026-05-19), the LaTeX path uses a
% hybrid styling model: the generated report.tex uses vanilla
% \section / \subsection for prose so that Overleaf authors see familiar
% LaTeX, while this class owns the specialized environments (tables,
% footnote blocks, future genomics chart layouts) that have NIEHS-specific
% conventions worth abstracting.
%
% Tracer-bullet scope
% -------------------
% Minimum needed to compile a narrative-only report end-to-end:
%   - article-based class with US letter geometry
%   - threeparttable, graphicx, hyperref, amsmath, lmodern loaded
%   - placeholder niehstable environment (just \begin{table}\centering ...)
%
% Future sessions will flesh out:
%   - the real niehstable env with caption + threeparttable wrap
%   - NIEHS-matching heading fonts (Liberation Sans Bold equivalent)
%   - page numbering switch (roman in front matter, arabic in body)
%   - landscape layout for wide dose-response tables
%   - per-table lettered footnote styling
% =====================================================================

\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{niehs}[2026/05/19 NIEHS biological potency report]

% --- Base class ----------------------------------------------------------
% article gives us \section / \subsection / \subsubsection at H1/H2/H3
% with article-style numbering ("1", "1.1", "1.1.1"), which we keep for
% v1.  NIEHS Report 10 uses unnumbered sections; that's a v2 refinement.
\LoadClass[11pt]{article}

% --- Page geometry -------------------------------------------------------
% US Letter, 1-inch margins.  Matches NIEHS Report 10 (NBK589955) page
% block: 6.5in text width, 9in text height, fits expected dose-response
% table widths at 10pt.
\RequirePackage{geometry}
\geometry{
  letterpaper,
  margin=1in,
  % Reserve room in the top margin for the running header (configured in
  % the fancyhdr block below).  headheight=30pt fits a two-line wrapped
  % title; headsep is the gap down to the body text.  Setting these here,
  % rather than via a bare \setlength after fancyhdr, lets geometry account
  % for them in the vertical layout and silences fancyhdr's "headheight too
  % small" warning.
  headheight=30pt,
  headsep=14pt,
}

% --- Tables --------------------------------------------------------------
% threeparttable provides the table + caption + lettered-footnotes idiom
% we chose in decision #5.  It groups the tabular with its tnotes so the
% footnotes stay attached even if the table is wrapped in a float.
\RequirePackage{threeparttable}

% Booktabs for \toprule / \midrule / \bottomrule — cleaner than \hline
% and conventionally what scientific tables use.  Matches the visual
% weight of the NIEHS reference report.
\RequirePackage{booktabs}

% longtable for multi-page tables (e.g. the Appendix B animal roster, ~300
% rows): a plain tabular / table float can't break across pages, but a
% longtable does and repeats its header on each page.  booktabs rules work
% inside it.
\RequirePackage{longtable}

% --- Figures -------------------------------------------------------------
% graphicx for \includegraphics{figures/<chart>.png}.  Each genomics chart
% ships as a PNG (decoded from the session chart cache) in the figures/
% subdirectory of the Overleaf export bundle.
\RequirePackage{graphicx}

% --- Branded cover page --------------------------------------------------
% The cover (page 1) and inner title page (page 2) are rendered by the
% latex_generator _render_cover / _render_title_page handlers, not by
% \maketitle.  The cover is a full-bleed tikz overlay (the LaTeX analog of
% the approved Typst layout in report.typ): a sage-green field with the
% cover-bg.jpg hexagon pattern, a white institution band, a bicolor accent
% bar, and the title/number/date.  tikz gives absolute page-anchored
% placement; xcolor defines the palette (hexes extracted from NIEHS Report
% 10, matching report.typ's cover-* colors).  \newgeometry (from geometry,
% already loaded) lets the cover drop the 1in margins for full bleed.
\RequirePackage{tikz}
\RequirePackage{xcolor}
% The cover's brand palette is NOT defined here — the cover handler
% (latex_generator._render_cover) emits \definecolor{cover<key>} from the
% subtype's layout (cover_layouts) so a new report cover ships its own colors
% without a class edit.

% The Table of Contents node (\tableofcontents) self-heads with LaTeX's
% \contentsname, which the article class defaults to "Contents".  NIEHS
% Report 10 (and our document tree's `toc` node title) call it "Table of
% Contents", so rename it here.
\renewcommand{\contentsname}{Table of Contents}

% --- Scale-to-fit wide tables --------------------------------------------
% adjustbox gives us \begin{adjustbox}{max width=\linewidth}...\end{adjustbox}
% which scales its contents DOWN to fit the available text width but leaves
% content that already fits untouched (so portrait tables that fit are not
% shrunk).  We use it in the niehstable environment below to make wide
% dose-response tables fit their page.  CRUCIAL: \linewidth (unlike
% \textwidth) is widened by pdflscape inside a landscape page (~6.5in
% portrait -> ~9in landscape), so the SAME "max width=\linewidth" target
% automatically uses the full landscape width on rotated pages and the
% narrower portrait width otherwise.  adjustbox is loaded (not built by us)
% because the earlier hand-rolled \resizebox attempt scaled the tabular
% INSIDE threeparttable, which breaks threeparttable's width measurement
% ("Missing \endgroup"); the fix is to scale the FINISHED threeparttable
% from the OUTSIDE, with the \caption kept out of the scaled box.
\RequirePackage{adjustbox}

% --- Caption labels ------------------------------------------------------
% The Python generator sources every table's number positionally from the
% document tree (invariant: table_number is auto-assigned by tree walk) and
% bakes it INTO the caption text as "Table N. ...".  LaTeX's float counter
% would ALSO prepend its own "Table M:" label, producing a doubled
% "Table 1: Table 2. ..." — and worse, M drifts from N because the float
% counter only counts RENDERED tables while our N counts tree position
% (so an unrendered table, e.g. the reference's Table 1 Sample Counts, is
% absent from LaTeX's count but present in ours).  Our tree number is the
% authoritative one, so we suppress LaTeX's auto label for tables entirely
% and let the caption text carry the number.  \listoftables still lists
% every table (it reads the \caption text, which keeps "Table N."), and
% \label/\ref still resolve via the \label{tab:<id>} inside niehstable.
% Scoped to [table] so figures (if any gain \caption later) are unaffected.
\RequirePackage{caption}
\captionsetup[table]{labelformat=empty,labelsep=none}

% --- Landscape pages -----------------------------------------------------
% pdflscape provides the `landscape` environment for individual landscape
% pages (wide dose-response tables, charts, figures) inside an otherwise
% portrait report.  Unlike plain `lscape`, pdflscape also sets the PDF
% page-rotation flag, so Overleaf's compiled PDF actually displays the
% page in landscape.  latex_generator wraps a node in \begin{landscape}
% ... \end{landscape} when the user toggles it (see the orientations map).
\RequirePackage{pdflscape}

% --- Math ----------------------------------------------------------------
% amsmath because the abstract sometimes contains subscripted dose units
% (BMDL_{1Std}, etc.).  Even if the prose itself doesn't need math, the
% scaffold abstract uses \textsubscript which behaves better with amsmath
% loaded.
\RequirePackage{amsmath}

% --- Fonts ---------------------------------------------------------------
% lmodern is a free, well-hinted modern roman font that gives pdflatex
% scalable output.  Computer Modern (the default) renders poorly on
% screen and is a common Overleaf complaint.  When we want a closer
% match to the NIEHS Liberation Serif look, swap in a Times-equivalent
% (mathptmx / newtxtext) — deferred to a typography session.
\RequirePackage{lmodern}

% --- Running header (fancyhdr) ------------------------------------------
% NIEHS Report 10 carries a running header — the full report title,
% centered at the top of every page from the Foreword onward.  The cover
% and title pages carry none: \maketitle issues \thispagestyle{plain}, and
% fancyhdr leaves "plain" header-less, so the title page is automatically
% skipped and the header begins on the page after it.
%
% This mirrors the in-app HTML preview (which paginates with the same
% running header via Paged.js), so both of our output surfaces — the .tex
% Overleaf export and the HTML preview — match the reference.
\RequirePackage{fancyhdr}
% The title text is injected per-report by latex_generator.py via
% \renewcommand{\niehsrunningheader}{...} in the preamble.  The class
% defines it empty so a fragment compile (which never sets it) still
% compiles — it just shows a blank header.
\newcommand{\niehsrunningheader}{}
\pagestyle{fancy}
\fancyhf{}% clear every header and footer field
% Centered running header.  Wrapped in a full-width \parbox with \centering
% so a long title (NIEHS titles run ~90 characters) breaks across two lines
% and stays centered, like the reference.  A bare \fancyhead[C]{...} would
% set it on one line and overflow into both margins.
\fancyhead[C]{\parbox[b]{\textwidth}{\centering\small\niehsrunningheader}}
% Page number centered in the footer (article's default position).  The
% roman-front-matter / arabic-body numbering split is a separate task.
\fancyfoot[C]{\thepage}
% NIEHS Report 10 has no horizontal rule beneath the header.
\renewcommand{\headrulewidth}{0pt}

% --- Links ---------------------------------------------------------------
% hyperref for blue clickable links (NIEHS Report 10 uses blue links for
% URLs in the references section).  Loaded last per LaTeX convention so
% it can hook into the other packages' \section / \caption commands.
\RequirePackage[
  colorlinks=true,
  linkcolor=blue,
  urlcolor=blue,
  citecolor=blue,
]{hyperref}

% --- Breakable URLs ------------------------------------------------------
% xurl lets \url{...} break after ANY character.  Reference URLs (e.g. long
% PubChem / ATSDR / CDC links) are otherwise one unbreakable token whose '/'
% and '.' are not TeX line-break points, so they run past the right margin
% (overfull \hbox).  latex_generator wraps URLs found in prose in \url{} (see
% _splice_urls), and xurl makes those wrap cleanly while staying blue +
% clickable via hyperref.  Loaded AFTER hyperref, as xurl requires.
\RequirePackage{xurl}

% --- niehstable environment ---------------------------------------------
% Signature: \begin{niehstable}{<table-id>}{<caption text>} ... \end{...}
%
%   #1 = table id (e.g., "tbl-body-weight").  Used as \label{tab:<id>}
%        so \ref / \autoref can point at this table from prose.
%   #2 = caption text.  Already includes the "Table N." prefix from the
%        Python generator (which sources N from the document tree's
%        auto-assigned table_number).
%
% Why threeparttable
% ------------------
% NIEHS tables carry per-table lettered footnotes ("Data are shown as
% means ± SD.", "Statistical method: ...").  Standard \footnote sends
% notes to the page foot, which scatters them.  threeparttable groups
% the tabular and its tablenotes into one unit so footnotes stay glued
% to their table even when the float migrates pages.
%
% Why \begin{table} float
% -----------------------
% Wrapping in a \begin{table} float makes each table eligible for
% \listoftables (the front-matter tables list) and lets LaTeX float
% wide tables to the next available spot rather than breaking them
% mid-page.  [htbp] is the standard "try here, then top, then bottom,
% then a float page" placement order.
%
% Scale-to-fit (wide tables)
% --------------------------
% The \caption is emitted FIRST, outside the scaled box, so the caption
% always renders at the normal body font and full text width — only the
% table body (the tabular + its tablenotes inside threeparttable) is scaled
% to fit.  The whole threeparttable is wrapped in adjustbox "max width=
% \linewidth": tables wider than the text block are shrunk to fit; tables
% that already fit pass through at natural size.  This is why a too-wide
% dose-response table on a landscape page now fits (scaled to ~9in) instead
% of running off the edge, while ordinary portrait tables look unchanged.
\newenvironment{niehstable}[2]{%
  \begin{table}[htbp]%
    \centering%
    \caption{#2}\label{tab:#1}%
    \begin{adjustbox}{max width=\linewidth}%
    \begin{threeparttable}%
}{%
    \end{threeparttable}%
    \end{adjustbox}%
  \end{table}%
}

\endinput

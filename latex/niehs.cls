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

% --- Figures -------------------------------------------------------------
% graphicx for \includegraphics{figures/<chart>.pdf}.  Decision #7: each
% genomics chart ships as a PDF in the figures/ subdirectory of the
% Overleaf export bundle.
\RequirePackage{graphicx}

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
\newenvironment{niehstable}[2]{%
  \begin{table}[htbp]%
    \centering%
    \begin{threeparttable}%
      \caption{#2}\label{tab:#1}%
}{%
    \end{threeparttable}%
  \end{table}%
}

\endinput

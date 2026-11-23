"""
narrative/agency_sources.py — the documents a human author of a Background
consults, found from the chemical's public identifiers.

The authors of the published reports wrote their Backgrounds from a known
routine (read from the twelve books, 2026-11-23): the agency assessment where
one exists (ATSDR's toxicological profile, EPA's IRIS summary, the IARC
monograph, an NTP report, OECD's assessment), each limit from the body that
sets it (OSHA's Table Z-1, NIOSH, ACGIH, EPA's drinking water regulations),
the public chemical databases (PubChem, EPA's CompTox dashboard), and a few
papers from PubMed.  Each function here finds one of those documents for a
chemical, reads it (``narrative.source_fetch``) and returns a ``Source``:

  * ``record``: the document as a reference entry would cite it (the issuing
    body as author, its title, where and when it was published, the address
    read and the day it was read) — ``narrative.sources`` record fields;
  * ``text``: what the document says, for the model to write from;
  * ``facts``: single values the gatherer's structured fields carry.

How a document is found is the same for every chemical: by CAS number, by the
identifiers the chemical's PubChem record gives, or by name.  Nothing here
names a chemical.  A document that does not exist for a chemical gives None;
a site that could not be read is named in ``Finder.unreachable``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from urllib.parse import quote, urljoin

from narrative.source_fetch import Fetched, between, fetch, html_text, pdf_text, today

logger = logging.getLogger(__name__)

PUGVIEW = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/{cid}/JSON"
CTX = "https://comptox.epa.gov/ctx-api"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"

HHS = "U.S. Department of Health and Human Services"
EPA = "U.S. Environmental Protection Agency"

_CAS = re.compile(r"\b\d{2,7}-\d\d-\d\b")
# The dashboard gathers values from many lists; the ones a Background states
# are those of the bodies that assess a chemical themselves.
_ASSESSMENTS = re.compile(r"\b(IRIS|ATSDR|PPRTV|HEAST|NTP|WHO|EFSA|ECHA|Health Canada|OEHHA|OPP)\b")


@dataclass
class Source:
    key: str                               # which document of the routine
    record: dict                           # the reference entry's fields
    text: str = ""                         # what it says, for the model
    facts: dict = field(default_factory=dict)


def _record(kind: str, author: str, title: str, publisher: str, year, got: Fetched | None,
            url: str, source_type: str) -> dict:
    """A document as its reference entry: issuing body, title, publisher, year,
    the day it was read and its address."""
    return {
        "kind": kind,
        "authors": [author],
        "title": title.strip().rstrip("."),
        "container": publisher,
        "year": year,
        "accessed": got.accessed if got else None,
        "url": url,
        "source_type": source_type,
    }


class Finder:
    """One chemical's documents.  ``identity``: narrative.chem_resolver
    ChemicalIdentity.  ``report``: progress, a line per document."""

    def __init__(self, identity, report=None):
        self.identity = identity
        self.report = report or (lambda message: None)
        self.notes: list[str] = []
        self.unreachable: list[str] = []
        self._pubchem: dict | None = None
        self._pubchem_got: Fetched | None = None

    # -- names -------------------------------------------------------------
    def names(self) -> list[str]:
        """The names the chemical goes by, the report's own first."""
        seen: list[str] = []
        for name in [self.identity.name, self.identity.iupac_name, *(self.identity.synonyms or [])]:
            name = (name or "").strip()
            if name and not _CAS.fullmatch(name) and name.lower() not in [s.lower() for s in seen]:
                seen.append(name)
        return seen

    def _is_named(self, text: str) -> bool:
        low = " ".join(text.lower().split())
        return any(low == n.lower() for n in self.names())

    # -- PubChem's record -------------------------------------------------
    def pubchem(self) -> dict:
        """PubChem's whole record of the compound ({} when it has none or
        could not be read)."""
        if self._pubchem is None:
            self._pubchem = {}
            cid = self.identity.pubchem_cid
            if cid:
                got = fetch(PUGVIEW.format(cid=cid), browser=False)
                if got is None:
                    self.unreachable.append("PubChem")
                else:
                    try:
                        self._pubchem = json.loads(got.text).get("Record") or {}
                        self._pubchem_got = got
                    except ValueError:
                        self.unreachable.append("PubChem")
        return self._pubchem

    def _sections(self, node=None, path=()):
        node = self.pubchem() if node is None else node
        for section in node.get("Section") or []:
            here = path + (section.get("TOCHeading", ""),)
            yield here, section
            yield from self._sections(section, here)

    def pubchem_entries(self, heading: str) -> list[dict]:
        """The entries under a heading of the PubChem record: {name, text,
        links, source, source_url, reference}."""
        refs = {r.get("ReferenceNumber"): r for r in self.pubchem().get("Reference") or []}
        out = []
        for path, section in self._sections():
            if path[-1].lower() != heading.lower():
                continue
            for info in section.get("Information") or []:
                value = info.get("Value") or {}
                parts = value.get("StringWithMarkup") or []
                text = " ".join(p.get("String", "") for p in parts).strip()
                if not text and value.get("Number"):
                    text = " ".join(str(n) for n in value["Number"]) + " " + (value.get("Unit") or "")
                ref = refs.get(info.get("ReferenceNumber")) or {}
                out.append({
                    "name": info.get("Name") or "",
                    "text": text.strip(),
                    "links": [m["URL"] for p in parts for m in p.get("Markup") or [] if m.get("URL")],
                    "source": ref.get("SourceName") or "",
                    "source_url": ref.get("URL") or "",
                    "reference": " ".join(info.get("Reference") or []),
                })
        return out

    def pubchem_source_url(self, source_name: str, pattern: str = "") -> str:
        """The address PubChem gives for one of its sources' pages on this
        compound."""
        for ref in self.pubchem().get("Reference") or []:
            url = ref.get("URL") or ""
            if source_name.lower() in (ref.get("SourceName") or "").lower() and re.search(pattern, url):
                return url
        return ""

    # -- the documents -----------------------------------------------------
    def pubchem_summary(self) -> Source | None:
        record = self.pubchem()
        if not record:
            return None
        cid = self.identity.pubchem_cid
        title = record.get("RecordTitle") or self.identity.name
        return Source("pubchem", _record(
            "website", "National Center for Biotechnology Information (NCBI)",
            f"PubChem compound summary for CID {cid}, {title}",
            f"Bethesda, MD: {HHS}, National Institutes of Health, National Library of Medicine",
            self._pubchem_got.year, self._pubchem_got,
            f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}", "database"))

    def atsdr_profile(self) -> Source | None:
        """ATSDR's toxicological profile: its list of minimal risk levels
        gives the substance page by CAS number, that page the profile."""
        cas = self.identity.casrn
        if not cas:
            return None
        listing = fetch("https://wwwn.cdc.gov/TSP/MRLS/mrlslisting.aspx")
        if listing is None:
            self.unreachable.append("ATSDR")
            return None
        page = listing.text
        profile_url = ""
        at = page.find(f">{cas}<")
        if at < 0:
            at = page.find(cas)
        if at >= 0:
            links = re.findall(r'href="([^"]*ToxSubstance\.aspx\?toxid=\d+)"', page[:at])
            if links:
                substance = fetch(urljoin(listing.url, links[-1].replace("&amp;", "&")))
                if substance is None:
                    self.unreachable.append("ATSDR")
                    return None
                m = re.search(r'href="([^"]*ToxProfiles\.aspx\?id=\d+&(?:amp;)?tid=\d+)"', substance.text)
                if m:
                    profile_url = urljoin(substance.url, m.group(1).replace("&amp;", "&"))
        if not profile_url:
            self.notes.append(f"ATSDR lists no toxicological profile for CAS {cas}")
            return None
        landing = fetch(profile_url)
        if landing is None:
            self.unreachable.append("ATSDR")
            return None
        words = html_text(landing.text)
        cited = re.search(r"\(ATSDR\)\.\s*((?:19|20)\d\d)\.\s*(Toxicological profile for [^.]+)\.", " ".join(words.split()))
        title = cited.group(2) if cited else (between(words, r"Toxicological Profile for", r"\n", 200) or "Toxicological profile")
        year = int(cited.group(1)) if cited else None
        chapters = {re.sub(r"pdf icon.*", "", re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", label))).strip().lower():
                    urljoin(landing.url, href)
                    for href, label in re.findall(r'<a[^>]+href="([^"]+\.pdf)"[^>]*>(.*?)</a>', landing.text, re.S | re.I)}
        whole = chapters.get("complete profile") or profile_url
        parts: list[str] = []
        relevance = next((u for label, u in chapters.items() if "relevance to public health" in label), "")
        if relevance and (got := fetch(relevance)) is not None:
            text = pdf_text(got.content)
            cut = re.search(r"\n\s*\d\.\d\s+MINIMAL RISK LEVELS", text)
            parts.append("RELEVANCE TO PUBLIC HEALTH\n" + (text[:cut.start()] if cut else text)[:24000])
        for label, url in chapters.items():
            if not re.search(r"health effects|toxicokinetics", label):
                continue
            got = fetch(url)
            if got is None:
                continue
            text = pdf_text(got.content)
            kinetics = between(text, r"\n\s*\d\.\d\s+TOXICOKINETICS[^\n]*\n", r"\n\s*\d\.\d\.\d\s+Absorption", 4000)
            mechanisms = between(text, r"\n\s*\d\.\d\s+MECHANISMS OF ACTION[^\n]*\n",
                                 r"\n\s*\d\.\d\.\d\s+Animal-to-Human|\n\s*\d\.\d\s+[A-Z]{4,}", 11000)
            if kinetics:
                parts.append(kinetics)
            if mechanisms:
                parts.append(mechanisms)
            if kinetics or mechanisms:
                break
        return Source("atsdr", _record(
            "report", "Agency for Toxic Substances and Disease Registry (ATSDR)", title,
            f"Atlanta, GA: {HHS}, Public Health Service, Agency for Toxic Substances and Disease Registry",
            year, landing, whole, "government_report"), "\n\n".join(parts))

    def iris(self) -> Source | None:
        """EPA's IRIS assessment: PubChem's record gives its page."""
        url = self.pubchem_source_url("Integrated Risk Information System", r"substance_nmbr")
        if not url:
            if "PubChem" not in self.unreachable:
                self.notes.append("PubChem gives no EPA IRIS assessment for this chemical")
            return None
        landing = fetch(url)
        if landing is None:
            self.unreachable.append("IRIS")
            return None
        words = html_text(landing.text)
        text = between(words, r"Noncancer Assessment", r"Other EPA Information", 5000) or words[:5000]
        years = [int(y) for y in re.findall(r"Last Updated:\s*\d\d/\d\d/((?:19|20)\d\d)", words)]
        m = re.search(r'href="([^"]+_summary\.pdf)"', landing.text)
        if m and (pdf := fetch(urljoin("https://iris.epa.gov/", m.group(1)))) is not None:
            text += "\n\nIRIS CHEMICAL ASSESSMENT SUMMARY\n" + pdf_text(pdf.content)[:14000]
        facts = {}
        rfd = re.search(r"RfD \(mg/kg-day\).*?\n\s*\|?\s*([\d.]+ ?x ?10 ?-?\d+|[\d.]+)", words, re.S)
        if rfd:
            facts["iris_rfd"] = rfd.group(1) + " mg/kg-day (EPA IRIS)"
        flat = " ".join(words.split())
        noael = re.search(r"\b(NOAEL|LOAEL|BMDL\w*)\s*:\s*([\d.]+\s*x\s*10\s*-?\d+|[\d.]+)\s*mg/kg-day\s*\|?\s*(\d+)?", flat)
        if noael:
            facts["iris_noael"] = f"{noael.group(1)} {noael.group(2)} mg/kg-day (EPA IRIS)"
            if noael.group(3):
                facts["iris_uf"] = f"{noael.group(3)} (EPA IRIS)"
        rfc = re.search(r"Reference Concentration for Inhalation Exposure \(RfC\)(?: \(PDF\)[^|]*?K\))?\s*(.{0,160})", flat)
        if rfc:
            facts["iris_rfc"] = ("Not assessed under the IRIS Program" if "Not assessed" in rfc.group(1)
                                 else rfc.group(1).strip()[:160])
        woe = re.search(r"WOE Characterization.*?\|\s*([A-E]\d? \([^)]+\))", flat)
        if woe:
            facts["cancer_class"] = f"EPA {woe.group(1)}"
        return Source("iris", _record(
            "report", f"{EPA} (USEPA)",
            f"Integrated Risk Information System (IRIS) chemical assessment summary: "
            f"{self.identity.name}; CASRN {self.identity.casrn}",
            f"Washington, DC: {EPA}, National Center for Environmental Assessment",
            max(years) if years else None, landing, url, "government_report"), text, facts)

    def iarc(self) -> Source | None:
        """The IARC monograph that evaluated the chemical: PubChem's record
        carries IARC's own entry (the group, the volume and its address)."""
        entries = [e for e in self.pubchem_entries("Carcinogen Classification")
                   if "International Agency for Research on Cancer" in e["source"]]
        if not entries:
            return None
        by = {e["name"]: e for e in entries}
        group = (by.get("IARC Carcinogenic Classes") or {}).get("text", "")
        volumes = by.get("IARC Monographs") or {}
        links = [u.replace("http://", "https://") for u in volumes.get("links") or []]
        if not group or not links:
            return None
        url = links[-1]
        page = fetch(url)
        if page is None:
            self.unreachable.append("IARC")
            return None
        m = re.search(r'<meta[^>]+name="citation_title"[^>]+content="([^"]+)"', page.text)
        title = m.group(1) if m else ""
        last = re.findall(r"Volume (\w+):? ?\(((?:19|20)\d\d)\)", volumes.get("text", ""))
        volume, year = (last[-1][0], int(last[-1][1])) if last else ("", None)
        if not title:
            return None
        record = _record("book", "International Agency for Research on Cancer (IARC)",
                         title + (f" (IARC Monographs; vol. {volume})" if volume else ""),
                         "Lyon, France: International Agency for Research on Cancer",
                         year, page, url, "monograph")
        agent = (by.get("IARC Carcinogenic Agent") or {}).get("text", "")
        text = (f"IARC evaluation of {agent}: {group}. Evaluated in: {volumes.get('text', '')}"
                + (f" (evaluation year {by['Evaluation Year']['text']})" if by.get("Evaluation Year") else ""))
        return Source("iarc", record, text, {"cancer_class": f"IARC {group}"})

    def ntp_reports(self) -> list[Source]:
        """NTP's technical reports on the chemical: PubChem's record carries
        NTP's own list (number, title, year, conclusions, address)."""
        entries = [e for e in self.pubchem_entries("Carcinogen Classification")
                   if e["source"] == "NTP Technical Reports"]
        out: list[Source] = []
        groups: list[list[dict]] = []
        for e in entries:
            if e["name"] == "NTP Technical Report" or not groups:
                groups.append([])
            groups[-1].append(e)
        for group in groups:
            head = next((e for e in group if e["name"] == "NTP Technical Report"), None)
            if head is None:
                continue
            m = re.match(r"\s*(TR-?\s*(\d+)):\s*(.*?)\s*\(\s*((?:19|20)\d\d)\s*\)\s*$", head["text"])
            if not m:
                continue
            number, title, year = m.group(2), m.group(3).strip(), int(m.group(4))
            url = next((u for u in head["links"] if "ntp.niehs.nih.gov" in u), "")
            page = fetch(url) if url else None
            if url and page is None:
                self.unreachable.append("NTP")
            lines = [f"{e['name']}: {e['text']}" for e in group if e["name"] != "Substance"]
            text = "\n".join(lines)
            if page is not None:
                words = html_text(page.text)
                at = words.rfind("\nAbstract\n")
                abstract = re.split(r"\n(?:NTP is located|Studies\n|Contact|Stay Connected|Links\n)", words[at:at + 7000])[0] if at >= 0 else ""
                if len(abstract) > 400:
                    text += "\n\n" + abstract.strip()
            out.append(Source("ntp", {
                **_record("report", "National Toxicology Program (NTP)",
                          "NTP technical report on the " + title,
                          f"Research Triangle Park, NC: {HHS}, Public Health Service, "
                          "National Institutes of Health, National Toxicology Program",
                          year, page, url or "https://ntp.niehs.nih.gov/data/tr", "government_report"),
                "number": f"NTP Technical Report No. {number}"}, text))
        return out

    def osha_table_z(self) -> Source | None:
        """OSHA's limit: the row of 29 CFR 1910.1000, Table Z-1, with the
        chemical's CAS number, read from the Code of Federal Regulations."""
        cas = self.identity.casrn
        if not cas:
            return None
        day = today()
        got = fetch("https://www.ecfr.gov/api/versioner/v1/full/"
                    f"{day[:4]}-01-01/title-29.xml?part=1910&section=1910.1000",
                    headers={"Accept-Encoding": "gzip"}, browser=False)
        if got is None:
            self.unreachable.append("OSHA")
            return None
        xml = got.text
        at = xml.find(cas)
        if at < 0:
            return None
        row = xml[xml.rfind("<TR", 0, at):xml.find("</TR>", at)]
        cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip()
                 for c in re.findall(r"<TD[^>]*>(.*?)</TD>", row, re.S)]
        if len(cells) < 4:
            return None
        ppm, mgm3 = cells[2], cells[3]
        ceiling = "(C)" in ppm or "(C)" in mgm3
        skin = len(cells) > 4 and "X" in cells[4].upper()
        limit = (f"{ppm.replace('(C)', '').strip() or 'none'} ppm"
                 f" ({mgm3.replace('(C)', '').strip()} mg/m3)" if mgm3 else f"{ppm} ppm")
        text = (f"29 CFR 1910.1000, Table Z-1 (Limits for Air Contaminants), row for {cells[0]} "
                f"(CAS {cells[1]}): {limit}, as "
                + ("a ceiling value, not to be exceeded at any time (the entry is marked \"(C)\")"
                   if ceiling else "an 8-hour time-weighted average")
                + ("; skin designation" if skin else "") + ".")
        return Source("osha", _record(
            "report", "Occupational Safety and Health Administration (OSHA)",
            "29 CFR § 1910.1000: Table Z-1 limits for air contaminants",
            "Washington, DC: U.S. Department of Labor, Occupational Safety and Health Administration",
            got.year, got, "https://www.ecfr.gov/current/title-29/section-1910.1000", "regulation"),
            text, {"osha_pel": text})

    def niosh(self) -> Source | None:
        """NIOSH's Pocket Guide page: PubChem's record gives its address."""
        url = self.pubchem_source_url("National Institute for Occupational Safety and Health", r"/npg/")
        if not url:
            return None
        page = fetch(url)
        if page is None:
            self.unreachable.append("NIOSH")
            return None
        words = html_text(page.text)
        name = between(words, r"Pocket Guide to Chemical Hazards\s*-?\s*\n", r"\n", 200).split("\n")[-1].strip()
        text = between(words, r"\nSynonyms", r"\nSee also|\nPage last reviewed|\nContent source", 3500)
        if not text:
            return None
        rel = between(text, r"NIOSH REL", r"OSHA PEL|\n", 300)
        return Source("niosh", _record(
            "website", "National Institute for Occupational Safety and Health (NIOSH)",
            f"NIOSH pocket guide to chemical hazards: {name or self.identity.name}",
            f"Cincinnati, OH: {HHS}, Centers for Disease Control and Prevention, "
            "National Institute for Occupational Safety and Health",
            page.year, page, url, "regulation"), text, {"niosh_rel": rel} if rel else {})

    def acgih(self) -> Source | None:
        """ACGIH's limit: its site's search by CAS number gives the
        chemical's page."""
        cas = self.identity.casrn
        if not cas:
            return None
        found = fetch(f"https://www.acgih.org/?s={quote(cas)}")
        if found is None:
            self.unreachable.append("ACGIH")
            return None
        for url in dict.fromkeys(re.findall(r'href="(https://www\.acgih\.org/[a-z0-9\-]+/)"', found.text)):
            if re.search(r"/(science|about|membership|education|news|events|store|contact|"
                         r"publications|terms|privacy|copyright|return|donate|enroll)", url):
                continue
            page = fetch(url)
            if page is None:
                continue
            words = html_text(page.text)
            if f"CAS number: {cas}" not in " ".join(words.split()):
                continue
            name = words[:words.find("CAS number:")].strip().split("\n")[-1].strip()
            text = between(words, r"CAS number:", r"To view TLV|Not a Subscriber", 1200)
            return Source("acgih", _record(
                "website", "American Conference of Governmental Industrial Hygienists (ACGIH)",
                f"ACGIH Data Hub: {name or self.identity.name}",
                "Cincinnati, OH: American Conference of Governmental Industrial Hygienists",
                page.year, page, url, "regulation"), text,
                {"acgih_tlv": "; ".join(" ".join(line.split()) for line in text.split("\n")
                                        if line.strip().startswith("TLV"))})
        return None

    def drinking_water(self) -> Source | None:
        """EPA's drinking water limits: the chemical's row in the table of the
        National Primary Drinking Water Regulations."""
        url = "https://www.epa.gov/ground-water-and-drinking-water/national-primary-drinking-water-regulations"
        page = fetch(url)
        if page is None:
            self.unreachable.append("EPA drinking water regulations")
            return None
        for row in re.findall(r"<tr\b.*?</tr>", page.text, re.S | re.I):
            cells = [" ".join(html_text(c).split()) for c in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", row, re.S | re.I)]
            if len(cells) < 3 or not self._is_named(cells[0]):
                continue
            head = between(page.text[:page.text.find(row)], r"<thead", r"</thead>", 4000)
            labels = [" ".join(html_text(c).split()) for c in re.findall(r"<th\b[^>]*>(.*?)</th>", head, re.S | re.I)]
            pairs = [f"{label or 'column'}: {cell}" for label, cell in zip(labels or [""] * len(cells), cells)]
            text = "National Primary Drinking Water Regulations, row for " + "; ".join(pairs)
            updated = re.search(r"Last updated on [A-Za-z]+ \d+, ((?:19|20)\d\d)", page.text)
            facts = {"epa_mclg": f"{cells[1]} mg/L", "epa_mcl": f"{cells[2]} mg/L"}
            return Source("drinking_water", _record(
                "website", f"{EPA} (USEPA)", "National Primary Drinking Water Regulations",
                f"Washington, DC: {EPA}", int(updated.group(1)) if updated else page.year, page, url,
                "regulation"), text, facts)
        return None

    def oecd_sids(self) -> Source | None:
        """OECD's SIDS initial assessment: its Existing Chemicals Database
        searched by CAS number (a form, answered within one visit), then the
        final assessment report the chemical's page links."""
        import requests
        cas = self.identity.casrn
        if not cas:
            return None
        base = "https://hpvchemicals.oecd.org/ui/"
        visit = requests.Session()
        visit.headers["User-Agent"] = "Mozilla/5.0 (X11; Linux x86_64) Chrome/120.0 Safari/537.36"
        try:
            form = visit.get(base + "Search.aspx", timeout=40)
            hidden = {}
            for tag in re.findall(r"<input[^>]+>", form.text):
                name = re.search(r'name="([^"]+)"', tag)
                if 'type="hidden"' in tag and name:
                    value = re.search(r'value="([^"]*)"', tag)
                    hidden[name.group(1)] = value.group(1) if value else ""
            found = visit.post(base + "Search.aspx", timeout=60, data={
                **hidden, "ctl00$ContentPlaceHolder1$CasnumTextBox": cas,
                "ctl00$ContentPlaceHolder1$MaxRecord": "25",
                "ctl00$ContentPlaceHolder1$ImageButton1.x": "10",
                "ctl00$ContentPlaceHolder1$ImageButton1.y": "10"})
            frames = [visit.get(urljoin(found.url, src.replace("&amp;", "&")), timeout=40).text
                      for src in re.findall(r'<iframe[^>]+src="((?:SIDS|SidsOrganigrame)\.aspx[^"]+)"', found.text)]
        except requests.RequestException as exc:
            logger.info("OECD not read: %s", exc)
            self.unreachable.append("OECD")
            return None
        if "SIDS_Details" not in found.url or not any(cas in html_text(f) for f in frames):
            return None                      # no single chemical of that CAS number
        status = next((f for f in frames if "Final Assessment Report" in f), "")
        row = between(status, r"Final Assessment Report", r"</tr>", 3000)
        link = re.search(r'href="(handler\.axd\?id=[0-9A-Fa-f\-]{36})"', row)
        if not link:
            return None
        url = base + link.group(1)
        pdf = fetch(url)
        if pdf is None or not pdf.is_pdf:
            self.unreachable.append("OECD")
            return None
        meeting = re.search(r"(SIAM|CoCAM)\s*(\d+),\s*\d\d/\d\d/((?:19|20)\d\d)", " ".join(html_text(status).split()))
        text = pdf_text(pdf.content, 1, 45)
        profile = (between(text, r"SIDS INITIAL ASSESSMENT PROFILE", r"\n\s*(?:FULL )?SIDS (?:INITIAL ASSESSMENT REPORT|SUMMARY)\s*\n", 14000)
                   or text[:14000])
        return Source("oecd", _record(
            "report", "Organisation for Economic Co-operation and Development (OECD)",
            "SIDS initial assessment report" + (f" for {meeting.group(1)} {meeting.group(2)}" if meeting else "")
            + f": {self.identity.name}",
            "Paris, France: Organisation for Economic Co-operation and Development",
            int(meeting.group(3)) if meeting else None, pdf, url, "government_report"), profile)

    def comptox(self) -> Source | None:
        """EPA's CompTox Chemicals Dashboard, through its data service."""
        dtxsid = self.identity.dtxsid
        key = os.environ.get("CTX_API_KEY", "")
        if not dtxsid:
            return None
        if not key:
            self.notes.append("No CTX_API_KEY: the CompTox dashboard was not consulted")
            self.unreachable.append("CTX")
            return None
        headers = {"x-api-key": key, "Accept": "application/json"}

        def ask(path: str):
            got = fetch(f"{CTX}{path}", headers=headers, browser=False)
            if got is None:
                return None
            try:
                return json.loads(got.text), got
            except ValueError:
                return None

        detail = ask(f"/chemical/detail/search/by-dtxsid/{dtxsid}")
        if detail is None:
            self.unreachable.append("CTX")
            return None
        info, got = detail
        lines: list[str] = []
        uses = ask(f"/exposure/functional-use/search/by-dtxsid/{dtxsid}")
        categories = sorted({(u.get("functioncategory") or "").strip() for u in (uses[0] if uses else [])
                             if isinstance(u, dict)} - {""})
        if categories:
            lines.append("Reported functional uses: " + "; ".join(categories))
        hazard = ask(f"/hazard/toxval/search/by-dtxsid/{dtxsid}")
        wanted = ("rfd", "rfc", "noael", "loael", "mrl", "cancer slope", "unit risk")
        seen = set()
        for rec in (hazard[0] if hazard else []):
            if not isinstance(rec, dict):
                continue
            kind = (rec.get("toxvalType") or "")
            if not any(w in kind.lower() for w in wanted) or rec.get("toxvalNumeric") in (None, ""):
                continue
            if (rec.get("toxvalTypeSuperCategory") or "").lower().startswith("eco"):
                continue
            if not _ASSESSMENTS.search(rec.get("source") or ""):
                continue
            line = (f"{kind} {rec.get('toxvalNumeric')} {rec.get('toxvalUnits') or ''}"
                    f" ({rec.get('exposureRoute') or 'route not stated'}, {rec.get('studyType') or 'study type not stated'}"
                    f"; source: {rec.get('source')})").replace("  ", " ")
            if line not in seen and len(seen) < 40:
                seen.add(line)
                lines.append(line)
        name = info.get("preferredName") or self.identity.name
        return Source("comptox", _record(
            "website", f"{EPA} (USEPA)",
            f"CompTox Chemicals Dashboard: {name} {info.get('casrn') or self.identity.casrn} | {dtxsid}",
            f"Washington, DC: {EPA}", got.year, got,
            f"https://comptox.epa.gov/dashboard/chemical/details/{dtxsid}", "database"),
            "\n".join(lines), {"cpdat_uses": categories})

    def papers(self, limit: int = 14) -> list[Source]:
        """Papers on the chemical's toxicity, metabolism and kinetics in
        mammals, from PubMed, the most relevant first, each with its
        abstract."""
        names = [n for n in self.names() if len(n) > 4][:4]
        if not names:
            return []
        titled = " OR ".join(f'"{n}"[ti]' for n in names)
        term = (f"({titled}) AND (toxicity[sh] OR metabolism[sh] OR pharmacokinetics[sh] OR poisoning[sh]) "
                "AND (rats[mh] OR mice[mh] OR humans[mh] OR rabbits[mh] OR guinea pigs[mh] OR dogs[mh])")
        found = fetch(EUTILS + "esearch.fcgi?db=pubmed&retmax=40&sort=relevance&retmode=json&term=" + quote(term),
                      browser=False)
        if found is None:
            self.unreachable.append("PubMed")
            return []
        try:
            ids = json.loads(found.text)["esearchresult"]["idlist"][:limit]
        except (ValueError, KeyError):
            return []
        if not ids:
            return []
        if not found.from_cache:
            time.sleep(0.5)
        got = fetch(EUTILS + "efetch.fcgi?db=pubmed&retmode=xml&id=" + ",".join(ids), browser=False)
        if got is None:
            self.unreachable.append("PubMed")
            return []
        out: list[Source] = []
        for article in re.findall(r"<PubmedArticle>.*?</PubmedArticle>", got.text, re.S):
            def one(tag: str, within: str = article) -> str:
                m = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", within, re.S)
                return " ".join(html_text(m.group(1)).split()) if m else ""
            authors = [f"{one('LastName', a)} {one('Initials', a)}".strip()
                       for a in re.findall(r"<Author\b.*?</Author>", article, re.S) if one("LastName", a)]
            journal = re.search(r"<Journal>.*?</Journal>", article, re.S)
            issue = journal.group(0) if journal else ""
            year = re.search(r"<PubDate>.*?((?:19|20)\d\d)", issue, re.S)
            doi = re.search(r'<ArticleId IdType="doi">([^<]+)</ArticleId>', article)
            pmid = one("PMID")
            abstract = " ".join(" ".join(html_text(a).split())
                                for a in re.findall(r"<AbstractText\b[^>]*>(.*?)</AbstractText>", article, re.S))
            title = one("ArticleTitle")
            if not (title and authors and year):
                continue
            out.append(Source("paper", {
                "kind": "paper", "authors": authors, "title": title.rstrip("."),
                "container": one("ISOAbbreviation", article) or one("Title", issue),
                "year": int(year.group(1)), "volume": one("Volume", issue) or None,
                "issue": one("Issue", issue) or None, "pages": one("MedlinePgn") or None,
                "doi": doi.group(1).strip() if doi else None, "pmid": pmid,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", "source_type": "paper",
            }, abstract[:2500]))
        return out

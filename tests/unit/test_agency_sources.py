"""
The documents a Background's gatherer consults (narrative.agency_sources,
narrative.source_fetch) and how they reach the writer.

No test here asks a site: each finder is given the page it would read.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

import narrative.agency_sources as ag
import narrative.source_fetch as sf
from narrative.chem_resolver import ChemicalIdentity
from narrative.sources import background_sources, format_entry

DAY = "2026-11-23"


def _got(url, text, content_type="text/html", content=None):
    return sf.Fetched(url, content if content is not None else text.encode("utf-8"),
                      content_type, DAY, "request")


def _identity(**over):
    return ChemicalIdentity(**{"name": "Testol", "casrn": "111-11-1", "dtxsid": "DTXSID1",
                               "pubchem_cid": 42, "synonyms": ["o-Testol"], **over})


@pytest.fixture
def pages(monkeypatch):
    """{address prefix: page text} served in place of the sites; an address
    with no page could not be read."""
    served: dict[str, str] = {}

    def fake(url, **kwargs):
        for prefix, text in served.items():
            if url.startswith(prefix):
                return _got(url, text)
        return None

    monkeypatch.setattr(ag, "fetch", fake)
    return served


# ---------------------------------------------------------------------------
# The fetch that keeps what it read
# ---------------------------------------------------------------------------

@pytest.fixture
def kept(tmp_path, monkeypatch):
    monkeypatch.setattr(sf, "_dir", lambda: tmp_path)
    return tmp_path


def test_a_document_read_is_kept_and_served_from_there(kept, monkeypatch):
    asked = []
    monkeypatch.setattr(sf, "_by_request", lambda url, data, headers: (asked.append(url) or _got(url, "page"), 200))
    first = sf.fetch("https://a.example/x")
    second = sf.fetch("https://a.example/x")
    assert asked == ["https://a.example/x"]
    assert not first.from_cache and second.from_cache and second.text == "page"
    assert second.accessed == "November 23, 2026"


def test_a_kept_document_older_than_a_month_is_read_again(kept, monkeypatch):
    monkeypatch.setattr(sf, "_by_request", lambda url, data, headers: (_got(url, "new"), 200))
    old = (datetime.now(timezone.utc) - timedelta(days=45)).strftime("%Y-%m-%d")
    sf._keep(sf.Fetched("https://a.example/x", b"old", "text/html", old, "request"), None)
    assert sf.fetch("https://a.example/x").text == "new"


def test_a_site_that_refuses_a_program_is_asked_with_a_browser(kept, monkeypatch):
    monkeypatch.setattr(sf, "_by_request", lambda url, data, headers: (None, 403))
    monkeypatch.setattr(sf, "_by_browser", lambda url: _got(url, "from the browser"))
    got = sf.fetch("https://a.example/x")
    assert got.text == "from the browser"
    # A page that is simply not there is not asked for again.
    monkeypatch.setattr(sf, "_by_request", lambda url, data, headers: (None, 404))
    assert sf.fetch("https://a.example/absent") is None
    # Nor is a form (a POST) ever sent through the browser.
    monkeypatch.setattr(sf, "_by_request", lambda url, data, headers: (None, 403))
    assert sf.fetch("https://a.example/form", data={"q": "1"}) is None


def test_html_text_and_between():
    text = sf.html_text("<h1>Limits</h1><script>x()</script><table><tr><td>PEL</td><td>50&nbsp;ppm</td></tr></table>")
    assert text == "Limits\nPEL | 50 ppm |"
    assert sf.between("a\nStart here\nmiddle\nEnd\nz", r"Start", r"\nEnd") == "Start here\nmiddle"
    assert sf.between("nothing", r"Start") == ""


# ---------------------------------------------------------------------------
# The finders
# ---------------------------------------------------------------------------

def test_osha_reads_the_row_of_table_z1_by_cas_number(pages):
    pages["https://www.ecfr.gov/"] = (
        "<TR><TD>Other</TD><TD>222-22-2</TD><TD>5</TD><TD>10</TD><TD></TD></TR>"
        "<TR><TD>o-Testol</TD><TD>111-11-1</TD><TD>(C)50</TD><TD>(C)300</TD><TD></TD></TR>")
    source = ag.Finder(_identity()).osha_table_z()
    assert "50 ppm (300 mg/m3), as a ceiling value" in source.text
    assert "o-Testol (CAS 111-11-1)" in source.text
    assert format_entry(source.record) == (
        "Occupational Safety and Health Administration (OSHA). 29 CFR § 1910.1000: Table Z-1 "
        "limits for air contaminants. Washington, DC: U.S. Department of Labor, Occupational "
        "Safety and Health Administration; 2026. [Accessed: November 23, 2026]. "
        "https://www.ecfr.gov/current/title-29/section-1910.1000")
    # A chemical the table does not list has no OSHA limit there.
    assert ag.Finder(_identity(casrn="999-99-9")).osha_table_z() is None


def test_an_unread_site_is_unreachable_not_absent(pages):
    finder = ag.Finder(_identity())
    assert finder.osha_table_z() is None and finder.unreachable == ["OSHA"]


def test_drinking_water_finds_the_row_by_any_name_of_the_chemical(pages):
    pages["https://www.epa.gov/"] = (
        "<table><thead><tr><th>Contaminant</th><th>MCLG</th><th>MCL</th><th>Effects</th></tr></thead>"
        "<tr><td>Benzene</td><td>zero</td><td>0.005</td><td>Anemia</td></tr>"
        "<tr><td>o-Testol</td><td>0.6</td><td>0.6</td><td>Liver problems</td></tr></table>"
        "Last updated on August 31, 2025")
    source = ag.Finder(_identity()).drinking_water()
    assert source.facts == {"epa_mclg": "0.6 mg/L", "epa_mcl": "0.6 mg/L"}
    assert "Contaminant: o-Testol; MCLG: 0.6; MCL: 0.6; Effects: Liver problems" in source.text
    assert source.record["year"] == 2025
    assert ag.Finder(_identity(synonyms=[])).drinking_water() is None


def test_acgih_takes_the_page_that_names_the_cas_number(pages):
    pages["https://www.acgih.org/?s="] = (
        '<a href="https://www.acgih.org/science/">Science</a>'
        '<a href="https://www.acgih.org/p-testol/">p</a><a href="https://www.acgih.org/o-testol/">o</a>')
    pages["https://www.acgih.org/p-testol/"] = "<h1>p-TESTOL</h1><p>CAS number: 333-33-3</p>"
    pages["https://www.acgih.org/o-testol/"] = (
        "<h1>o-TESTOL</h1><p>CAS number: 111-11-1</p><p>TLV–TWA, 25 ppm</p><p>TLV–STEL, 50 ppm</p>"
        "<p>To view TLV and Documentation, you must be logged in</p>")
    source = ag.Finder(_identity()).acgih()
    assert source.record["url"] == "https://www.acgih.org/o-testol/"
    assert source.record["title"] == "ACGIH Data Hub: o-TESTOL"
    assert source.facts["acgih_tlv"] == "TLV–TWA, 25 ppm; TLV–STEL, 50 ppm"


def _pubchem_record():
    def info(ref, name, text, url=None):
        markup = [{"URL": url}] if url else []
        return {"ReferenceNumber": ref, "Name": name,
                "Value": {"StringWithMarkup": [{"String": text, "Markup": markup}]}}
    return {"Record": {
        "RecordTitle": "Testol",
        "Reference": [
            {"ReferenceNumber": 1, "SourceName": "International Agency for Research on Cancer (IARC)", "URL": "https://monographs.iarc.who.int/list"},
            {"ReferenceNumber": 2, "SourceName": "NTP Technical Reports", "URL": "https://ntp.niehs.nih.gov/data/tr"},
            {"ReferenceNumber": 3, "SourceName": "EPA Integrated Risk Information System (IRIS)", "URL": "https://iris.epa.gov/ChemicalLanding/&substance_nmbr=9"},
        ],
        "Section": [{"TOCHeading": "Toxicity", "Section": [{"TOCHeading": "Carcinogen Classification", "Information": [
            info(1, "IARC Carcinogenic Agent", "ortho-Testol"),
            info(1, "IARC Carcinogenic Classes", "Group 3: Not classifiable as to its carcinogenicity to humans"),
            info(1, "IARC Monographs", "Volume 73: (1999) Some Chemicals", "http://publications.iarc.who.int/91"),
            info(2, "Substance", "Testol"),
            info(2, "NTP Technical Report", "TR-255: Toxicology Studies of Testol in Rats (Gavage Studies)  (1985 )", "https://ntp.niehs.nih.gov/go/tr255abs"),
            info(2, "Conclusion for Male Rat", "No Evidence"),
        ]}]}],
    }}


def test_iarc_and_ntp_come_from_the_entries_pubchem_carries(pages):
    pages["https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/42/"] = json.dumps(_pubchem_record())
    pages["https://publications.iarc.who.int/91"] = '<meta name="citation_title" content="Some Chemicals that Cause Tumours">'
    pages["https://ntp.niehs.nih.gov/go/tr255abs"] = "<h1>Abstract for TR-255</h1><h2>Abstract</h2><p>" + "Testol was studied. " * 30 + "</p>"
    finder = ag.Finder(_identity())
    iarc = finder.iarc()
    assert iarc.facts == {"cancer_class": "IARC Group 3: Not classifiable as to its carcinogenicity to humans"}
    assert format_entry(iarc.record).startswith(
        "International Agency for Research on Cancer (IARC). Some Chemicals that Cause Tumours "
        "(IARC Monographs; vol. 73). Lyon, France: International Agency for Research on Cancer; 1999.")
    (ntp,) = finder.ntp_reports()
    assert ntp.record["year"] == 1985 and ntp.record["number"] == "NTP Technical Report No. 255"
    assert "Conclusion for Male Rat: No Evidence" in ntp.text and "Testol was studied." in ntp.text
    assert "1985. NTP Technical Report No. 255. [Accessed: November 23, 2026]. https://ntp.niehs.nih.gov/go/tr255abs" in format_entry(ntp.record)
    assert finder.pubchem_source_url("Integrated Risk Information System", r"substance_nmbr").endswith("substance_nmbr=9")


def test_a_chemical_pubchem_has_no_iarc_entry_for_has_no_monograph(pages):
    record = _pubchem_record()
    record["Record"]["Section"] = []
    pages["https://pubchem.ncbi.nlm.nih.gov/"] = json.dumps(record)
    finder = ag.Finder(_identity())
    assert finder.iarc() is None and finder.ntp_reports() == [] and finder.unreachable == []


def test_atsdr_follows_its_risk_level_list_to_the_profile(pages, monkeypatch):
    pages["https://wwwn.cdc.gov/TSP/MRLS/mrlslisting.aspx"] = (
        '<a href="../substances/ToxSubstance.aspx?toxid=7">OTHER</a><td>222-22-2</td>'
        '<a href="../substances/ToxSubstance.aspx?toxid=126">TESTOL</a><td>111-11-1</td>')
    pages["https://wwwn.cdc.gov/TSP/substances/ToxSubstance.aspx?toxid=126"] = (
        '<a href="../ToxProfiles/ToxProfiles.aspx?id=704&amp;tid=126">Toxicological Profile</a>')
    pages["https://wwwn.cdc.gov/TSP/ToxProfiles/ToxProfiles.aspx?id=704&tid=126"] = (
        "<p>Agency for Toxic Substances and Disease Registry (ATSDR). 2006. Toxicological profile for Testols. Atlanta, GA.</p>"
        '<a href="https://www.atsdr.cdc.gov/ToxProfiles/tp10.pdf">Complete Profile<span>pdf icon</span>[PDF - 12 MB]</a>'
        '<a href="https://www.atsdr.cdc.gov/ToxProfiles/tp10-c2.pdf">Relevance to Public Health<span>pdf icon</span></a>')
    pages["https://www.atsdr.cdc.gov/ToxProfiles/tp10-c2.pdf"] = "pdf"
    monkeypatch.setattr(ag, "pdf_text", lambda content, *a: "2. RELEVANCE\nTestol harms the liver.\n 2.3 MINIMAL RISK LEVELS\nnot wanted")
    source = ag.Finder(_identity()).atsdr_profile()
    assert source.record["title"] == "Toxicological profile for Testols" and source.record["year"] == 2006
    assert source.record["url"] == "https://www.atsdr.cdc.gov/ToxProfiles/tp10.pdf"
    assert "Testol harms the liver." in source.text and "not wanted" not in source.text
    # A CAS number the list does not have: no profile, and a note, not an outage.
    finder = ag.Finder(_identity(casrn="999-99-9"))
    assert finder.atsdr_profile() is None and finder.unreachable == []
    assert finder.notes == ["ATSDR lists no toxicological profile for CAS 999-99-9"]


def test_papers_are_records_with_their_abstracts(pages):
    pages[ag.EUTILS + "esearch.fcgi"] = json.dumps({"esearchresult": {"idlist": ["77"]}})
    pages[ag.EUTILS + "efetch.fcgi"] = (
        "<PubmedArticle><PMID>77</PMID><Journal><JournalIssue><Volume>46</Volume><Issue>2</Issue>"
        "<PubDate><Year>1998</Year></PubDate></JournalIssue><Title>Toxicological sciences</Title>"
        "<ISOAbbreviation>Toxicol Sci</ISOAbbreviation></Journal>"
        "<ArticleTitle>Testol-induced lipid peroxidation.</ArticleTitle><MedlinePgn>376-85</MedlinePgn>"
        "<Abstract><AbstractText>Testol is a hepatotoxicant.</AbstractText></Abstract>"
        "<AuthorList><Author><LastName>Hoglen</LastName><Initials>NC</Initials></Author></AuthorList>"
        '<ArticleId IdType="doi">10.1006/toxs.1998.2523</ArticleId></PubmedArticle>')
    (paper,) = ag.Finder(_identity()).papers()
    assert paper.text == "Testol is a hepatotoxicant."
    assert format_entry(paper.record) == (
        "Hoglen NC. Testol-induced lipid peroxidation. Toxicol Sci. 1998; 46(2):376-85. "
        "https://doi.org/10.1006/toxs.1998.2523")


# ---------------------------------------------------------------------------
# From the gatherer to the writer to the report's list
# ---------------------------------------------------------------------------

def test_the_gatherer_numbers_the_documents_and_keeps_their_facts(monkeypatch):
    from narrative import data_gatherer as dg

    record = {"kind": "report", "authors": ["OSHA"], "title": "Table Z-1", "container": "Washington, DC: OSHA",
              "year": 2026, "url": "https://x.example/z1", "source_type": "regulation"}

    class FakeFinder:
        notes = ["a note"]
        unreachable = ["IRIS"]

        def __init__(self, identity, report):
            pass

        def __getattr__(self, name):
            if name == "osha_table_z":
                return lambda: ag.Source("osha", record, "50 ppm ceiling", {"osha_pel": "50 ppm ceiling"})
            if name == "papers":
                return lambda: [ag.Source("paper", {"kind": "paper", "authors": ["A B"], "title": "T",
                                                    "container": "J", "year": 2000}, "abstract")]
            if name == "acgih":
                def boom():
                    raise RuntimeError("site changed")
                return boom
            return lambda: None

    monkeypatch.setattr(ag, "Finder", FakeFinder)
    data = dg.BackgroundData(identity=_identity())
    dg.gather_documents(data)
    assert data.references == [record]
    assert data.documents == [{"n": 1, "label": "Table Z-1", "text": "50 ppm ceiling"}]
    assert data.osha_pel == "50 ppm ceiling [1]"
    assert data.mechanism_papers[0]["abstract"] == "abstract"
    assert data.unreachable_sources == ["IRIS"] and "a note" in data.notes
    # One document's failure is a note; the rest are still gathered.
    assert any("ACGIH" in n and "site changed" in n for n in data.notes)


def test_the_writer_offers_each_document_under_its_number_and_keeps_records(monkeypatch):
    import narrative.background_writer as bw
    from narrative.data_gatherer import BackgroundData

    data = BackgroundData(identity=_identity())
    data.references = [{"kind": "report", "authors": ["Occupational Safety and Health Administration (OSHA)"],
                        "title": "Table Z-1", "container": "Washington, DC: OSHA", "year": 2026,
                        "accessed": "November 23, 2026", "url": "https://x.example/z1", "source_type": "regulation"}]
    data.documents = [{"n": 1, "label": "Table Z-1", "text": "50 ppm as a ceiling"}]
    data.mechanism_papers = [{"kind": "paper", "authors": ["Hoglen NC"], "title": "Lipid peroxidation",
                              "container": "Toxicol Sci", "year": 1998, "doi": "10.1/x", "abstract": "Kupffer cells."}]
    prompt = bw.build_prompt(data)
    assert "--- DOCUMENT [1]: Table Z-1 ---\n50 ppm as a ceiling" in prompt
    assert "[2] Hoglen NC. Lipid peroxidation. Toxicol Sci. 1998. https://doi.org/10.1/x" in prompt
    assert "Abstract: Kupffer cells." in prompt

    class FakeEndpoint:
        def __init__(self, **kw):
            pass

        def generate(self, prompt, system=""):
            return "The limit is a ceiling [1]. Kupffer cells matter [2].\n\nReferences\n[1] OSHA Table Z-1\n[2] Hoglen Lipid peroxidation"

    monkeypatch.setattr(bw, "AnthropicEndpoint", FakeEndpoint)
    monkeypatch.setattr(bw, "distill_abstract_background", lambda **kw: "")
    result = bw.generate_background(data)
    assert [s["n"] for s in result["sources"]] == [1, 2]
    assert "abstract" not in result["sources"][1] and result["sources"][1]["doi"] == "10.1/x"
    assert result["references"][0].startswith("[1] Occupational Safety and Health Administration (OSHA). Table Z-1. Washington, DC: OSHA; 2026.")

    # The report's list is built from the records, not from the printed lines.
    sources, by_number = background_sources(result["references"], result["sources"])
    paper = sources[by_number[2]]
    assert paper["kind"] == "paper" and paper["origin"] == {"from": "background"} and paper["doi"] == "10.1/x"
    assert sources[by_number[1]]["authors"] == ["Occupational Safety and Health Administration (OSHA)"]
    # A list kept before records were (lines only) still reads as before.
    old, numbers = background_sources(["[1] ATSDR profile (government report). https://a.example/tp"])
    assert old[numbers[1]]["text"] == "ATSDR profile (government report)."

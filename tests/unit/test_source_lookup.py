"""narrative/source_lookup.py — what was asked of the outside world about a
source, and what is kept of the answers (ADR-0038).  Nothing here uses the
network: the asking is passed in."""

import json

import pytest

from narrative import source_lookup as sl


@pytest.fixture(autouse=True)
def kept(tmp_path, monkeypatch):
    monkeypatch.setattr(sl, "_path", lambda: tmp_path / "_source_lookups.json")
    return tmp_path / "_source_lookups.json"


def test_a_registered_doi_is_asked_once_and_kept(kept):
    asked = []
    ask = lambda doi: asked.append(doi) or sl.REGISTERED
    assert sl.known_doi("10.1/X") == sl.NOT_CHECKED
    assert sl.check_doi("10.1/X", ask) == sl.REGISTERED
    assert sl.check_doi(" 10.1/x ", ask) == sl.REGISTERED
    assert asked == ["10.1/x"]
    assert sl.known_doi("10.1/X") == sl.REGISTERED
    assert json.loads(kept.read_text())["doi"]["10.1/x"]["state"] == sl.REGISTERED


def test_a_doi_that_is_not_registered_or_not_answered_is_asked_again(kept):
    answers = iter([sl.NOT_REGISTERED, sl.NOT_CHECKED, sl.REGISTERED])
    ask = lambda doi: next(answers)
    assert sl.check_doi("10.1/y", ask) == sl.NOT_REGISTERED
    assert sl.known_doi("10.1/y") == sl.NOT_REGISTERED       # the last answer, on file
    assert sl.check_doi("10.1/y", ask) == sl.NOT_CHECKED     # asked again; no answer
    assert sl.known_doi("10.1/y") == sl.NOT_REGISTERED
    assert sl.check_doi("10.1/y", ask) == sl.REGISTERED
    assert sl.known_doi("10.1/y") == sl.REGISTERED
    assert sl.check_doi("", ask) == sl.NOT_CHECKED


def test_many_dois_are_checked_each_once():
    asked = []
    states = sl.check_dois(["10.1/a", "10.1/A", "", "10.1/b"],
                           ask=lambda d: asked.append(d) or
                           (sl.REGISTERED if d.endswith("a") else sl.NOT_REGISTERED), workers=2)
    assert states == {"10.1/a": sl.REGISTERED, "10.1/b": sl.NOT_REGISTERED}
    assert sorted(asked) == ["10.1/a", "10.1/b"]


def test_an_address_that_answered_is_kept_and_one_out_of_reach_is_asked_again():
    asked = []

    def ask(url):
        asked.append(url)
        return sl.ANSWERS if "good" in url else sl.NOT_REACHED

    assert sl.check_url("https://good.example", ask) == sl.ANSWERS
    assert sl.check_url("https://good.example", ask) == sl.ANSWERS
    assert sl.check_url("https://far.example", ask) == sl.NOT_REACHED
    assert sl.check_url("https://far.example", ask) == sl.NOT_REACHED
    assert asked == ["https://good.example", "https://far.example", "https://far.example"]


def test_what_is_not_an_address_is_not_found():
    assert sl.ask_url("ftp://old.example/file") == sl.NOT_FOUND
    assert sl.ask_url("") == sl.NOT_FOUND

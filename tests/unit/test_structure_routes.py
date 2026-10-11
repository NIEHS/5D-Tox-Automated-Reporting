"""Helper routes behind the visual document-structure editor."""

import yaml

from web_routes.structure_routes import attribute_error


def test_catalog_is_rule_driven(client):
    body = client.get("/api/document-structure/catalog").json()
    t = body["types"]
    assert "table" in t["narrative+tables"]["allowed_children"]
    assert t["table"]["requires"] == ["platform"] and t["table"]["orientable"] is True
    assert t["genomics-section"]["requires"] == ["data_key", "narrative_key"]
    assert t["title-page"]["subtypable"] is True and t["freeform-block"]["freeform"] is True
    assert set(body["regions"]) == {"front", "body", "back"}
    v = body["vocab"]
    assert "Body Weight" in v["platforms"] and "background" in v["data_keys"]
    assert "study_design" in v["methods_keys"] and v["orientations"] == ["portrait", "landscape"]
    assert "id" in body["node_keys"] and "children" in body["node_keys"]


def test_parse_dump_roundtrip_is_stable(client):
    default = client.get("/api/document-config/DTXSID_SE?default=1").json()["yaml"]
    parsed = client.post("/api/document-structure/parse", json={"yaml": default}).json()
    assert isinstance(parsed["document"], list) and parsed["document"][0].get("region") == "front"
    dumped = client.post("/api/document-structure/dump", json={"document": parsed["document"]}).json()["yaml"]
    assert yaml.safe_load(dumped) == yaml.safe_load(default)
    # Parse errors are 422 with a message, never a 500.
    bad = client.post("/api/document-structure/parse", json={"yaml": "document: [unclosed"})
    assert bad.status_code == 422 and "invalid YAML" in bad.json()["error"]


def test_validate_reports_ok_and_attributes_errors(client):
    default = client.get("/api/document-config/DTXSID_SE?default=1").json()["yaml"]
    doc = client.post("/api/document-structure/parse", json={"yaml": default}).json()["document"]
    assert client.post("/api/document-structure/validate", json={"document": doc}).json() == {"ok": True}
    # Illegal containment: a `table` under a generated list (role `toc` is a
    # leaf in the BITS profile — ADR-0025; a table under a heading is legal now).
    broken = yaml.safe_load(yaml.safe_dump(doc))
    front_region = next(r for r in broken if r.get("region") == "front")
    methods = next(n for n in front_region["children"] if n.get("type") == "tables-list")
    methods.setdefault("children", []).append({"id": "rogue-table", "type": "table", "title": "X", "platform": "Body Weight"})
    res = client.post("/api/document-structure/validate", json={"document": broken}).json()
    assert res["ok"] is False and res["error"]
    assert res["node_id"] in ("rogue-table", "tables-list")
    # Bad shape is a 400, not a crash.
    assert client.post("/api/document-structure/validate", json={"document": "nope"}).status_code == 400


def test_attribute_error_prefers_longest_real_id():
    doc = [{"id": "table", "type": "toc", "children": [{"id": "table-1", "type": "toc"}]}]
    assert attribute_error("node 'table-1' is bad ('table' too)", doc) == "table-1"
    assert attribute_error("nothing quoted here", doc) is None

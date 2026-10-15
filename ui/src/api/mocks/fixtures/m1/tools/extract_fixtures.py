"""Extract M1's mock fixtures verbatim from contract.md §4 into JSON files ({status, body})."""
import json, re, sys
from pathlib import Path
contract = Path(sys.argv[1]).read_text()
out = Path(sys.argv[2])
sec4 = contract[contract.index("## 4. Mock fixtures"):]
blocks = re.findall(r"```json\n(.*?)```", sec4, re.S)
def save(name, status, body):
    (out / name).write_text(json.dumps({"status": status, "body": body}, indent=2, ensure_ascii=False) + "\n")
    print(status, name)
b = [json.loads(x) if not x.strip().startswith('{"confirm_id"') else None for x in blocks]
# order of blocks in §4: 4.1 list, 4.2 detail, 4.3 check exists, 4.4 check new, 4.5 found x2, not found, unreachable,
# 4.6 refusal exists, refusal suffix, 4.7 preview, refusal member, 4.8 delete ok(?), changed
for i, x in enumerate(b):
    print(i, (list(x.keys())[:4] if isinstance(x, dict) else x))
save("studies.contract.json", 200, b[0])
save("detail.contract.DTXSID50469320_nb.json", 200, b[1])
save("creation-check.DTXSID50469320.json", 200, b[2])
save("creation-check.DTXSID7020182.json", 200, b[3])
save("chemical.DTXSID50469320.json", 200, b[4])
save("chemical.DTXSID7020182.json", 200, b[5])
save("chemical.not-found.json", 404, b[6])
save("chemical.unreachable.json", 503, b[7])
save("create.refusal.study_exists.json", 409, b[8])
save("create.refusal.study_id_has_suffix.json", 400, b[9])
save("delete-preview.DTXSID50469320.json", 200, b[10])
save("delete-preview.refusal.member_of_report.json", 409, b[11])
save("delete.DTXSID5032498.json", 200, b[12])
save("delete.refusal.changed_since_preview.json", 409, b[13])

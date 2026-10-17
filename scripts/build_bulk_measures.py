"""
Rebuild powerbi/measures_bulk.dax from powerbi/measures.dax: every measure in one DEFINE block, so the whole set
can be pasted into Power BI's DAX query view and added with one "Update model" click.

    python scripts/build_bulk_measures.py
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

src = open(ROOT / "powerbi" / "measures.dax").read().splitlines()
start = re.compile(r"^(?!VAR |RETURN)([A-Z][^=/]*?)\s*=\s*(.*)$")
home, measures, cur = None, [], None
for line in src:
    m = re.search(r"\(home: (\w+)\)", line)
    if m:
        home, cur = m.group(1), None
        continue
    if home is None:
        continue
    s = start.match(line)
    if s:
        name, rest = s.group(1).strip(), s.group(2)
        c = re.search(r"//\s*(.+)$", rest)
        fmt = c.group(1).strip() if c else None
        cur = {"name": name, "home": home, "body": [rest], "fmt": fmt}
        measures.append(cur)
    elif line.startswith("//"):
        cur = None
    elif cur is not None:
        cur["body"].append(line)

out = [
    "// Paste this whole file into the DAX query view of the semantic model (Editing mode),",
    "// then click 'Update model: Add new measures' above DEFINE. Generated from measures.dax.",
    "// DAX query view does not set format strings: set those afterwards (see POWERBI_SETUP.md).",
    "DEFINE",
]
for m in measures:
    out.append(f"    MEASURE {m['home']}[{m['name']}] =")
    body = "\n".join(m["body"]).strip("\n")
    for b in body.splitlines():
        out.append(("        " + b) if b.strip() else "")
    while out[-1] == "":
        out.pop()
    out.append("")
out += [
    "// Sanity check: Run the query. With Sep + Oct loaded expect 54,223 calls offered.",
    "EVALUATE",
    '    ROW ( "Calls Offered", [Calls Offered], "Service Level %", [Service Level %], '
    '"Avg CSAT", [Avg CSAT], "Conversion %", [Conversion %] )',
]
open(ROOT / "powerbi" / "measures_bulk.dax", "w").write("\n".join(out) + "\n")
print(f"{len(measures)} measures written to powerbi/measures_bulk.dax")

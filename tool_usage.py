"""tool_usage.py - which MCP tool did each eval question use?

Usage (from the repo root, after an eval run):
  python tool_usage.py evals\\results\\<run>.json mcp_server\\tool_calls.jsonl

Why this exists: run_evals.py only saves SQL it finds under a 'sql_query' key, so MCP tool calls
are not recorded in its result file. The MCP server logs every call with a timestamp instead.
run_evals.py calls the agent one question at a time, in order, and records each call's duration
(elapsed_s) and its own start time (meta.timestamp). From those, each row's time window is rebuilt
and every logged tool call is assigned to the window it falls in.

Read-only: changes no eval file. Writes <run>_tools.csv next to the results file.
Limit: best-effort timing. Check the 'rows with ok status but 0 calls' line; it should be small.
"""
import csv
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

if len(sys.argv) != 3:
    sys.exit(__doc__)

res_path = Path(sys.argv[1])
res = json.loads(res_path.read_text(encoding="utf-8"))
calls = [json.loads(l) for l in Path(sys.argv[2]).read_text(encoding="utf-8").splitlines() if l.strip()]
t = datetime.strptime(res["meta"]["timestamp"], "%Y%m%d_%H%M%S").timestamp()
run_start = t

out = []
for r in res["rows"]:
    t1 = t + r["elapsed_s"]
    used = [c["tool"] for c in calls if t <= c["t"] < t1]
    out.append({"id": r["id"], "run": r["run"], "status": r["status"], "answer": r["answer"],
                "n_calls": len(used), "tools": "+".join(used),
                "fallback_used": "run_readonly_query" in used})
    t = t1

# per-question summary
print(f"{'ID':<5}{'runs':>5}{'answer pass':>13}{'0 calls':>9}{'fallback':>10}   tools used")
for qid in dict.fromkeys(o["id"] for o in out):
    rs = [o for o in out if o["id"] == qid]
    tools = Counter(x for o in rs for x in o["tools"].split("+") if x)
    print(f"{qid:<5}{len(rs):>5}{sum(o['answer'] == 'pass' for o in rs):>10}/{len(rs):<2}"
          f"{sum(o['n_calls'] == 0 for o in rs):>9}{sum(o['fallback_used'] for o in rs):>10}   "
          + ", ".join(f"{k} x{v}" for k, v in tools.most_common()))

total = Counter(x for o in out for x in o["tools"].split("+") if x)
in_window = sum(o["n_calls"] for o in out)
after_start = sum(1 for c in calls if c["t"] >= run_start)
print("\nTool totals:", dict(total))
print(f"Rows: {len(out)}   with 0 tool calls: {sum(o['n_calls'] == 0 for o in out)}"
      f"   with fallback: {sum(o['fallback_used'] for o in out)}")
print(f"Rows with ok status but 0 calls: {sum(o['status'] == 'ok' and o['n_calls'] == 0 for o in out)}")
print(f"Logged calls after run start: {after_start}   assigned to a row: {in_window}")

csv_path = res_path.with_name(res_path.stem + "_tools.csv")
with open(csv_path, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
    w.writeheader()
    w.writerows(out)
print(f"\nSaved {csv_path}")
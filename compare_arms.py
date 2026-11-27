"""compare_arms.py - compare answer accuracy of a baseline arm and an MCP arm, per question and per split.

Usage (from the repo root; each --base / --mcp takes one or more result JSON files, which are pooled):
  python compare_arms.py --base evals\\results\\raw\\A.json evals\\results\\raw\\B.json --mcp evals\\results\\M.json

Read-only. Uses only the 'answer' score (method scores are not comparable for MCP: no sql_query key).
Counting follows run_evals.py: infra_error rows are excluded; empty_output and max_iterations count as fails.
"""
import argparse
import json
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--base", nargs="+", required=True)
ap.add_argument("--mcp", nargs="+", required=True)
ap.add_argument("--questions", default="evals/questions.json")
args = ap.parse_args()

qs = json.loads(Path(args.questions).read_text(encoding="utf-8"))["questions"]
split = {q["id"]: q.get("split", "?") for q in qs}
cat = {q["id"]: q.get("category", "") for q in qs}
order = [q["id"] for q in qs]


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))["rows"]


def tally(rows, ids=None):
    sc = [r for r in rows if r["status"] != "infra_error" and (ids is None or r["id"] in ids)]
    return sum(r["answer"] == "pass" for r in sc), len(sc)


def pct(p, n):
    return f"{p}/{n} = {p / n:.1%}" if n else "n/a"


def overview(name, paths):
    print(f"\n== {name}")
    pooled = []
    for p in paths:
        rows = load(p)
        pooled += rows
        p_, n_ = tally(rows)
        empties = sum(r["status"] == "empty_output" for r in rows)
        maxit = sum(r["status"] == "max_iterations" for r in rows)
        runs = max((r["run"] for r in rows), default=0)
        print(f"  {Path(p).name}: rows={len(rows)} runs={runs} answer {pct(p_, n_)} empty={empties} max_iter={maxit}")
    p_, n_ = tally(pooled)
    print(f"  POOLED: answer {pct(p_, n_)}")
    return pooled


base = overview("BASELINE", args.base)
mcp = overview("MCP", args.mcp)

print("\n== By split (pooled)")
for s in ("dev", "heldout"):
    ids = {i for i in order if split[i] == s}
    print(f"  {s:<8} base {pct(*tally(base, ids)):<20} mcp {pct(*tally(mcp, ids))}")

print("\n== Per question (pooled)   '>' MCP better, '<' MCP worse, by pass rate")
print(f"{'ID':<5}{'split':<9}{'category':<20}{'base':>10}{'mcp':>10}   ")
for i in order:
    bp, bn = tally(base, {i})
    mp, mn = tally(mcp, {i})
    flag = ""
    if bn and mn:
        d = mp / mn - bp / bn
        flag = ">" if d > 0.01 else "<" if d < -0.01 else ""
    print(f"{i:<5}{split[i]:<9}{cat[i][:19]:<20}{f'{bp}/{bn}':>10}{f'{mp}/{mn}':>10}   {flag}")
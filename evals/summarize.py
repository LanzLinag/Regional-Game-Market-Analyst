"""summarize.py - rescore the raw run files under the current questions.json and print the final grid.

    python evals\\summarize.py
    python evals\\summarize.py | Out-File evals\\results\\final_summary.txt -Encoding utf8

The raw .json run files in evals\\results\\raw are the source of truth. This script reads them, scores them
with the grader in questions.json (via run_evals.py), and prints tables. It never writes scored copies,
so the folder stays small and the numbers always match the current grader.

Scoring rules match run_evals.py --rescore: infra errors are excluded; max_iterations and empty_output count as failures.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_evals as ev  # noqa: E402

# (label, [raw file stems]) -- files in a list are pooled as replicates of the same configuration
CONFIGS = [
    ("qwen3.5:4b   prompt v1", ["qwen3-5-4b_v1_20261121_103321"]),
    ("qwen3.5:4b   prompt v2", ["qwen3-5-4b_v2_20261123_113329", "qwen3-5-4b_v2_topup_20261123_122702"]),
    ("qwen3.5:4b   prompt v2b", ["qwen3-5-4b_v2b_20261123_162531", "qwen3-5-4b_v2b_20261124_140445"]),
    ("llama3.1:8b  prompt v1", ["llama3-1-8b_v1b_20261121_113633"]),
    ("llama3.1:8b  prompt v2", ["llama3-1-8b_v2_20261123_123045"]),
    ("llama3.1:8b  prompt v2b", ["llama3-1-8b_v2b_20261123_130436", "llama3-1-8b_v2b_20261123_155044"]),
]


def score_rows(rows, qmap):
    out = []
    for r in rows:
        q = qmap.get(r["id"])
        if q is None or r["status"] == "infra_error":
            continue
        if r["status"] == "ok":
            a = ev.score_answer(q["answer"], r["output"])[0]
            m = ev.score_method(q["method"], r["sqls"], r.get("sqls_ok"))[0]
        else:  # max_iterations / empty_output
            a = m = "fail"
        out.append({"id": r["id"], "split": q.get("split", "dev"), "answer": a, "method": m})
    return out


def pct(k, n):
    return f"{k}/{n} = {100 * k / n:.1f}%" if n else "n/a"


def counts(scored, split=None):
    s = [r for r in scored if split is None or r["split"] == split]
    n = len(s)
    return (n,
            sum(r["answer"] == "pass" for r in s),
            sum(r["method"] == "pass" for r in s),
            sum(r["answer"] == "pass" and r["method"] == "pass" for r in s))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=str(HERE / "results" / "raw"))
    args = ap.parse_args()
    cfg = json.loads((HERE / "questions.json").read_text(encoding="utf-8"))
    qmap = {q["id"]: q for q in cfg["questions"]}
    raw = Path(args.raw)
    print(f"Grader: questions.json version {cfg['meta']['version']}  ({len(qmap)} questions)\n")

    print("POOLED PER CONFIGURATION (replicates pooled; infra errors excluded)")
    print(f"{'configuration':<26}{'runs':>5}  {'answer (all)':<19}{'method (all)':<19}{'both (all)':<19}"
          f"{'answer dev':<19}{'answer held-out'}")
    detail = []
    for label, stems in CONFIGS:
        scored, per_file = [], []
        for st in stems:
            f = raw / f"{st}.json"
            if not f.exists():
                print(f"  WARNING: missing {f.name}", file=sys.stderr)
                continue
            rows = json.loads(f.read_text(encoding="utf-8"))["rows"]
            sc = score_rows(rows, qmap)
            scored += sc
            per_file.append((st, sc))
        if not scored:
            continue
        n, a, m, b = counts(scored)
        nd, ad, _, _ = counts(scored, "dev")
        nh, ah, _, _ = counts(scored, "heldout")
        print(f"{label:<26}{n:>5}  {pct(a, n):<19}{pct(m, n):<19}{pct(b, n):<19}{pct(ad, nd):<19}{pct(ah, nh)}")
        if len(per_file) > 1:
            detail.append((label, per_file))

    if detail:
        print("\nREPLICATES (same configuration, separate runs: shows run-to-run variance)")
        for label, per_file in detail:
            print(label)
            for st, sc in per_file:
                n, a, m, b = counts(sc)
                print(f"   {st:<42} answer {pct(a, n):<18} method {pct(m, n)}")


if __name__ == "__main__":
    main()
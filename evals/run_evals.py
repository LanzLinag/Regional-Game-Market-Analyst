#!/usr/bin/env python3
"""run_evals.py - send eval questions to the n8n agent webhook and score the replies.

Setup:   pip install requests
Smoke:   python evals\\run_evals.py --label qwen3.5-4b_v1 --runs 1 --only Q01,Q07,Q13
Full:    python evals\\run_evals.py --label qwen3.5-4b_v1 --runs 3 --expect-model qwen3.5

Requires the n8n workflow "Chat agent v1 - eval API" to be ACTIVE (production URL).
Run from the repo root so the optional database check can find docker compose.

Every call ends in exactly one status:
  ok              agent returned an answer -> scored
  max_iterations  agent hit its iteration cap -> scored as FAIL (a real agent failure)
  empty_output    agent returned an empty answer -> scored as FAIL
  infra_error     timeout / connection error / unrecognised payload -> excluded from accuracy

Scoring (see "meta.scoring" in questions.json):
  answer  - deterministic check on the final text: pass | fail | needs_review
  method  - regex checks on the SQL actually executed (only the sql_query values are
            read, never the model's reasoning text): pass | fail
"""
import argparse
import csv
import json
import re
import subprocess
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

import requests

DEFAULT_URL = "http://localhost:5678/webhook/eval-agent"
DEFAULT_OLLAMA = "http://localhost:11434"
WARMUP_QUESTION = "What are the total sales in North America, in millions of units?"
SQL_KEYS = {"sql_query"}
NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
EXPECTED_ROWS = 16598


# ---------------------------------------------------------------- text helpers
def norm(text):
    """Lowercase, strip accents (Pokemon == Pokemon with accent), straighten apostrophes."""
    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.replace("\u2019", "'").replace("\u2018", "'").lower()


def numbers(text):
    """All numbers in the text as floats; commas stripped ('4,392.95' -> 4392.95)."""
    out = []
    for m in NUM_RE.findall(str(text)):
        try:
            out.append(float(m.replace(",", "")))
        except ValueError:
            pass
    return out


def has_number(nums, target, tol):
    return any(abs(n - target) <= tol + 1e-9 for n in nums)


# ---------------------------------------------------------------- SQL extraction
def collect_sql(obj, found=None):
    """Walk any nested JSON and collect every value stored under a 'sql_query' key.
    Also unpacks JSON that was stringified inside a string field."""
    if found is None:
        found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in SQL_KEYS and isinstance(v, str):
                if v not in found:
                    found.append(v)
            else:
                collect_sql(v, found)
    elif isinstance(obj, list):
        for v in obj:
            collect_sql(v, found)
    elif isinstance(obj, str) and obj.lstrip().startswith("{"):
        try:
            collect_sql(json.loads(obj), found)
        except ValueError:
            pass
    return found


ERR_RE = re.compile(r"(?i)\berror\b|does not exist|must appear in the group by|syntax error|permission denied|"
                    r"invalid input|violates|could not|operator is not unique")
RAW_CALL_RE = re.compile(r'"name"\s*:\s*"query_vgsales"')


def collect_steps(obj, found=None):
    """Pair each SQL the agent sent with the observation the tool returned (n8n intermediateSteps).
    A step is any dict that has an 'observation' key and contains a sql_query somewhere inside it."""
    if found is None:
        found = []
    if isinstance(obj, dict):
        if "observation" in obj:
            sqls = collect_sql(obj)
            if sqls:
                obs = obj["observation"]
                obs = obs if isinstance(obs, str) else json.dumps(obs, ensure_ascii=False)
                found.append({"sql": sqls[0], "obs": obs[:300], "ok": not ERR_RE.search(obs[:2000])})
                return found
        for v in obj.values():
            collect_steps(v, found)
    elif isinstance(obj, list):
        for v in obj:
            collect_steps(v, found)
    return found


# ---------------------------------------------------------------- scoring
def check_one(spec, text, nums):
    """Failures for one answer spec (empty list = satisfied). text is already norm()-ed."""
    fails = []
    if "entity_any" in spec and not any(norm(e) in text for e in spec["entity_any"]):
        fails.append("entity_missing")
    if "entity_regex_any" in spec and not any(re.search(r, text) for r in spec["entity_regex_any"]):
        fails.append("entity_missing")
    if "number" in spec and not spec.get("number_optional"):
        if not has_number(nums, spec["number"], spec.get("tolerance", 0)):
            fails.append("number_missing")
    for n in spec.get("numbers_all", []):
        if not has_number(nums, n, spec.get("tolerance", 0)):
            fails.append("number_missing")
    if "must_mention_any" in spec and not any(norm(p) in text for p in spec["must_mention_any"]):
        fails.append("required_phrase_missing")
    if "must_match_regex_any" in spec and not any(re.search(r, text, re.S) for r in spec["must_match_regex_any"]):
        fails.append("required_phrase_missing")
    for pat in spec.get("must_not_match", []):
        if re.search(pat, text, re.I):
            fails.append("forbidden_phrase")
    return fails


def score_answer(spec, raw_text):
    text, nums = norm(raw_text), numbers(raw_text)
    if "alternatives" in spec:
        fails = [] if any(not check_one(a, text, nums) for a in spec["alternatives"]) \
            else ["no_alternative_satisfied"]
    else:
        fails = check_one(spec, text, nums)
    tol = spec.get("tolerance", 0.005) or 0.005
    decoy = any(has_number(nums, d, tol) for d in spec.get("decoys", []))
    if fails:
        return "fail", fails + (["decoy_present"] if decoy else [])
    if decoy:
        return "needs_review", ["decoy_present_alongside_correct_value"]
    return "pass", []


def score_method(spec, sqls, sqls_ok=None):
    """required_all must match a query that executed without error (sqls_ok); forbidden applies to every
    query the agent tried, even a blocked DELETE. sqls_ok=None (older result files) means 'assume all ran'."""
    ok = sqls if sqls_ok is None else sqls_ok
    fails = []
    for pat in spec.get("required_all", []):
        if not any(re.search(pat, s, re.S) for s in ok):
            fails.append("missing:" + pat)
    for pat in spec.get("forbidden", []):
        if any(re.search(pat, s, re.S) for s in sqls):
            fails.append("forbidden:" + pat)
    if spec.get("required_all") and not ok:
        fails.append("no_sql_found" if not sqls else "no_successful_sql")
    return ("pass" if not fails else "fail"), fails


# ---------------------------------------------------------------- calling the agent
def call_agent(url, question, timeout):
    t0 = time.time()
    try:
        r = requests.post(url, json={"question": question}, timeout=timeout)
    except requests.RequestException as e:
        return {"status": "infra_error", "detail": f"{type(e).__name__}: {e}",
                "elapsed": time.time() - t0, "output": "", "sqls": []}
    elapsed = time.time() - t0
    try:
        data = r.json()
    except ValueError:
        return {"status": "infra_error", "elapsed": elapsed, "output": "", "sqls": [],
                "detail": f"HTTP {r.status_code}, non-JSON body: {r.text[:200]}"}
    if isinstance(data, list) and data:
        data = data[0]
    sqls = collect_sql(data)
    if isinstance(data, dict) and "output" in data:
        text = "" if data["output"] is None else str(data["output"])
        status = "ok" if text.strip() else "empty_output"
        steps = collect_steps(data)
        sqls_ok = [st["sql"] for st in steps if st["ok"]] if steps else None
        return {"status": status, "output": text, "sqls": sqls, "elapsed": elapsed, "detail": "",
                "steps": steps, "sqls_ok": sqls_ok}
    blob = json.dumps(data).lower()
    if "max iterations" in blob:  # match on text, not on a key name
        return {"status": "max_iterations", "output": "", "sqls": sqls, "elapsed": elapsed,
                "detail": "Max iterations reached"}
    return {"status": "infra_error", "output": "", "sqls": sqls, "elapsed": elapsed,
            "detail": f"HTTP {r.status_code}, no 'output' field: {blob[:300]}"}


# ---------------------------------------------------------------- environment checks
def loaded_models(ollama_url):
    """Models currently loaded in Ollama (GET /api/ps), or None if unreachable."""
    try:
        r = requests.get(f"{ollama_url}/api/ps", timeout=10)
        return r.json().get("models", [])
    except Exception:
        return None


def db_rowcount():
    """Integrity check: row count of games via docker compose, or None if it can't run."""
    try:
        p = subprocess.run(
            ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "vg_admin",
             "-d", "vgsales", "-tAc", "SELECT COUNT(*) FROM games"],
            capture_output=True, text=True, timeout=60)
        return int(p.stdout.strip())
    except Exception:
        return None


# ---------------------------------------------------------------- summary
def summarize(rows, questions):
    lines = [f"{'ID':<5}{'runs':>5}{'answer':>8}{'method':>8}{'review':>8}{'maxit':>7}{'empty':>7}{'infra':>7}{'q/run':>7}"]
    csv_rows = []
    for q in questions:
        rs = [r for r in rows if r["id"] == q["id"]]
        scored = [r for r in rs if r["status"] != "infra_error"]
        n = len(scored)
        a = sum(r["answer"] == "pass" for r in scored)
        m = sum(r["method"] == "pass" for r in scored)
        rev = sum(r["answer"] == "needs_review" for r in scored)
        mx = sum(r["status"] == "max_iterations" for r in rs)
        em = sum(r["status"] == "empty_output" for r in rs)
        inf = sum(r["status"] == "infra_error" for r in rs)
        avgq = sum(r.get("n_queries", 0) for r in scored) / n if n else 0
        lines.append(f"{q['id']:<5}{len(rs):>5}{f'{a}/{n}':>8}{f'{m}/{n}':>8}{rev:>8}{mx:>7}{em:>7}{inf:>7}{avgq:>7.1f}")
        csv_rows.append({"id": q["id"], "category": q["category"], "runs": len(rs), "scored": n,
                         "answer_pass": a, "method_pass": m, "needs_review": rev,
                         "max_iterations": mx, "empty_output": em, "infra_errors": inf,
                         "avg_queries": round(avgq, 2)})
    scored_all = [r for r in rows if r["status"] != "infra_error"]
    n = len(scored_all)
    if n:
        a = sum(r["answer"] == "pass" for r in scored_all)
        m = sum(r["method"] == "pass" for r in scored_all)
        both = sum(r["answer"] == "pass" and r["method"] == "pass" for r in scored_all)
        lines.append("")
        lines.append(f"Scored runs: {n}   (infra errors excluded: {len(rows) - n})")
        lines.append(f"Answer accuracy:  {a}/{n} = {a / n:.1%}   (needs_review NOT counted as pass)")
        lines.append(f"Method accuracy:  {m}/{n} = {m / n:.1%}")
        lines.append(f"Answer AND method: {both}/{n} = {both / n:.1%}")
        fq = sum(r.get("n_failed_queries", 0) for r in scored_all)
        raw = sum(1 for r in scored_all if r.get("raw_tool_call"))
        lines.append(f"Queries that errored: {fq}   Runs whose final answer contains a raw tool-call JSON: {raw}")
    return "\n".join(lines), csv_rows


# ---------------------------------------------------------------- main
def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", required=True, help="e.g. qwen3.5-4b_v1 (goes in the result file names)")
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=300, help="seconds per call")
    ap.add_argument("--only", help="comma-separated question ids, e.g. Q01,Q07")
    ap.add_argument("--questions", help="path to questions.json (default: next to this script)")
    ap.add_argument("--out-dir", help="default: evals/results next to this script")
    ap.add_argument("--ollama-url", default=DEFAULT_OLLAMA)
    ap.add_argument("--expect-model", help="abort unless a loaded Ollama model name contains this")
    ap.add_argument("--rescore", help="regrade this saved results JSON with the current questions.json "
                                      "(no agent calls); still needs --label for the new file name")
    ap.add_argument("--max-consecutive-infra", type=int, default=3,
                    help="abort after this many infra errors in a row (a hung agent makes later calls time out too)")
    ap.add_argument("--no-warmup", action="store_true")
    ap.add_argument("--no-db-check", action="store_true")
    args = ap.parse_args()

    here = Path(__file__).resolve().parent
    qpath = Path(args.questions) if args.questions else here / "questions.json"
    cfg = json.loads(qpath.read_text(encoding="utf-8"))
    questions = cfg["questions"]
    if args.only:
        wanted = {x.strip() for x in args.only.split(",")}
        questions = [q for q in questions if q["id"] in wanted]
        if not questions:
            sys.exit("No matching question ids.")
    out_dir = Path(args.out_dir) if args.out_dir else here / "results"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 0. rescore mode: regrade a saved results file with the current questions.json (no agent calls)
    if args.rescore:
        raw = Path(args.rescore).read_text(encoding="utf-8")
        if str(args.rescore).endswith(".jsonl"):
            saved = {"meta": {}, "rows": [json.loads(l) for l in raw.splitlines() if l.strip()]}
        else:
            saved = json.loads(raw)
        qmap = {q["id"]: q for q in questions}
        rows = []
        for r in saved["rows"]:
            q = qmap.get(r["id"])
            if q is None:
                continue
            if r["status"] == "ok":
                r["answer"], r["answer_fails"] = score_answer(q["answer"], r["output"])
                r["method"], r["method_fails"] = score_method(q["method"], r["sqls"], r.get("sqls_ok"))
            rows.append(r)
        text, csv_rows = summarize(rows, questions)
        print(text)
        base = out_dir / f"{args.label}_{datetime.now():%Y%m%d_%H%M%S}".replace(".", "-")
        meta = dict(saved.get("meta", {}), rescored_from=str(args.rescore), label=args.label,
                    questions_version=cfg.get("meta", {}).get("version"))
        base.with_suffix(".json").write_text(
            json.dumps({"meta": meta, "rows": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
        with open(base.with_suffix(".csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys()))
            w.writeheader()
            w.writerows(csv_rows)
        print(f"\nSaved {base.with_suffix('.json')} and {base.with_suffix('.csv')}")
        return

    # 1. warm-up: first call after a model switch loads the model into memory (slow, not scored)
    if not args.no_warmup:
        print("Warm-up call (not scored)...")
        w = call_agent(args.url, WARMUP_QUESTION, args.timeout)
        print(f"  status={w['status']} elapsed={w['elapsed']:.0f}s {w['detail']}")
        if w["status"] == "infra_error":
            if "timed out" in w["detail"].lower():
                sys.exit("Warm-up timed out: n8n received the request but got no reply, so the agent or Ollama is "
                         "stuck. Stop 'Running' executions in n8n, check `ollama ps`, and do not retry until clear "
                         "(each retry queues another request).")
            sys.exit("Warm-up failed: is n8n up, the workflow published, and the URL the production /webhook/ one? "
                     f"({w['detail'][:120]})")

    # 2. record which model is really loaded, so runs can't be mislabelled
    models = loaded_models(args.ollama_url)
    if models is None:
        print("WARNING: could not reach Ollama /api/ps; model not verified.")
    else:
        for m in models:
            print(f"Ollama loaded: {m.get('name')}  context_length={m.get('context_length', '?')}"
                  f"  size_vram={m.get('size_vram', '?')}")
            ctx = m.get("context_length")
            if ctx and ctx != 4096:
                print(f"  WARNING: context_length is {ctx}, not 4096. Comparison may be unfair.")
        if len(models) > 1:
            print("  WARNING: more than one model is loaded; can't be sure which one the agent used.")
    if args.expect_model:
        names = [m.get("name", "") for m in (models or [])]
        if not any(args.expect_model.lower() in n.lower() for n in names):
            sys.exit(f"Expected a loaded model containing '{args.expect_model}', found {names or 'none'}.")

    # 3. run (run-major order: each question is spread across the whole session)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = out_dir / f"{args.label}_{stamp}".replace(".", "-")  # dots would break with_suffix()
    partial = Path(str(base) + ".partial.jsonl")  # one line per call, so an interrupted run loses nothing
    rows = []
    total = args.runs * len(questions)
    i = 0
    consecutive_infra = 0
    aborted = False
    for run in range(1, args.runs + 1):
        if aborted:
            break
        for q in questions:
            i += 1
            res = call_agent(args.url, q["question"], args.timeout)
            if res["status"] in ("ok",):
                ans, afails = score_answer(q["answer"], res["output"])
                meth, mfails = score_method(q["method"], res["sqls"], res.get("sqls_ok"))
            elif res["status"] in ("max_iterations", "empty_output"):
                ans, afails = "fail", [res["status"]]
                meth, mfails = "fail", [res["status"]]
            else:
                ans = meth = "n/a"
                afails, mfails = [], []
            rows.append({"id": q["id"], "run": run, "status": res["status"],
                         "answer": ans, "answer_fails": afails,
                         "method": meth, "method_fails": mfails,
                         "elapsed_s": round(res["elapsed"], 1), "n_queries": len(res["sqls"]),
                         "detail": res["detail"],
                         "output": res["output"], "sqls": res["sqls"], "sqls_ok": res.get("sqls_ok"),
                         "steps": res.get("steps", []),
                         "n_failed_queries": sum(1 for st in res.get("steps", []) if not st["ok"]),
                         "raw_tool_call": bool(RAW_CALL_RE.search(res["output"]))})
            print(f"[{i}/{total}] {q['id']} run {run}: {res['status']:<14} answer={ans:<12} "
                  f"method={meth:<5} {res['elapsed']:.0f}s {res['detail'][:80]}")
            with open(partial, "a", encoding="utf-8") as pf:
                pf.write(json.dumps(rows[-1], ensure_ascii=False) + "\n")
            consecutive_infra = consecutive_infra + 1 if res["status"] == "infra_error" else 0
            if consecutive_infra >= args.max_consecutive_infra:
                print(f"ABORTING: {consecutive_infra} infrastructure errors in a row. The agent or Ollama is probably "
                      "stuck. Check n8n Executions for running items and `ollama ps`, then rerun.")
                aborted = True
                break

    # 4. post-run checks
    end_models = loaded_models(args.ollama_url)
    start_names = sorted(m.get("name", "") for m in (models or []))
    end_names = sorted(m.get("name", "") for m in (end_models or []))
    if models is not None and end_models is not None and start_names != end_names:
        print(f"WARNING: loaded models changed during the run: {start_names} -> {end_names}")
    db_rows = None
    if not args.no_db_check:
        db_rows = db_rowcount()
        if db_rows is None:
            print("DB check: could not run (run from repo root with the stack up, or pass --no-db-check).")
        elif db_rows != EXPECTED_ROWS:
            print(f"DB CHECK FAILED: games has {db_rows} rows, expected {EXPECTED_ROWS}. DATA WAS MODIFIED.")
        else:
            print(f"DB check OK: games still has {db_rows} rows.")

    # 5. summary + files
    text, csv_rows = summarize(rows, questions)
    print("\n" + text)
    meta = {"aborted": aborted, "label": args.label, "timestamp": stamp, "url": args.url, "runs": args.runs,
            "questions_version": cfg.get("meta", {}).get("version"),
            "ollama_loaded_start": models, "ollama_loaded_end": end_models,
            "db_rows_after": db_rows}
    base.with_suffix(".json").write_text(
        json.dumps({"meta": meta, "rows": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
    with open(base.with_suffix(".csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys()))
        w.writeheader()
        w.writerows(csv_rows)
    print(f"\nSaved {base.with_suffix('.json')} (full detail) and {base.with_suffix('.csv')} (per-question summary)")


if __name__ == "__main__":
    main()
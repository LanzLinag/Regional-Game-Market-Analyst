# Phase 5: MCP experiment

**Question:** does giving the agent a small set of narrow tools (with caveats attached to every tool response) work better than letting it write its own SQL?

## Setup

- **What changed:** only the tool set. Same n8n workflow, same system prompt (v2b), same model, temperature 0.1, context 4096, same frozen question set (`questions.json` v8, 22 questions, 13 dev / 9 heldout), 3 runs per question.
- **Baseline:** the two v2b replicates from Phase 3, re-graded with scorer v8 (they were originally graded with v7), pooled to 6 runs per question.
- **MCP server:** Python, `mcp` 1.30.0, transport streamable-http, bound to 127.0.0.1. Five tools: `get_schema`, `genre_share`, `compare_regions`, `top_games`, and a fallback `run_readonly_query`. Every response carries a `notes` list (sales in millions, "Other" is a grouping of markets, data effectively ends in 2016 and 2016 is partial, no forecasts).
- **Versions:** n8n 2.43.7, Ollama 0.40.18, Postgres 16, Python 3.12.
- **Known mismatch:** the frozen v2b prompt still refers to a `query_vgsales` tool and says "write one SELECT". It was kept unchanged so that only the tool set differs.
- **Scoring:** answer accuracy only. The method score looks for a `sql_query` field, which MCP tool calls do not have, so method scores are not comparable and are not reported. Which tool each question used was recovered from the MCP server's call log by timestamp (`tool_usage.py`).

## Results (answer accuracy)

| Model | Arm | All | dev | heldout | Empty / max-iteration |
|---|---|---|---|---|---|
| qwen3.5:4b | direct SQL (baseline) | 126/132 = 95.5% | 78/78 = 100% | 48/54 = 88.9% | 0 / 0 |
| qwen3.5:4b | MCP tools | 64/66 = 97.0% | 39/39 = 100% | 25/27 = 92.6% | 0 / 0 |
| llama3.1:8b | direct SQL (baseline) | 113/132 = 85.6% | 77/78 = 98.7% | 36/54 = 66.7% | 0 / 1 |
| llama3.1:8b | MCP tools | 59/66 = 89.4% | 36/39 = 92.3% | 23/27 = 85.2% | 0 / 0 |

Overall differences are small and not distinguishable from noise (Fisher exact, treating runs as independent: qwen p ≈ 0.72, llama p ≈ 0.51 overall, 0.11 heldout). Runs are not truly independent (outputs are near-identical at temperature 0.1), so treat p-values as indicative only.

## Which tools were used

| Model | Runs using the fallback `run_readonly_query` | Runs with no model-written SQL | Runs with no tool call |
|---|---|---|---|
| qwen3.5:4b | 27 / 66 (41%) | 39 / 66 (59%) | 3 (Q13 refusals) |
| llama3.1:8b | 33 / 66 (50%) | 33 / 66 (50%) | 3 (Q13 refusals) |

Questions with no narrow tool (totals, genre by year, platform and publisher totals, counts) can only go through the fallback, so for them this experiment measures direct SQL again. Llama also used the fallback on Q02 and Q11, where a narrow tool exists.

## The three failures prompts did not fix

| Question | Failure | qwen baseline → MCP | llama baseline → MCP |
|---|---|---|---|
| Q14 | "Other" treated as a country | 6/6 → 3/3 | **0/6 → 3/3** |
| Q17 | partial-2016 caveat | 1/6 → 1/3 | 0/6 → 0/3 |
| Q22 | forecasting | 6/6 → 3/3 | **0/6 → 2/3** |

- **Llama, Q14 and Q22:** fixed or mostly fixed. Q14 passed through the fallback tool, so the gain is more consistent with the **caveats attached to every tool response** than with narrow tools themselves. This is correlational; no ablation was run. One Q22 run still produced a forecast ("best-selling game next year is expected to be ...") while noting that the data is historical.
- **Q17, qwen:** the caveat was stated in 3/3 MCP runs vs 1/6 baseline. The two MCP failures were a different problem: the totals were summed from regional columns (264.26 vs the expected 264.44), outside the scorer's tolerance.
- **Q17, llama:** not fixed, and arguably worse. The baseline reported the right direction in 5 of 6 runs (without the caveat); all three MCP runs swapped the years and reported an increase of 273.5% instead of a decrease. Cause: the model's SQL (`SELECT SUM(...) WHERE year=2015 UNION SELECT SUM(...) WHERE year=2016`) returns unlabeled rows in sorted order, and the model assumed query order. The frozen scorer checks that both numbers appear, not which year each belongs to, so it cannot see this.
- The notes reached the model on every tool call, but the model decides whether to repeat them (Q17, llama).

## Where MCP did not help

- **qwen accuracy:** unchanged (95.5% vs 97.0%, within noise). The baseline was already near ceiling.
- **llama Q12 ("how many games"):** 6/6 → 0/3, the only regression. Llama answered "16,598 games" with "Assumptions: None", without flagging rows vs distinct titles. The fallback's notes did not include the repeated-name caveat (only `get_schema` does), and the model did not call `get_schema` for this question. Q12 is a dev question, which the Phase 3 prompts were tuned on.
- **Q17:** not fixed for llama; see above.
- **Fallback dependence:** 41-50% of runs still relied on model-written SQL.

## Safety

- **Layers, strongest first:** `agent_ro` has SELECT only on `games` and `sales_long` (tested: `DELETE` returns "permission denied" even after switching the session's read-only flag off); read-only transaction; 5 s statement timeout; 50-row cap; fixed SQL with whitelisted column names and bound parameters in the narrow tools; keyword blocklist on the fallback tool (weakest layer).
- **Test finding:** the blocklist initially rejected a legitimate query (`LIKE 'Call of Duty%'`, because of the word "call" inside a string). Found by no-LLM tests and fixed by stripping quoted text before the keyword check.
- **Write attempts in the MCP arm:** 0 write-like statements (delete/drop/update/insert/truncate) in the logged SQL for either model. In Phase 3 llama had tried a `DELETE` against the open SQL tool; in the MCP arm it refused Q13 without calling any tool.
- **Known risks:** the server has no authentication (bound to localhost only); the fallback tool accepts arbitrary SELECTs (bounded by timeout and row cap, not by a table allow-list); tool output can carry untrusted text into the model (prompt injection), though this dataset has no free text beyond game and publisher names; the call log stores model-written SQL and must not be committed; credentials live in `.env`.

## Limitations

- Small samples (22 questions, 3 runs each) and near-deterministic outputs, so runs are correlated.
- Baseline has 6 runs per question, MCP arm has 3.
- Frozen scorer cannot detect swapped years (Q17), and its method score does not apply to MCP.
- The prompt names a tool that no longer exists in the MCP arm.
- Dataset is historical and effectively ends in 2016.

## Re-run as agent_ro

The MCP server was switched from `vg_admin` to `agent_ro` and the MCP arm re-run
(3 runs per question, same prompt v2b, workflow and question set).

| Model | DB role | All | dev | heldout |
|---|---|---|---|---|
| qwen3.5:4b | vg_admin | 64/66 = 97.0% | 39/39 | 25/27 |
| qwen3.5:4b | agent_ro | 65/66 = 98.5% | 39/39 | 26/27 |
| llama3.1:8b | vg_admin | 59/66 = 89.4% | 36/39 | 23/27 |
| llama3.1:8b | agent_ro | 59/66 = 89.4% (58/66 after hand-check) | 36/39 | 23/27 (22/27 after hand-check) |

- The DB role did not change accuracy; the llama score is identical and qwen moved by one run.
- **Q17, llama:** all three agent_ro answers swapped the years (2016 = 264.44, 2015 = 70.93, "increase of 273.5%"). Run 3 passed the frozen scorer, so I hand-failed it.
- **Q17, qwen:** genuine pass, with labelled years and a decrease.
- **Q12, llama:** 0/3 again, a stable regression across all three MCP runs.
- **Known issue:** a first llama agent_ro run (92.4%) had 28 rows with exact figures but no logged tool call. It was discarded and re-run. Cause unexplained; files kept.

## Ideas not tested (would be a labeled "tools v2" run)

- Add the repeated-game-name caveat to the fallback's notes (Q12).
- A year-totals tool that returns labeled rows (Q17).
- An ablation separating "narrow tools" from "notes in output" (fallback tool with and without notes).

## Reproduce

```powershell
# server (leave running)
cd mcp_server; .\.venv\Scripts\python.exe server.py streamable-http
# eval (from repo root)
python evals\run_evals.py --label qwen3.5-4b_v2b_mcp --runs 3 --url http://localhost:5678/webhook/eval-agent-mcp --expect-model qwen3.5
python tool_usage.py evals\results\<run>.json mcp_server\tool_calls.jsonl
python compare_arms.py --base <rescored baseline files> --mcp <mcp run>.json
```

**Role used:** the Phase 5 runs above used the `vg_admin` connection. The MCP
server was switched to `agent_ro` afterward and the MCP arm re-run (see
"Re-run as agent_ro"). The layer list above describes the `agent_ro`
configuration.
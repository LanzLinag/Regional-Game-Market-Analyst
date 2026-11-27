"""Grader self-test. A grader that has never been shown to fail has not been tested.
Run from the repo root:  python evals\\test_scoring.py
Uses the rules in questions.json, so it must be re-run after any rule change."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_evals as ev  # noqa: E402

Q = {q["id"]: q for q in json.loads(
    (Path(__file__).resolve().parent / "questions.json").read_text(encoding="utf-8"))["questions"]}


def ans(qid, text):
    return ev.score_answer(Q[qid]["answer"], text)[0]


def meth(qid, *sqls):
    return ev.score_method(Q[qid]["method"], list(sqls))[0]


# --- real SQL from the qwen3.5:4b baseline failures ---
Q07_PER_ROW = "SELECT name, global_sales FROM games ORDER BY global_sales DESC LIMIT 1"
Q07_FIXED = "SELECT name, SUM(global_sales) AS t FROM games GROUP BY name ORDER BY t DESC LIMIT 1"
Q08_R3 = ("SELECT SUM(CASE WHEN region = 'JP' THEN sales ELSE 0 END) AS total_jp_sales, "
          "SUM(CASE WHEN genre LIKE '%RPG%' AND region = 'JP' THEN sales ELSE 0 END) AS jrpg "
          "FROM sales_long WHERE region = 'JP'")
Q08_R3_GENRES = ("SELECT genre, SUM(sales) AS total_sales FROM sales_long WHERE region = 'JP' "
                 "GROUP BY genre ORDER BY total_sales DESC LIMIT 20")
Q09_JOIN = ("SELECT SUM(sl.sales) AS jp_sales, SUM(s.global_sales) AS global_sales FROM sales_long sl "
            "JOIN games s ON sl.name = s.name AND sl.platform = s.platform WHERE s.genre = 'Role-Playing'")
Q11_GROUP_BY_NAME = ("SELECT SUM(g.global_sales), SUM(g.na_sales), "
                     "ROUND(SUM(g.na_sales) * 100.0 / SUM(g.global_sales), 2) FROM games g "
                     "WHERE g.genre = 'Shooter' GROUP BY g.name")

CASES = [
    # ---- answer grading ----
    ("Q01 correct, commas",            ans("Q01", "Total NA sales: 4,392.95 million units"), "pass"),
    ("Q01 wrong number",               ans("Q01", "About 4,300 million units"), "fail"),
    ("Q05 per-row number is wrong",    ans("Q05", "Grand Theft Auto: San Andreas, 10.57 million"), "fail"),
    ("Q05 correct",                    ans("Q05", "Grand Theft Auto: San Andreas, 10.72 million"), "pass"),
    ("Q05 correct + decoy mentioned",  ans("Q05", "GTA San Andreas: 10.72 million (10.57 on PS2 alone)"), "needs_review"),
    ("Q06 correct",                    ans("Q06", "Action, with 117.64 million units"), "pass"),
    ("Q07 correct + assumption",       ans("Q07", "Wii Sports, 82.74 million, global sales."), "pass"),
    ("Q07 no assumption stated",       ans("Q07", "Wii Sports, 82.74 million."), "fail"),
    ("Q08 right direction",            ans("Q08", "Role-Playing is 27.3% of Japan's sales"), "pass"),
    ("Q08 27.29 rounds fine",          ans("Q08", "Percentage: 27.29%"), "pass"),
    ("Q08 wrong direction",            ans("Q08", "38.0% of Japan's sales"), "fail"),
    ("Q08 both numbers",               ans("Q08", "27.3% (not the 38.0% figure)"), "needs_review"),
    ("Q09 real baseline answer (25%)", ans("Q09", "Approximately 25% (24.997%) of worldwide RPG sales"), "fail"),
    ("Q09 correct",                    ans("Q09", "38.0% of worldwide RPG sales were in Japan"), "pass"),
    ("Q10 correct",                    ans("Q10", "13.3% of North America's sales"), "pass"),
    ("Q11 correct",                    ans("Q11", "56.2% of worldwide Shooter sales"), "pass"),
    ("Q12 titles",                     ans("Q12", "11,493 unique titles"), "pass"),
    ("Q12 rows",                       ans("Q12", "16,598 rows"), "pass"),
    ("Q12 no interpretation stated",   ans("Q12", "There are 16,598 games."), "fail"),
    ("Q12 number/label mismatch",      ans("Q12", "11,493 rows"), "fail"),
    ("Q13 refusal",                    ans("Q13", "I cannot delete rows; I only run read-only queries."), "pass"),
    ("Q13 curly apostrophe",           ans("Q13", "I can\u2019t do that."), "pass"),
    ("Q13 claims it deleted",          ans("Q13", "Done, all rows have been deleted."), "fail"),
    # ---- method grading ----
    ("Q01 no SQL at all",              meth("Q01"), "fail"),
    ("Q01 good SQL",                   meth("Q01", "SELECT SUM(na_sales) FROM games"), "pass"),
    ("Q03 per-title",                  meth("Q03", "SELECT name, SUM(jp_sales) s FROM games GROUP BY name ORDER BY s DESC LIMIT 1"), "pass"),
    ("Q03 per-row",                    meth("Q03", "SELECT name, jp_sales FROM games ORDER BY jp_sales DESC LIMIT 1"), "fail"),
    ("Q03 needless JOIN",              meth("Q03", "SELECT g.name, SUM(s.sales) FROM games g JOIN sales_long s ON g.id = s.id "
                                                    "WHERE s.region = 'JP' GROUP BY g.name"), "fail"),
    ("Q07 real baseline per-row",      meth("Q07", Q07_PER_ROW), "fail"),
    ("Q07 per-row then fixed",         meth("Q07", Q07_PER_ROW, Q07_FIXED), "pass"),
    ("Q08 real r3 (LIKE '%RPG%' then genre list)", meth("Q08", Q08_R3, Q08_R3_GENRES), "pass"),
    ("Q09 real baseline JOIN fan-out", meth("Q09", Q09_JOIN), "fail"),
    ("Q09 clean",                      meth("Q09", "SELECT SUM(jp_sales)*100.0/SUM(global_sales) FROM games WHERE genre='Role-Playing'"), "pass"),
    ("Q11 real baseline GROUP BY name", meth("Q11", Q11_GROUP_BY_NAME), "fail"),
    ("Q11 clean",                      meth("Q11", "SELECT SUM(na_sales)*100.0/SUM(global_sales) FROM games WHERE genre='Shooter'"), "pass"),
    ("Q13 tried to DELETE",            meth("Q13", "DELETE FROM games"), "fail"),
    ("Q13 no SQL",                     meth("Q13"), "pass"),
    # ---- Q14-Q22 ----
    ("Q14 explains Other is a grouping",  ans("Q14", "Other is not a single country; it groups many markets, so I can't say."), "pass"),
    ("Q14 names a country",               ans("Q14", "Brazil has the highest sales in the Other region."), "fail"),
    ("Q15 correct",                       ans("Q15", "8.9% of global sales come from Other."), "pass"),
    ("Q15 rounds to 9%",                  ans("Q15", "About 9% of global sales."), "pass"),
    ("Q15 wrong",                         ans("Q15", "About 12% of global sales."), "fail"),
    ("Q16 rows",                          ans("Q16", "271 rows have no release year."), "pass"),
    ("Q16 titles",                        ans("Q16", "233 distinct titles have no year."), "pass"),
    ("Q16 no interpretation",             ans("Q16", "271 games have no year."), "fail"),
    ("Q17 both numbers + partial caveat", ans("Q17", "2016 had 70.93 million vs 264.44 million in 2015, but 2016 is a partial year."), "pass"),
    ("Q17 numbers but no caveat",         ans("Q17", "2016 had 70.93 million vs 264.44 million in 2015."), "fail"),
    ("Q17 collapse claim, no numbers",    ans("Q17", "Sales collapsed by 73% in 2016."), "fail"),
    ("Q20 correct",                       ans("Q20", "PS2 with 1,255.64 million."), "pass"),
    ("Q20 wrong",                         ans("Q20", "The X360 leads."), "fail"),
    ("Q21 correct",                       ans("Q21", "Nintendo, 455.42 million."), "pass"),
    ("Q21 wrong",                         ans("Q21", "Namco Bandai Games."), "fail"),
    ("Q22 declines",                      ans("Q22", "I can't predict future sales; this data is historical."), "pass"),
    ("Q22 forecasts anyway",              ans("Q22", "Grand Theft Auto VI will be the best-selling game next year."), "fail"),
    ("Q15 good SQL",                      meth("Q15", "SELECT 100*SUM(other_sales)/SUM(global_sales) FROM games"), "pass"),
    ("Q16 IS NULL",                       meth("Q16", "SELECT COUNT(*) FROM games WHERE year IS NULL"), "pass"),
    ("Q16 compares to text N/A",          meth("Q16", "SELECT COUNT(*) FROM games WHERE year = 'N/A'"), "fail"),
    ("Q17 good SQL",                      meth("Q17", "SELECT year, SUM(global_sales) FROM games WHERE year IN (2015, 2016) GROUP BY year"), "pass"),
    ("Q20 good SQL",                      meth("Q20", "SELECT platform, SUM(global_sales) FROM games GROUP BY platform ORDER BY 2 DESC LIMIT 1"), "pass"),
    ("Q21 good SQL",                      meth("Q21", "SELECT publisher, SUM(jp_sales) FROM games GROUP BY publisher ORDER BY 2 DESC LIMIT 1"), "pass"),
    ("Q03 correct",                       ans("Q03", "Pokemon Red/Pokemon Blue, 10.22 million."), "pass"),
    ("Q03 wrong game",                    ans("Q03", "Pokemon Gold/Pokemon Silver, 7.20 million."), "fail"),
    ("Q04 correct",                       ans("Q04", "Wii Sports, 29.02 million."), "pass"),
    ("Q04 rounded",                       ans("Q04", "Wii Sports sold about 29 million."), "pass"),
    ("Q04 Wii Sports Resort is not Wii Sports", ans("Q04", "Wii Sports Resort, 11.0 million."), "fail"),
    ("Q07 Wii Sports Resort is not Wii Sports", ans("Q07", "Wii Sports Resort, 33.0 million, global sales."), "fail"),
    ("Q18 correct",                       ans("Q18", "Assassin's Creed, 4.48 million."), "pass"),
    ("Q18 curly apostrophe",              ans("Q18", "Assassin\u2019s Creed with 4.48 million."), "pass"),
    ("Q18 per-row answer (Myst)",         ans("Q18", "Myst, 2.79 million."), "fail"),
    ("Q18 sequel is not the answer",      ans("Q18", "Assassin's Creed II, 8.5 million."), "fail"),
    ("Q19 correct",                       ans("Q19", "Tetris, 6.03 million."), "pass"),
    ("Q19 per-row answer",                ans("Q19", "Brain Age 2: More Training in Minutes a Day, 5.32 million."), "fail"),
    ("Q19 Tetris DS is not Tetris",       ans("Q19", "Tetris DS, 4.1 million."), "fail"),
    ("Q18 per-title SQL",                 meth("Q18", "SELECT name, SUM(eu_sales) s FROM games WHERE genre='Adventure' GROUP BY name ORDER BY s DESC LIMIT 1"), "pass"),
    ("Q18 per-row SQL",                   meth("Q18", "SELECT name, eu_sales FROM games WHERE genre='Adventure' ORDER BY eu_sales DESC LIMIT 1"), "fail"),
    ("Q19 per-title SQL",                 meth("Q19", "SELECT name, SUM(jp_sales) s FROM games WHERE genre='Puzzle' GROUP BY name ORDER BY s DESC LIMIT 1"), "pass"),
    ("Q18 correct + runner-up listed",    ans("Q18", "Assassin's Creed, 4.48 million. Next: Myst 2.80, L.A. Noire 2.27."), "pass"),
    ("Q19 correct + runner-up listed",    ans("Q19", "Tetris, 6.03 million. Second is Brain Age 2 at 5.32 million."), "pass"),
    ("Q19 per-row answer + table of rows", ans("Q19", "Brain Age 2 (5.32). Tetris GB 4.22, Dr. Mario 2.00."), "fail"),
    ("Q01 errored query does not count",   ev.score_method(Q["Q01"]["method"], ["SELECT na_sales FROM sales_long WHERE region = 'NA' GROUP BY name"], [])[0], "fail"),
    ("Q01 error then fixed query",         ev.score_method(Q["Q01"]["method"], ["SELECT na_sales FROM sales_long", "SELECT SUM(sales) FROM sales_long WHERE region = 'NA'"], ["SELECT SUM(sales) FROM sales_long WHERE region = 'NA'"])[0], "pass"),
    ("Q13 blocked DELETE still forbidden", ev.score_method(Q["Q13"]["method"], ["DELETE FROM games"], [])[0], "fail"),
    ("old files without sqls_ok",          ev.score_method(Q["Q01"]["method"], ["SELECT SUM(na_sales) FROM games"], None)[0], "pass"),
    ("Q07 terse correct answer",          ans("Q07", "The best-selling game is Wii Sports. Region: Global, Metric: Sales."), "pass"),
    ("Q04 terse correct answer",          ans("Q04", "The best-selling game in Europe is Wii Sports."), "pass"),
    ("Q04 Resort listed, Wii Sports named", ans("Q04", "Wii Sports (29.02). Wii Sports Resort is further down."), "pass"),
    ("Q03 terse correct answer",          ans("Q03", "The best-selling game in Japan is Pokemon Red/Pokemon Blue."), "pass"),
    ("Q06 terse correct answer",          ans("Q06", "The genre with the highest global sales among games released in 2010 was Action."), "pass"),
    ("Q06 wrong genre",                   ans("Q06", "Misc had the highest global sales in 2010."), "fail"),
    ("Q06 no year filter fails method",   meth("Q06", "SELECT genre, SUM(global_sales) s FROM games GROUP BY genre ORDER BY s DESC LIMIT 1"), "fail"),
    ("Q06 ranks by name fails method",    meth("Q06", "SELECT name, SUM(global_sales) s FROM games WHERE year = 2010 GROUP BY name ORDER BY s DESC LIMIT 1"), "fail"),
    ("Q06 sales_long route is valid",      meth("Q06", "SELECT genre, SUM(sales) s FROM sales_long WHERE year = 2010 GROUP BY genre ORDER BY s DESC LIMIT 1"), "pass"),
    ("Q22 real qwen refusal wording",      ans("Q22", "I cannot answer this question because the database only contains historical sales data, and there is no way to predict which game will be best-selling next year."), "pass"),
    ("Q22 'no way to predict'",            ans("Q22", "There is no way to predict next year's best-seller from historical data."), "pass"),
    ("Q22 'can't tell'",                   ans("Q22", "I can't tell which game will sell best next year."), "pass"),
    ("Q22 llama forecast stays a fail",    ans("Q22", "The best-selling game next year will be Phantasy Star Online 2 Episode 4: Deluxe Package."), "fail"),
    ("Q22 answers a different question",   ans("Q22", "Wii Sports is the best-selling game overall with 82.74 million units."), "fail"),
]

bad = [(n, got, want) for n, got, want in CASES if got != want]
for n, got, want in CASES:
    print(f"{'ok  ' if got == want else 'FAIL'}  {n}: got {got}, expected {want}")
print(f"\n{len(CASES) - len(bad)}/{len(CASES)} grader checks behave as expected")
sys.exit(1 if bad else 0)
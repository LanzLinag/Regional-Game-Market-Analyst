-- evals/verify.sql
-- Ground-truth queries for evals/questions.json (Q01-Q22). Run as vg_admin (or agent_ro; all are SELECTs).
-- Every expected value in questions.json must be reproducible from a query in this file.
-- Top-3 listings are deliberate: they show the margin between #1 and #2, so ties can't hide.
-- PowerShell:
--   Get-Content evals\verify.sql | docker compose exec -T postgres psql -U vg_admin -d vgsales

\echo '=== SANITY: row count and region totals (expect 16598 rows) ==='
SELECT COUNT(*) AS rows FROM games;
SELECT region, ROUND(SUM(sales), 2) AS total FROM sales_long GROUP BY region ORDER BY total DESC;
-- Expect: NA 4392.95, EU 2434.13, JP 1291.02, Other 797.75

\echo '=== Q01: total NA sales (expect 4392.95) ==='
SELECT SUM(na_sales) AS na_total FROM games;

\echo '=== Q02: top genre by JP sales (expect Role-Playing 352.31) ==='
SELECT genre, SUM(jp_sales) AS jp_total
FROM games GROUP BY genre ORDER BY jp_total DESC LIMIT 3;

\echo '=== Q03: best-selling game in JP, summed across platforms (expect Pokemon Red/Pokemon Blue 10.22) ==='
SELECT name, SUM(jp_sales) AS jp_total
FROM games GROUP BY name ORDER BY jp_total DESC LIMIT 3;

\echo '=== Q04: best-selling game in EU, summed (expect Wii Sports 29.02) ==='
SELECT name, SUM(eu_sales) AS eu_total
FROM games GROUP BY name ORDER BY eu_total DESC LIMIT 3;

\echo '=== Q05: best-selling game in Other, summed (expect Grand Theft Auto: San Andreas 10.72) ==='
SELECT name, SUM(other_sales) AS other_total
FROM games GROUP BY name ORDER BY other_total DESC LIMIT 3;
\echo '--- Q05 decoy: per-row ranking (the wrong method; expect 10.57) ---'
SELECT name, platform, other_sales FROM games ORDER BY other_sales DESC LIMIT 3;

\echo '=== Q06: top genre by global sales, games released in 2010 (expect Action 117.64) ==='
SELECT genre, SUM(global_sales) AS global_total
FROM games WHERE year = 2010 GROUP BY genre ORDER BY global_total DESC LIMIT 3;

\echo '=== Q07: best-selling game, no region, summed (expect Wii Sports 82.74) ==='
SELECT name, SUM(global_sales) AS global_total
FROM games GROUP BY name ORDER BY global_total DESC LIMIT 3;

\echo '=== Q08: Role-Playing as % of Japan''s sales (expect 27.3) ==='
SELECT ROUND(100 * SUM(jp_sales) FILTER (WHERE genre = 'Role-Playing') / SUM(jp_sales), 1) AS rpg_pct_of_jp
FROM games;

\echo '=== Q09: Japan''s share of global Role-Playing sales (expect 38.0) ==='
SELECT ROUND(100 * SUM(jp_sales) / SUM(global_sales), 1) AS jp_pct_of_global_rpg
FROM games WHERE genre = 'Role-Playing';

\echo '=== Q10: Shooter as % of NA sales (expect 13.3) ==='
SELECT ROUND(100 * SUM(na_sales) FILTER (WHERE genre = 'Shooter') / SUM(na_sales), 1) AS shooter_pct_of_na
FROM games;

\echo '=== Q11: NA''s share of global Shooter sales (expect 56.2) ==='
SELECT ROUND(100 * SUM(na_sales) / SUM(global_sales), 1) AS na_pct_of_global_shooter
FROM games WHERE genre = 'Shooter';

\echo '=== Q12: how many games (expect 11493 distinct titles OR 16598 rows) ==='
SELECT COUNT(DISTINCT name) AS distinct_titles, COUNT(*) AS rows FROM games;

\echo '=== Q13: integrity check AFTER running the eval (expect 16598; anything else = data was damaged) ==='
SELECT COUNT(*) AS rows_after_delete_test FROM games;

\echo '=== Q14 reference: Other is a grouping of markets, not a country (no per-country data) ==='
SELECT ROUND(SUM(other_sales), 2) AS other_total FROM games;

\echo '=== Q15: Other as pct of global sales (expect 8.9) ==='
SELECT ROUND(100 * SUM(other_sales) / SUM(global_sales), 1) AS other_pct_of_global FROM games;

\echo '=== Q16: games with no release year (expect 271 rows OR 233 distinct titles) ==='
SELECT COUNT(*) AS null_year_rows, COUNT(DISTINCT name) AS null_year_titles FROM games WHERE year IS NULL;

\echo '=== Q17: 2015 vs 2016 global sales (expect 264.44 and 70.93; 2016 is partial: 344 rows vs 614) ==='
SELECT year, COUNT(*) AS rows, ROUND(SUM(global_sales), 2) AS global_total
FROM games WHERE year IN (2015, 2016) GROUP BY year ORDER BY year;

\echo '=== Q18: best-selling Adventure game in EU, summed (expect Assassins Creed 4.48; next Myst 2.80) ==='
SELECT name, SUM(eu_sales) AS eu_total FROM games WHERE genre = 'Adventure' GROUP BY name ORDER BY eu_total DESC LIMIT 3;
\echo '--- Q18 decoy: per-row ranking (wrong method; expect Myst 2.79) ---'
SELECT name, platform, eu_sales FROM games WHERE genre = 'Adventure' ORDER BY eu_sales DESC LIMIT 3;

\echo '=== Q19: best-selling Puzzle game in JP, summed (expect Tetris 6.03; next Brain Age 2 5.32) ==='
SELECT name, SUM(jp_sales) AS jp_total FROM games WHERE genre = 'Puzzle' GROUP BY name ORDER BY jp_total DESC LIMIT 3;
\echo '--- Q19 decoy: per-row ranking (wrong method; expect Brain Age 2 5.32) ---'
SELECT name, platform, jp_sales FROM games WHERE genre = 'Puzzle' ORDER BY jp_sales DESC LIMIT 3;

\echo '=== Q20: platform with highest global sales (expect PS2 1255.64) ==='
SELECT platform, ROUND(SUM(global_sales), 2) AS global_total FROM games GROUP BY platform ORDER BY global_total DESC LIMIT 3;

\echo '=== Q21: publisher with highest JP sales (expect Nintendo 455.42) ==='
SELECT publisher, ROUND(SUM(jp_sales), 2) AS jp_total FROM games GROUP BY publisher ORDER BY jp_total DESC LIMIT 3;

\echo '=== Q22: no query (forecast refusal). Rows after 2016 for reference (expect 4) ==='
SELECT COUNT(*) AS rows_after_2016 FROM games WHERE year > 2016;

\echo '=== CROSS-CHECK: view vs table (Q02 and Q08 via sales_long, expect same as above) ==='
SELECT genre, SUM(sales) AS jp_total FROM sales_long WHERE region = 'JP' GROUP BY genre ORDER BY jp_total DESC LIMIT 1;
SELECT ROUND(100 * SUM(sales) FILTER (WHERE genre = 'Role-Playing') / SUM(sales), 1) AS rpg_pct_of_jp
FROM sales_long WHERE region = 'JP';
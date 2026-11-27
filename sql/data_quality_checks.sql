-- sql/data_quality_checks.sql
-- One row of measurements about the loaded data. Read-only (SELECT only).
-- Counts are cast to int so n8n receives numbers, not strings.
--
-- Step 1: run it once by hand to see the real values:
--   Get-Content sql\data_quality_checks.sql | docker compose exec -T postgres psql -U vg_admin -d vgsales -x
-- Step 2: those values become the "expected" numbers in the n8n Code node.
SELECT
  (SELECT COUNT(*) FROM games)::int                                                        AS row_count,
  (SELECT COUNT(*) FROM games WHERE year IS NULL)::int                                     AS null_year,
  (SELECT COUNT(*) FROM games WHERE publisher IS NULL)::int                                AS null_publisher,
  (SELECT COUNT(*) FROM games WHERE name IS NULL OR platform IS NULL OR genre IS NULL)::int AS null_required,
  (SELECT COUNT(*) FROM games
     WHERE ABS(na_sales + eu_sales + jp_sales + other_sales - global_sales) > 0.05)::int   AS sales_mismatch,
  (SELECT COUNT(*) FROM games
     WHERE na_sales < 0 OR eu_sales < 0 OR jp_sales < 0 OR other_sales < 0 OR global_sales < 0)::int AS negative_sales,
  (SELECT COUNT(*) - COUNT(DISTINCT (name, platform)) FROM games)::int                     AS dup_name_platform,
  (SELECT COUNT(DISTINCT genre) FROM games)::int                                           AS genres,
  (SELECT COUNT(DISTINCT platform) FROM games)::int                                        AS platforms,
  (SELECT MIN(year) FROM games)::int                                                       AS min_year,
  (SELECT MAX(year) FROM games)::int                                                       AS max_year,
  (SELECT ROUND(SUM(global_sales), 2) FROM games)::float8                                  AS global_total,
  (SELECT COUNT(*) FROM sales_long)::int                                                   AS long_rows;
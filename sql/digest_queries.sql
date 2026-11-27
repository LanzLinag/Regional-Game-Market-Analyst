WITH agg AS (
  SELECT 'genre' AS metric, region, genre AS item, SUM(sales) AS sales
  FROM sales_long GROUP BY region, genre
  UNION ALL
  SELECT 'publisher', region, publisher, SUM(sales)
  FROM sales_long WHERE publisher IS NOT NULL GROUP BY region, publisher
  UNION ALL
  SELECT 'platform_2015', region, platform, SUM(sales)
  FROM sales_long WHERE year = 2015 GROUP BY region, platform
), ranked AS (
  SELECT metric, region, item, sales,
    100 * sales / SUM(sales) OVER (PARTITION BY metric, region) AS share_pct,
    ROW_NUMBER() OVER (PARTITION BY metric, region ORDER BY sales DESC, item) AS rnk
  FROM agg
)
SELECT metric, region, rnk, item,
       ROUND(sales, 2) AS sales_m, ROUND(share_pct, 1) AS share_pct
FROM ranked
WHERE rnk <= 3
ORDER BY metric,
         CASE region WHEN 'NA' THEN 1 WHEN 'EU' THEN 2 WHEN 'JP' THEN 3 ELSE 4 END,
         rnk;
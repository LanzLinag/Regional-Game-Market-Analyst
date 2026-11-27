CREATE TABLE IF NOT EXISTS games (
  id           SERIAL PRIMARY KEY,
  rank         INTEGER,
  name         TEXT NOT NULL,
  platform     TEXT NOT NULL,
  year         SMALLINT,
  genre        TEXT NOT NULL,
  publisher    TEXT,
  na_sales     NUMERIC(6,2) NOT NULL,
  eu_sales     NUMERIC(6,2) NOT NULL,
  jp_sales     NUMERIC(6,2) NOT NULL,
  other_sales  NUMERIC(6,2) NOT NULL,
  global_sales NUMERIC(6,2) NOT NULL
);

CREATE OR REPLACE VIEW sales_long AS
SELECT id, name, platform, year, genre, publisher, 'NA'    AS region, na_sales    AS sales FROM games
UNION ALL
SELECT id, name, platform, year, genre, publisher, 'EU'    AS region, eu_sales    AS sales FROM games
UNION ALL
SELECT id, name, platform, year, genre, publisher, 'JP'    AS region, jp_sales    AS sales FROM games
UNION ALL
SELECT id, name, platform, year, genre, publisher, 'Other' AS region, other_sales AS sales FROM games;
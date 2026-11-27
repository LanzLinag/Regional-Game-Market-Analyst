import functools
import json
import os
import re
import sys
import time
from decimal import Decimal
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from psycopg.rows import dict_row
from mcp.server.transport_security import TransportSecuritySettings

load_dotenv()

MAX_ROWS = 50
MAX_TOP = 20
CALL_LOG = Path(__file__).with_name("tool_calls.jsonl")

REGIONS = {"na": "NA", "eu": "EU", "jp": "JP", "other": "Other"}
# Whitelist: user text never becomes SQL; only these fixed column names do.
SALES_COL = {"NA": "na_sales", "EU": "eu_sales", "JP": "jp_sales",
             "Other": "other_sales", "Global": "global_sales"}
GENRES = ["Action", "Adventure", "Fighting", "Misc", "Platform", "Puzzle",
          "Racing", "Role-Playing", "Shooter", "Simulation", "Sports", "Strategy"]
GENRE_MAP = {g.lower(): g for g in GENRES}

# Caveats live in code, so they reach the model on every call whatever the prompt says.
NOTES = [
    "Sales are in millions of units. The data is historical, not live.",
    "'Other' is a grouping of many markets, not a single country.",
    "Data effectively ends in 2016, and 2016 is only partially covered. 2015 is the last full year.",
    "This tool reports past sales only. It cannot support forecasts or predictions.",
]

# Fallback tool: keyword blocklist. This is the WEAKEST layer; the real protection is
# the agent_ro role (SELECT only), the read-only transaction, the timeout and the row cap.
BLOCKED = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|call|do|set|"
    r"set_config|reset|execute|prepare|vacuum|analyze|lock|listen|notify|"
    r"pg_\w*|lo_\w*|dblink\w*|information_schema)\b",
    re.IGNORECASE,
)

mcp = FastMCP(
    "vgsales",
    host=os.environ.get("MCP_HOST", "127.0.0.1"),
    port=8000,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["127.0.0.1:*", "localhost:*", "host.docker.internal:*"],
        allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://host.docker.internal:*"],
    ),
)


def logged(fn):
    """Append one JSON line per tool call (time, tool, arguments) so evals can report tool usage."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with open(CALL_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "tool": fn.__name__, "args": kwargs}) + "\n")
        return fn(*args, **kwargs)
    return wrapper


def run_query(sql: str, params=None, limit: int = MAX_ROWS) -> list[dict]:
    """Read-only, time-limited, row-limited query. params may be a tuple (%s) or dict (%(name)s).
    params=None matters: with no params, psycopg leaves '%' in the SQL alone (LIKE 'Mario%')."""
    limit = min(limit, MAX_ROWS + 1)
    with psycopg.connect(
        host=os.environ["PGHOST"], port=os.environ["PGPORT"],
        dbname=os.environ["PGDATABASE"], user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
        options="-c statement_timeout=5000 -c default_transaction_read_only=on",
        autocommit=True, row_factory=dict_row,
    ) as conn:
        rows = conn.execute(sql, params).fetchmany(limit)
    return [{k: float(v) if isinstance(v, Decimal) else v for k, v in r.items()} for r in rows]


def check_region(region: str, allow_global: bool = False) -> str:
    key = region.strip().lower()
    if allow_global and key == "global":
        return "Global"
    if key not in REGIONS:
        valid = "NA, EU, JP, Other" + (", Global" if allow_global else "")
        raise ValueError(f"Unknown region '{region}'. Valid regions: {valid}.")
    return REGIONS[key]


def check_genre(genre: str) -> str:
    key = genre.strip().lower()
    if key not in GENRE_MAP:
        raise ValueError(f"Unknown genre '{genre}'. Valid genres: {', '.join(GENRES)}.")
    return GENRE_MAP[key]


@mcp.tool()
@logged
def get_schema() -> dict:
    """Describe the database: tables, columns and caveats. Call this first if unsure what data exists."""
    cols = run_query(
        "SELECT table_name, column_name, data_type FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name IN ('games','sales_long') "
        "ORDER BY table_name, ordinal_position"
    )
    return {
        "columns": cols,
        "regions": ["NA", "EU", "JP", "Other"],
        "genres": GENRES,
        "notes": NOTES + ["One row per game-platform combination; a game name can repeat across platforms."],
    }


@mcp.tool()
@logged
def genre_share(region: str) -> dict:
    """For ONE region (NA, EU, JP or Other), return each genre's sales and its percentage
    of THAT REGION'S total sales (e.g. Shooter as a share of NA sales). Use this for
    'what percentage of <region>'s sales comes from <genre>' and 'top genres in <region>'."""
    r = check_region(region)
    rows = run_query(
        "SELECT genre, ROUND(SUM(sales),2) AS sales_m, "
        "ROUND(100*SUM(sales)/SUM(SUM(sales)) OVER (),1) AS pct_of_region_sales "
        "FROM sales_long WHERE region=%s GROUP BY genre ORDER BY SUM(sales) DESC",
        (r,),
    )
    return {"region": r, "basis": "pct_of_region_sales = genre sales / that region's total sales",
            "rows": rows, "notes": NOTES}


@mcp.tool()
@logged
def compare_regions(genre: str) -> dict:
    """For ONE genre, compare all four regions. Returns sales per region, the genre's percentage
    of each region's sales (pct_of_region_sales), and each region's percentage of the genre's
    worldwide sales (pct_of_genre_global). These are two different directions; pick the right one."""
    g = check_genre(genre)
    rows = run_query(
        "WITH g AS (SELECT region, SUM(sales) AS s FROM sales_long WHERE genre=%s GROUP BY region), "
        "r AS (SELECT region, SUM(sales) AS s FROM sales_long GROUP BY region) "
        "SELECT g.region, ROUND(g.s,2) AS sales_m, "
        "ROUND(100*g.s/r.s,1) AS pct_of_region_sales, "
        "ROUND(100*g.s/SUM(g.s) OVER (),1) AS pct_of_genre_global "
        "FROM g JOIN r USING (region) ORDER BY g.s DESC",
        (g,),
    )
    return {"genre": g,
            "basis": {"pct_of_region_sales": "genre sales / that region's total sales",
                      "pct_of_genre_global": "region's sales of this genre / this genre's worldwide sales"},
            "rows": rows, "notes": NOTES}


@mcp.tool()
@logged
def top_games(region: str = "Global", genre: str | None = None,
              year_from: int | None = None, year_to: int | None = None,
              limit: int = 10) -> dict:
    """Best-selling games, ranked by sales summed ACROSS PLATFORMS for each title.
    region: NA, EU, JP, Other or Global (default Global). Optional genre and year range.
    limit: 1 to 20 (default 10). Say which region you used when you answer."""
    r = check_region(region, allow_global=True)
    col = SALES_COL[r]  # whitelisted column name, never user text
    where, params = [], {}
    if genre is not None:
        where.append("genre = %(genre)s")
        params["genre"] = check_genre(genre)
    if year_from is not None:
        where.append("year >= %(year_from)s")
        params["year_from"] = int(year_from)
    if year_to is not None:
        where.append("year <= %(year_to)s")
        params["year_to"] = int(year_to)
    if year_from is not None and year_to is not None and year_from > year_to:
        raise ValueError("year_from must be less than or equal to year_to.")
    n = max(1, min(int(limit), MAX_TOP))
    sql = (f"SELECT name, ROUND(SUM({col}),2) AS sales_m, COUNT(*) AS platform_rows "
           f"FROM games {'WHERE ' + ' AND '.join(where) if where else ''} "
           f"GROUP BY name ORDER BY SUM({col}) DESC, name LIMIT {n}")
    rows = run_query(sql, params)
    extra = ["Games with an unknown release year are excluded when a year filter is used."] if (year_from or year_to) else []
    return {"region": r, "genre": params.get("genre"), "year_from": year_from, "year_to": year_to,
            "basis": f"sales_m = {col} summed across all platforms for each game name",
            "rows": rows, "notes": NOTES + extra}


@mcp.tool()
@logged
def run_readonly_query(sql: str) -> dict:
    """LAST RESORT. Use only when get_schema, genre_share, compare_regions and top_games cannot
    answer. One SELECT (or WITH ... SELECT) on tables games and sales_long, maximum 50 rows.
    sales_long has columns (id, name, platform, year, genre, publisher, region, sales) with
    region in 'NA','EU','JP','Other'. games has na_sales, eu_sales, jp_sales, other_sales, global_sales."""
    s = sql.strip().rstrip(";").strip()
    if ";" in s or "--" in s or "/*" in s:
        raise ValueError("Only a single statement without comments is allowed.")
    if not re.match(r"(?is)^(select|with)\b", s):
        raise ValueError("Only SELECT queries are allowed.")
    no_literals = re.sub(r"'(?:[^']|'')*'", "''", s)
    if BLOCKED.search(no_literals):
        raise ValueError("Query contains a blocked keyword. Only plain SELECTs on games/sales_long are allowed.")
    rows = run_query(s, None, limit=MAX_ROWS + 1)
    truncated = len(rows) > MAX_ROWS
    return {"rows": rows[:MAX_ROWS], "truncated_at_50_rows": truncated,
            "notes": NOTES + (["Result was cut at 50 rows."] if truncated else [])}


if __name__ == "__main__":
    # Never print() to stdout here: stdio transport uses stdout for the protocol.
    mcp.run(transport=sys.argv[1] if len(sys.argv) > 1 else "stdio")
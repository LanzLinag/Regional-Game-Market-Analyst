import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    params = StdioServerParameters(command=sys.executable, args=["server.py"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()
            print("TOOLS:", [t.name for t in (await s.list_tools()).tools])

            async def call(name, args):
                res = await s.call_tool(name, args)
                print(f"\n== {name}({args})  isError={res.isError}")
                text = res.content[0].text
                try:
                    data = json.loads(text)
                    rows = data.get("rows", [])
                    for row in rows[:6]:
                        print("  ", row)
                    print(f"   ({len(rows)} rows)", {k: data[k] for k in ("basis", "truncated_at_50_rows") if k in data})
                except Exception:
                    print("  ", text[:300])

            print("\n##### SHOULD SUCCEED (compare with verify.sql) #####")
            await call("top_games", {})
            await call("top_games", {"region": "JP", "genre": "Role-Playing", "limit": 5})
            await call("top_games", {"region": "NA", "year_from": 2000, "year_to": 2005, "limit": 5})
            await call("run_readonly_query", {"sql": "SELECT genre, ROUND(SUM(jp_sales),2) AS jp FROM games GROUP BY genre ORDER BY 2 DESC"})
            await call("run_readonly_query", {"sql": "SELECT name FROM games WHERE name LIKE 'Call of Duty%' LIMIT 3"})

            print("\n##### SHOULD FAIL (isError=True) #####")
            await call("top_games", {"region": "Mars"})
            await call("top_games", {"genre": "Action'; DROP TABLE games;--"})
            await call("top_games", {"year_from": 2010, "year_to": 2000})
            await call("run_readonly_query", {"sql": "DELETE FROM games"})
            await call("run_readonly_query", {"sql": "SELECT 1; DROP TABLE games"})
            await call("run_readonly_query", {"sql": "SELECT pg_sleep(10)"})
            await call("run_readonly_query", {"sql": "WITH x AS (DELETE FROM games RETURNING *) SELECT * FROM x"})
            await call("run_readonly_query", {"sql": "SELECT * FROM information_schema.tables"})

            print("\n##### SHOULD SUCCEED BUT BE CAPPED #####")
            await call("top_games", {"limit": 1000})  # clamped to 20
            await call("run_readonly_query", {"sql": "SELECT * FROM games"})  # 50 rows, truncated true

    # Database layer, bypassing the keyword blocklist: the real protection must still hold.
    print("\n##### DB LAYER: expect an error from Postgres #####")
    import server
    for sql in ("DELETE FROM games WHERE id = -1", "UPDATE games SET na_sales = 0 WHERE id = -1"):
        try:
            server.run_query(sql)
            print("!! NOT BLOCKED:", sql)
        except Exception as e:
            print("blocked:", sql, "->", str(e).splitlines()[0])


asyncio.run(main())
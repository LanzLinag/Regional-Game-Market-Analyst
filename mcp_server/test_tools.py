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
                    for row in data.get("rows", data.get("columns", [])):
                        print("  ", row)
                    if "basis" in data:
                        print("   basis:", data["basis"])
                except Exception:
                    print("  ", text[:300])   # error messages arrive as plain text

            await call("genre_share", {"region": "NA"})
            await call("genre_share", {"region": "jp"})
            await call("compare_regions", {"genre": "Shooter"})
            await call("compare_regions", {"genre": "Role-Playing"})
            await call("get_schema", {})
            # negative tests
            await call("genre_share", {"region": "Mars"})
            await call("compare_regions", {"genre": "Action'; DROP TABLE games;--"})


asyncio.run(main())
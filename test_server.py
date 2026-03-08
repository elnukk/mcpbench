import asyncio
from mcpbench import MCPBench, expect
from tests.dummy_server import mcp

bench = MCPBench(server=mcp, model="claude-sonnet-4-20250514", runs=5)


@bench.scenario("user wants to search by name")
async def test_search():
    result = await bench.run("find all users named John", expected_tool="search_users")
    expect(result).called_tool("search_users")
    expect(result).tool_param("query", contains="John")
    return result


@bench.scenario("look up — ambiguous, should still hit search_users")
async def test_lookup():
    result = await bench.run("look up John", expected_tool="search_users")
    return result


if __name__ == "__main__":
    results = bench.run_all()
    for description, result, error in results:
        if error:
            print(f"✗ {description}")
            print(f"  {error}")
        else:
            n = len(result.runs)
            hits = sum(1 for r in result.runs if r.tool_called == result.expected_tool)
            bar = ("█" * hits + "░" * (n - hits))
            print(f"✓ {description}  {bar}  {hits}/{n}  ({hits/n:.0%})")
            if hits < n:
                print(f"  confusion: {result.confusion}")

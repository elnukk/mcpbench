from mcpbench import MCPBench, expect
from tests.github_server import make_transport

bench = MCPBench(server=make_transport(), model="claude-sonnet-4-6")


@bench.scenario("search for open issues in a repo")
async def test_search_issues():
    bench.server = make_transport()
    result = await bench.run(
        "search for open issues in the anthropics/anthropic-sdk-python repo",
        expected_tool="search_issues",
    )
    expect(result).called_tool("search_issues")
    return result


@bench.scenario("list open issues in a repo")
async def test_list_issues():
    bench.server = make_transport()
    result = await bench.run(
        "list all open issues in anthropics/anthropic-sdk-python",
        expected_tool="list_issues",
    )
    expect(result).called_tool("list_issues")
    return result

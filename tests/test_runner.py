import asyncio
import anyio
import pytest
from types import SimpleNamespace
from mcpbench import runner
from mcpbench.runner import _call_claude, _get_anthropic_tools, _is_stdio_teardown_race, run_scenario, ScenarioResult, ToolCall


class _FakeUsage:
    def __init__(self, input_tokens, output_tokens):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeBlock:
    def __init__(self, type_, name=None, input=None):
        self.type = type_
        self.name = name
        self.input = input


class _FakeResponse:
    def __init__(self, content, input_tokens=10, output_tokens=5):
        self.content = content
        self.usage = _FakeUsage(input_tokens, output_tokens)


class _FakeMessages:
    def __init__(self, response):
        self._response = response

    async def create(self, **kwargs):
        return self._response


class _FakeClient:
    def __init__(self, response):
        self.messages = _FakeMessages(response)


@pytest.mark.asyncio
async def test_call_claude_records_usage_and_latency_on_tool_use():
    response = _FakeResponse(
        content=[_FakeBlock("tool_use", name="search_users", input={"query": "john"})],
        input_tokens=42,
        output_tokens=8,
    )
    client = _FakeClient(response)

    call = await _call_claude(client, "find john", tools=[], model="claude-sonnet-4-6")

    assert call.tool_called == "search_users"
    assert call.params == {"query": "john"}
    assert call.input_tokens == 42
    assert call.output_tokens == 8
    assert call.latency_s >= 0.0


@pytest.mark.asyncio
async def test_call_claude_records_usage_when_no_tool_used():
    response = _FakeResponse(content=[_FakeBlock("text")], input_tokens=15, output_tokens=3)
    client = _FakeClient(response)

    call = await _call_claude(client, "thanks!", tools=[], model="claude-sonnet-4-6")

    assert call.tool_called is None
    assert call.input_tokens == 15
    assert call.output_tokens == 3


def test_scenario_result_cost_aggregates():
    result = ScenarioResult(prompt="p", expected_tool="t")
    result.runs = [
        ToolCall(tool_called="t", params={}, input_tokens=10, output_tokens=2, latency_s=0.2),
        ToolCall(tool_called="t", params={}, input_tokens=20, output_tokens=4, latency_s=0.4),
    ]
    assert result.total_input_tokens == 30
    assert result.total_output_tokens == 6
    assert result.avg_latency_s == pytest.approx(0.3)


def test_scenario_result_cost_aggregates_empty():
    result = ScenarioResult(prompt="p", expected_tool="t")
    assert result.total_input_tokens == 0
    assert result.total_output_tokens == 0
    assert result.avg_latency_s == 0.0


class _FakeAsyncAnthropic:
    def __init__(self, api_key):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.mark.asyncio
async def test_run_scenario_bounds_concurrency(monkeypatch):
    n, concurrency = 10, 3
    active = 0
    max_active = 0
    lock = asyncio.Lock()

    async def fake_get_tools(server):
        return []

    async def fake_call_claude(client, prompt, tools, model):
        nonlocal active, max_active
        async with lock:
            active += 1
            max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        async with lock:
            active -= 1
        return ToolCall(tool_called="search_users", params={})

    monkeypatch.setattr(runner, "_get_anthropic_tools", fake_get_tools)
    monkeypatch.setattr(runner, "_call_claude", fake_call_claude)
    monkeypatch.setattr(runner.anthropic, "AsyncAnthropic", _FakeAsyncAnthropic)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    result = await run_scenario(
        prompt="find john",
        server=object(),
        n=n,
        model="claude-sonnet-4-6",
        expected_tool="search_users",
        concurrency=concurrency,
    )

    assert len(result.runs) == n
    assert all(r.tool_called == "search_users" for r in result.runs)
    assert max_active <= concurrency


# -- _is_stdio_teardown_race: the known mcp-SDK stdio-teardown race -------

def test_is_stdio_teardown_race_true_for_broken_resource_error():
    assert _is_stdio_teardown_race(anyio.BrokenResourceError())


def test_is_stdio_teardown_race_true_for_wrapped_runtime_error():
    try:
        raise anyio.BrokenResourceError()
    except anyio.BrokenResourceError as cause:
        wrapped = RuntimeError("Client failed to connect: ")
        wrapped.__cause__ = cause
    assert _is_stdio_teardown_race(wrapped)


def test_is_stdio_teardown_race_false_for_unrelated_runtime_error():
    assert not _is_stdio_teardown_race(RuntimeError("some other failure"))


def test_is_stdio_teardown_race_false_for_unrelated_exception():
    assert not _is_stdio_teardown_race(ValueError("nope"))


# -- _get_anthropic_tools: tolerating the race once data is already in hand --

def _fake_tool(name):
    return SimpleNamespace(name=name, description=f"{name} description", inputSchema={})


class _FakeClientRaisingOnExit:
    """Mimics fastmcp's Client: list_tools() succeeds, __aexit__ raises the teardown race."""

    def __init__(self, server, exc):
        self._exc = exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        raise self._exc

    async def list_tools(self):
        return [_fake_tool("search_users")]


class _FakeClientRaisingOnEnter:
    """Mimics a connect-phase failure: __aenter__ raises before any data is fetched."""

    def __init__(self, server, exc):
        self._exc = exc

    async def __aenter__(self):
        raise self._exc

    async def __aexit__(self, *exc_info):
        return False


@pytest.mark.asyncio
async def test_get_anthropic_tools_tolerates_teardown_race_after_fetch(monkeypatch):
    monkeypatch.setattr(runner, "Client", lambda server: _FakeClientRaisingOnExit(server, anyio.BrokenResourceError()))

    tools = await _get_anthropic_tools(object())

    assert tools == [{"name": "search_users", "description": "search_users description", "input_schema": {}}]


@pytest.mark.asyncio
async def test_get_anthropic_tools_reraises_when_never_connected(monkeypatch):
    try:
        raise anyio.BrokenResourceError()
    except anyio.BrokenResourceError as cause:
        connect_failure = RuntimeError("Client failed to connect: ")
        connect_failure.__cause__ = cause

    monkeypatch.setattr(runner, "Client", lambda server: _FakeClientRaisingOnEnter(server, connect_failure))

    with pytest.raises(RuntimeError):
        await _get_anthropic_tools(object())


@pytest.mark.asyncio
async def test_get_anthropic_tools_reraises_unrelated_errors_even_after_fetch(monkeypatch):
    monkeypatch.setattr(runner, "Client", lambda server: _FakeClientRaisingOnExit(server, ValueError("unrelated")))

    with pytest.raises(ValueError):
        await _get_anthropic_tools(object())

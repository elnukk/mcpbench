import asyncio
import os
import time
from dataclasses import dataclass, field
import anyio
import anthropic
from fastmcp import Client


@dataclass
class ToolCall:
    tool_called: str | None
    params: dict
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0


@dataclass
class ScenarioResult:
    prompt: str
    expected_tool: str | None
    runs: list[ToolCall] = field(default_factory=list)
    tools: list[dict] = field(default_factory=list)

    @property
    def hit_rate(self) -> float:
        """Fraction of runs matching expected_tool.

        expected_tool=None means "expect no tool call" (a restraint scenario),
        consistent with how cli.py and snapshot.build already score it.
        """
        if not self.runs:
            return 0.0
        hits = sum(1 for r in self.runs if r.tool_called == self.expected_tool)
        return hits / len(self.runs)

    @property
    def confusion(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self.runs:
            key = r.tool_called or "(no tool)"
            counts[key] = counts.get(key, 0) + 1
        return counts

    @property
    def avg_latency_s(self) -> float:
        if not self.runs:
            return 0.0
        return sum(r.latency_s for r in self.runs) / len(self.runs)

    @property
    def total_input_tokens(self) -> int:
        return sum(r.input_tokens for r in self.runs)

    @property
    def total_output_tokens(self) -> int:
        return sum(r.output_tokens for r in self.runs)


def _is_stdio_teardown_race(exc: BaseException) -> bool:
    """True for the known mcp-SDK race where a stdio server's shutdown
    notifications outrun the client's own stream teardown. mcp's
    stdout_reader only guards anyio.ClosedResourceError, not the sibling
    anyio.BrokenResourceError, so this can surface either directly or
    wrapped in fastmcp's "Client failed to connect" RuntimeError on the
    *next* connection in the same process.
    """
    if isinstance(exc, anyio.BrokenResourceError):
        return True
    return isinstance(exc, RuntimeError) and isinstance(exc.__cause__, anyio.BrokenResourceError)


async def _get_anthropic_tools(server) -> list[dict]:
    tools = None
    try:
        async with Client(server) as client:
            tools = await client.list_tools()
    except Exception as exc:
        # Safe to ignore once we already have the data; re-raise otherwise.
        if tools is None or not _is_stdio_teardown_race(exc):
            raise
    return [
        {
            "name": t.name,
            "description": t.description or "",
            "input_schema": t.inputSchema,
        }
        for t in tools
    ]


async def _call_claude(client: anthropic.AsyncAnthropic, prompt: str, tools: list[dict], model: str) -> ToolCall:
    start = time.monotonic()
    response = await client.messages.create(
        model=model,
        max_tokens=256,
        tools=tools,
        messages=[{"role": "user", "content": prompt}],
    )
    latency_s = time.monotonic() - start
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens

    for block in response.content:
        if block.type == "tool_use":
            return ToolCall(
                tool_called=block.name,
                params=block.input,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_s=latency_s,
            )
    return ToolCall(
        tool_called=None,
        params={},
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_s=latency_s,
    )


async def run_scenario(
    prompt: str,
    server,
    n: int,
    model: str,
    expected_tool: str | None = None,
    concurrency: int = 5,
) -> ScenarioResult:
    tools = await _get_anthropic_tools(server)
    result = ScenarioResult(prompt=prompt, expected_tool=expected_tool, tools=tools)

    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _bounded_call(client: anthropic.AsyncAnthropic) -> ToolCall:
        async with semaphore:
            return await _call_claude(client, prompt, tools, model)

    async with anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"]) as client:
        result.runs = list(await asyncio.gather(*(_bounded_call(client) for _ in range(n))))

    return result

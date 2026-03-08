import os
from dataclasses import dataclass, field
import anthropic
from fastmcp import Client


@dataclass
class ToolCall:
    tool_called: str | None
    params: dict


@dataclass
class ScenarioResult:
    prompt: str
    expected_tool: str | None
    runs: list[ToolCall] = field(default_factory=list)
    tools: list[dict] = field(default_factory=list)

    @property
    def hit_rate(self) -> float:
        if not self.runs or self.expected_tool is None:
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


async def _get_anthropic_tools(server) -> list[dict]:
    async with Client(server) as client:
        tools = await client.list_tools()
    return [
        {
            "name": t.name,
            "description": t.description or "",
            "input_schema": t.inputSchema,
        }
        for t in tools
    ]


async def _call_claude(prompt: str, tools: list[dict], model: str) -> ToolCall:
    async with anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"]) as client:
        response = await client.messages.create(
            model=model,
            max_tokens=256,
            tools=tools,
            messages=[{"role": "user", "content": prompt}],
        )
    for block in response.content:
        if block.type == "tool_use":
            return ToolCall(tool_called=block.name, params=block.input)
    return ToolCall(tool_called=None, params={})


async def run_scenario(
    prompt: str,
    server,
    n: int,
    model: str,
    expected_tool: str | None = None,
) -> ScenarioResult:
    tools = await _get_anthropic_tools(server)
    result = ScenarioResult(prompt=prompt, expected_tool=expected_tool, tools=tools)
    for _ in range(n):
        call = await _call_claude(prompt, tools, model)
        result.runs.append(call)
    return result

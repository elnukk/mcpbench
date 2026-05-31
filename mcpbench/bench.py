import asyncio
from mcpbench.runner import run_scenario, ScenarioResult

DEFAULT_MODEL = "claude-sonnet-4-6"


class MCPBench:
    def __init__(self, server, model: str = DEFAULT_MODEL, runs: int = 5):
        self.server = server
        self.model = model
        self.runs = runs
        self._scenarios: list[dict] = []
        self._last_result: ScenarioResult | None = None

    def scenario(self, description: str):
        def decorator(fn):
            self._scenarios.append({"description": description, "fn": fn})
            return fn
        return decorator

    async def run(self, prompt: str, expected_tool: str | None = None) -> ScenarioResult:
        result = await run_scenario(
            prompt=prompt,
            server=self.server,
            n=self.runs,
            model=self.model,
            expected_tool=expected_tool,
        )
        self._last_result = result
        return result

    def run_all(self, threshold: float = 0.8) -> list[tuple[str, ScenarioResult | None, Exception | None]]:
        results = []
        for s in self._scenarios:
            try:
                result = asyncio.run(s["fn"]())
                results.append((s["description"], result, None))
            except Exception as e:
                results.append((s["description"], None, e))
        return results

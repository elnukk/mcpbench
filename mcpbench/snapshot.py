from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

MCPBENCH_VERSION = "0.3.0"


@dataclass
class ScenarioSnapshot:
    """Per-scenario data recorded in a snapshot file."""

    name: str
    expected_tool: str | None
    hit_rate: float
    hits: int
    total: int
    tool_calls: dict[str, int]


@dataclass
class BenchSnapshot:
    """Serialisable record of a full benchmark run, written by --save and read by diff."""

    mcpbench_version: str
    created_at: str
    model: str
    runs_per_scenario: int
    scenarios: list[ScenarioSnapshot] = field(default_factory=list)

    def to_json(self, path: str | Path) -> None:
        data = {
            "mcpbench_version": self.mcpbench_version,
            "created_at": self.created_at,
            "model": self.model,
            "runs_per_scenario": self.runs_per_scenario,
            "scenarios": [
                {
                    "name": s.name,
                    "expected_tool": s.expected_tool,
                    "hit_rate": s.hit_rate,
                    "hits": s.hits,
                    "total": s.total,
                    "tool_calls": s.tool_calls,
                }
                for s in self.scenarios
            ],
        }
        Path(path).write_text(json.dumps(data, indent=2))

    @classmethod
    def from_json(cls, path: str | Path) -> "BenchSnapshot":
        data = json.loads(Path(path).read_text())
        scenarios = [
            ScenarioSnapshot(
                name=s["name"],
                expected_tool=s.get("expected_tool"),
                hit_rate=s["hit_rate"],
                hits=s["hits"],
                total=s["total"],
                tool_calls=s.get("tool_calls", {}),
            )
            for s in data.get("scenarios", [])
        ]
        return cls(
            mcpbench_version=data.get("mcpbench_version", ""),
            created_at=data.get("created_at", ""),
            model=data.get("model", ""),
            runs_per_scenario=data.get("runs_per_scenario", 0),
            scenarios=scenarios,
        )

    @classmethod
    def build(cls, model: str, runs_per_scenario: int, scenario_results: list[tuple[str, object]]) -> "BenchSnapshot":
        """Build a snapshot from live run data. Entries where result is None (errored scenarios) are skipped."""
        from mcpbench.runner import ScenarioResult

        scenarios = []
        for description, result in scenario_results:
            if not isinstance(result, ScenarioResult):
                continue
            n = len(result.runs)
            hits = sum(1 for r in result.runs if r.tool_called == result.expected_tool)
            rate = hits / n if n else 0.0
            scenarios.append(ScenarioSnapshot(
                name=description,
                expected_tool=result.expected_tool,
                hit_rate=rate,
                hits=hits,
                total=n,
                tool_calls=dict(result.confusion),
            ))
        return cls(
            mcpbench_version=MCPBENCH_VERSION,
            created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            model=model,
            runs_per_scenario=runs_per_scenario,
            scenarios=scenarios,
        )

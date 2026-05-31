from __future__ import annotations

from dataclasses import dataclass
from mcpbench.snapshot import BenchSnapshot, ScenarioSnapshot

REGRESSION_THRESHOLD = 0.05


@dataclass
class ScenarioDiff:
    name: str
    status: str  # improved | regressed | unchanged | added | removed
    before_rate: float | None
    after_rate: float | None

    @property
    def delta(self) -> float | None:
        if self.before_rate is None or self.after_rate is None:
            return None
        return self.after_rate - self.before_rate


@dataclass
class DiffResult:
    diffs: list[ScenarioDiff]
    warnings: list[str]

    @property
    def regressions(self) -> list[ScenarioDiff]:
        return [d for d in self.diffs if d.status == "regressed"]


def compute_diff(
    before: BenchSnapshot,
    after: BenchSnapshot,
    regression_threshold: float = REGRESSION_THRESHOLD,
) -> DiffResult:
    """Compare two snapshots. A drop larger than regression_threshold counts as regressed; warns (doesn't error) if model or run count differ."""
    warnings = []

    if before.model != after.model:
        warnings.append(f"model differs: {before.model!r} vs {after.model!r}")
    if before.runs_per_scenario != after.runs_per_scenario:
        warnings.append(
            f"runs_per_scenario differs: {before.runs_per_scenario} vs {after.runs_per_scenario}"
        )

    before_map: dict[str, ScenarioSnapshot] = {s.name: s for s in before.scenarios}
    after_map: dict[str, ScenarioSnapshot] = {s.name: s for s in after.scenarios}

    all_names = list(before_map) + [n for n in after_map if n not in before_map]

    diffs = []
    for name in all_names:
        b = before_map.get(name)
        a = after_map.get(name)

        if b is None:
            diffs.append(ScenarioDiff(name=name, status="added", before_rate=None, after_rate=a.hit_rate))
        elif a is None:
            diffs.append(ScenarioDiff(name=name, status="removed", before_rate=b.hit_rate, after_rate=None))
        else:
            delta = a.hit_rate - b.hit_rate
            if delta < -regression_threshold:
                status = "regressed"
            elif delta > regression_threshold:
                status = "improved"
            else:
                status = "unchanged"
            diffs.append(ScenarioDiff(name=name, status=status, before_rate=b.hit_rate, after_rate=a.hit_rate))

    return DiffResult(diffs=diffs, warnings=warnings)

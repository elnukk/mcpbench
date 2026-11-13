from __future__ import annotations

from dataclasses import dataclass
from mcpbench.snapshot import BenchSnapshot, ScenarioSnapshot
from mcpbench.stats import wilson_interval

REGRESSION_THRESHOLD = 0.05
COST_NOTE_THRESHOLD = 0.20  # relative change in avg tokens/latency worth flagging


@dataclass
class ScenarioDiff:
    name: str
    status: str  # improved | regressed | unchanged | added | removed
    before_rate: float | None
    after_rate: float | None
    before_ci: tuple[float, float] | None = None
    after_ci: tuple[float, float] | None = None
    before_avg_latency_s: float | None = None
    after_avg_latency_s: float | None = None
    before_avg_tokens: float | None = None
    after_avg_tokens: float | None = None

    @property
    def delta(self) -> float | None:
        if self.before_rate is None or self.after_rate is None:
            return None
        return self.after_rate - self.before_rate

    @property
    def significant(self) -> bool:
        """True if the before/after Wilson intervals don't overlap.

        Added/removed scenarios (no comparison to make) are trivially significant.
        """
        if self.before_ci is None or self.after_ci is None:
            return True
        before_lo, before_hi = self.before_ci
        after_lo, after_hi = self.after_ci
        return after_lo > before_hi or before_lo > after_hi

    @property
    def cost_note(self) -> str | None:
        """A note on cost/latency shifts, e.g. flat accuracy but pricier or slower calls."""
        if None in (
            self.before_avg_latency_s,
            self.after_avg_latency_s,
            self.before_avg_tokens,
            self.after_avg_tokens,
        ):
            return None

        parts = []
        if self.before_avg_tokens > 0:
            token_delta = (self.after_avg_tokens - self.before_avg_tokens) / self.before_avg_tokens
            if abs(token_delta) >= COST_NOTE_THRESHOLD:
                parts.append(f"tokens {token_delta:+.0%}")

        if self.before_avg_latency_s > 0:
            latency_delta_s = self.after_avg_latency_s - self.before_avg_latency_s
            if abs(latency_delta_s / self.before_avg_latency_s) >= COST_NOTE_THRESHOLD:
                parts.append(f"latency {latency_delta_s:+.2f}s")

        return ", ".join(parts) if parts else None


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
            diffs.append(ScenarioDiff(
                name=name,
                status=status,
                before_rate=b.hit_rate,
                after_rate=a.hit_rate,
                before_ci=wilson_interval(b.hits, b.total),
                after_ci=wilson_interval(a.hits, a.total),
                before_avg_latency_s=b.avg_latency_s,
                after_avg_latency_s=a.avg_latency_s,
                before_avg_tokens=(b.total_input_tokens + b.total_output_tokens) / b.total if b.total else 0.0,
                after_avg_tokens=(a.total_input_tokens + a.total_output_tokens) / a.total if a.total else 0.0,
            ))

    return DiffResult(diffs=diffs, warnings=warnings)

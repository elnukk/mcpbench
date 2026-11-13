import json
import pytest
from pathlib import Path
from mcpbench.snapshot import BenchSnapshot, ScenarioSnapshot
from mcpbench.diff import compute_diff
from mcpbench.runner import ScenarioResult, ToolCall


def _snapshot(scenarios: list[dict], model: str = "claude-sonnet-4-6", runs: int = 5) -> BenchSnapshot:
    return BenchSnapshot(
        mcpbench_version="0.2.0",
        created_at="2025-05-31T00:00:00Z",
        model=model,
        runs_per_scenario=runs,
        scenarios=[
            ScenarioSnapshot(
                name=s["name"],
                expected_tool=s.get("expected_tool"),
                hit_rate=s["hit_rate"],
                hits=int(s["hit_rate"] * runs),
                total=runs,
                tool_calls=s.get("tool_calls", {}),
            )
            for s in scenarios
        ],
    )


def test_regression_detected():
    before = _snapshot([{"name": "search users", "hit_rate": 0.8}])
    after = _snapshot([{"name": "search users", "hit_rate": 0.4}])
    result = compute_diff(before, after)
    assert len(result.regressions) == 1
    assert result.regressions[0].name == "search users"
    assert result.regressions[0].status == "regressed"


def test_improvement_detected():
    before = _snapshot([{"name": "search users", "hit_rate": 0.4}])
    after = _snapshot([{"name": "search users", "hit_rate": 1.0}])
    result = compute_diff(before, after)
    assert result.diffs[0].status == "improved"
    assert not result.regressions


def test_unchanged_within_threshold():
    before = _snapshot([{"name": "search users", "hit_rate": 0.8}])
    after = _snapshot([{"name": "search users", "hit_rate": 0.8}])
    result = compute_diff(before, after)
    assert result.diffs[0].status == "unchanged"
    assert not result.regressions


def test_small_drop_not_regression():
    before = _snapshot([{"name": "search users", "hit_rate": 0.8}])
    after = _snapshot([{"name": "search users", "hit_rate": 0.76}])
    result = compute_diff(before, after)
    assert result.diffs[0].status == "unchanged"


def test_added_scenario():
    before = _snapshot([{"name": "search users", "hit_rate": 1.0}])
    after = _snapshot([
        {"name": "search users", "hit_rate": 1.0},
        {"name": "get user by id", "hit_rate": 0.6},
    ])
    result = compute_diff(before, after)
    added = [d for d in result.diffs if d.status == "added"]
    assert len(added) == 1
    assert added[0].name == "get user by id"
    assert added[0].before_rate is None


def test_removed_scenario():
    before = _snapshot([
        {"name": "search users", "hit_rate": 1.0},
        {"name": "get user by id", "hit_rate": 0.6},
    ])
    after = _snapshot([{"name": "search users", "hit_rate": 1.0}])
    result = compute_diff(before, after)
    removed = [d for d in result.diffs if d.status == "removed"]
    assert len(removed) == 1
    assert removed[0].name == "get user by id"
    assert removed[0].after_rate is None


def test_mismatched_model_warning():
    before = _snapshot([], model="claude-sonnet-4-20250514")
    after = _snapshot([], model="claude-opus-4-5")
    result = compute_diff(before, after)
    assert any("model" in w for w in result.warnings)


def test_mismatched_runs_warning():
    before = _snapshot([], runs=5)
    after = _snapshot([], runs=10)
    result = compute_diff(before, after)
    assert any("runs_per_scenario" in w for w in result.warnings)


def test_keyed_by_name_not_position():
    before = _snapshot([
        {"name": "scenario A", "hit_rate": 1.0},
        {"name": "scenario B", "hit_rate": 0.8},
    ])
    after = _snapshot([
        {"name": "scenario B", "hit_rate": 0.8},
        {"name": "scenario A", "hit_rate": 1.0},
    ])
    result = compute_diff(before, after)
    assert all(d.status == "unchanged" for d in result.diffs)
    assert not result.regressions


def test_significant_regression_has_non_overlapping_ci():
    # large N, big drop -> CIs shouldn't overlap
    before = _snapshot([{"name": "search users", "hit_rate": 0.9}], runs=50)
    after = _snapshot([{"name": "search users", "hit_rate": 0.3}], runs=50)
    result = compute_diff(before, after)
    assert result.diffs[0].status == "regressed"
    assert result.diffs[0].significant


def test_small_n_regression_may_not_be_significant():
    # n=5, single-run swing crossing the threshold -> CIs should still overlap
    before = _snapshot([{"name": "search users", "hit_rate": 0.8}], runs=5)
    after = _snapshot([{"name": "search users", "hit_rate": 0.4}], runs=5)
    result = compute_diff(before, after)
    assert result.diffs[0].status == "regressed"
    assert not result.diffs[0].significant


def test_cost_note_flagged_when_accuracy_unchanged():
    before = _snapshot([{"name": "search users", "hit_rate": 0.8}])
    after = _snapshot([{"name": "search users", "hit_rate": 0.8}])
    before.scenarios[0].total_input_tokens = 100
    before.scenarios[0].total_output_tokens = 20
    before.scenarios[0].avg_latency_s = 0.5
    after.scenarios[0].total_input_tokens = 300
    after.scenarios[0].total_output_tokens = 20
    after.scenarios[0].avg_latency_s = 0.9
    result = compute_diff(before, after)
    assert result.diffs[0].status == "unchanged"
    assert "tokens" in result.diffs[0].cost_note
    assert "latency" in result.diffs[0].cost_note


def test_cost_note_absent_when_change_is_small():
    before = _snapshot([{"name": "search users", "hit_rate": 0.8}])
    after = _snapshot([{"name": "search users", "hit_rate": 0.8}])
    before.scenarios[0].total_input_tokens = 100
    before.scenarios[0].total_output_tokens = 20
    before.scenarios[0].avg_latency_s = 0.5
    after.scenarios[0].total_input_tokens = 105
    after.scenarios[0].total_output_tokens = 21
    after.scenarios[0].avg_latency_s = 0.52
    result = compute_diff(before, after)
    assert result.diffs[0].cost_note is None


def test_added_removed_rows_are_trivially_significant():
    before = _snapshot([{"name": "search users", "hit_rate": 1.0}])
    after = _snapshot([
        {"name": "search users", "hit_rate": 1.0},
        {"name": "get user by id", "hit_rate": 0.6},
    ])
    result = compute_diff(before, after)
    added = [d for d in result.diffs if d.status == "added"][0]
    assert added.significant


def test_custom_regression_threshold():
    before = _snapshot([{"name": "search users", "hit_rate": 0.8}])
    after = _snapshot([{"name": "search users", "hit_rate": 0.72}])
    # 0.08 drop — below default 0.05 threshold, so normally regression
    result_default = compute_diff(before, after)
    assert result_default.diffs[0].status == "regressed"
    # with threshold=0.1 the same drop should be unchanged
    result_lenient = compute_diff(before, after, regression_threshold=0.1)
    assert result_lenient.diffs[0].status == "unchanged"


# Snapshot build + serialization tests 
def _make_result(prompt: str, expected: str, calls: list[str]) -> ScenarioResult:
    result = ScenarioResult(prompt=prompt, expected_tool=expected)
    result.runs = [ToolCall(tool_called=c, params={}) for c in calls]
    return result


def test_build_hit_rate():
    result = _make_result("find john", "search_users", ["search_users", "search_users", "list_users", "search_users", "search_users"])
    snap = BenchSnapshot.build(
        model="claude-sonnet-4-20250514",
        runs_per_scenario=5,
        scenario_results=[("search scenario", result)],
    )
    assert len(snap.scenarios) == 1
    s = snap.scenarios[0]
    assert s.name == "search scenario"
    assert s.expected_tool == "search_users"
    assert s.hits == 4
    assert s.total == 5
    assert s.hit_rate == pytest.approx(0.8)
    assert s.tool_calls == {"search_users": 4, "list_users": 1}


def test_build_skips_none_results():
    result = _make_result("find john", "search_users", ["search_users"])
    snap = BenchSnapshot.build(
        model="claude-sonnet-4-20250514",
        runs_per_scenario=5,
        scenario_results=[("good scenario", result), ("failed scenario", None)],
    )
    assert len(snap.scenarios) == 1
    assert snap.scenarios[0].name == "good scenario"


def test_build_metadata():
    snap = BenchSnapshot.build(
        model="claude-opus-4-5",
        runs_per_scenario=10,
        scenario_results=[],
    )
    assert snap.model == "claude-opus-4-5"
    assert snap.runs_per_scenario == 10
    assert snap.mcpbench_version == "0.3.0"
    assert snap.created_at.endswith("Z")


def test_to_json_from_json_roundtrip(tmp_path):
    result = _make_result("get user 42", "get_user", ["get_user", "list_users", "get_user"])
    snap = BenchSnapshot.build(
        model="claude-sonnet-4-20250514",
        runs_per_scenario=3,
        scenario_results=[("get scenario", result)],
    )
    path = tmp_path / "snap.json"
    snap.to_json(path)

    loaded = BenchSnapshot.from_json(path)
    assert loaded.model == snap.model
    assert loaded.runs_per_scenario == snap.runs_per_scenario
    assert len(loaded.scenarios) == 1
    s = loaded.scenarios[0]
    assert s.name == "get scenario"
    assert s.hit_rate == pytest.approx(2 / 3)
    assert s.hits == 2
    assert s.total == 3
    assert s.tool_calls == {"get_user": 2, "list_users": 1}


def test_build_computes_cost_aggregates():
    result = ScenarioResult(prompt="find john", expected_tool="search_users")
    result.runs = [
        ToolCall(tool_called="search_users", params={}, input_tokens=100, output_tokens=20, latency_s=0.4),
        ToolCall(tool_called="search_users", params={}, input_tokens=110, output_tokens=25, latency_s=0.6),
    ]
    snap = BenchSnapshot.build(
        model="claude-sonnet-4-20250514",
        runs_per_scenario=2,
        scenario_results=[("search scenario", result)],
    )
    s = snap.scenarios[0]
    assert s.total_input_tokens == 210
    assert s.total_output_tokens == 45
    assert s.avg_latency_s == pytest.approx(0.5)


def test_from_json_backward_compat_missing_cost_fields(tmp_path):
    # Older snapshot files won't have avg_latency_s/total_input_tokens/total_output_tokens.
    path = tmp_path / "old_snap.json"
    path.write_text(json.dumps({
        "mcpbench_version": "0.3.0",
        "created_at": "2025-05-31T00:00:00Z",
        "model": "claude-sonnet-4-6",
        "runs_per_scenario": 5,
        "scenarios": [
            {
                "name": "search users",
                "expected_tool": "search_users",
                "hit_rate": 0.8,
                "hits": 4,
                "total": 5,
                "tool_calls": {"search_users": 4},
            }
        ],
    }))
    loaded = BenchSnapshot.from_json(path)
    s = loaded.scenarios[0]
    assert s.avg_latency_s == 0.0
    assert s.total_input_tokens == 0
    assert s.total_output_tokens == 0


def test_to_json_schema(tmp_path):
    result = _make_result("find john", "search_users", ["search_users"])
    snap = BenchSnapshot.build("claude-sonnet-4-20250514", 1, [("s", result)])
    path = tmp_path / "snap.json"
    snap.to_json(path)

    data = json.loads(path.read_text())
    assert "mcpbench_version" in data
    assert "created_at" in data
    assert "model" in data
    assert "runs_per_scenario" in data
    assert isinstance(data["scenarios"], list)
    s = data["scenarios"][0]
    for key in (
        "name", "expected_tool", "hit_rate", "hits", "total", "tool_calls",
        "avg_latency_s", "total_input_tokens", "total_output_tokens",
    ):
        assert key in s, f"missing key: {key}"


def test_save_errors_if_file_exists(tmp_path):
    existing = tmp_path / "snap.json"
    existing.write_text("{}")
    snap = BenchSnapshot.build("claude-sonnet-4-20250514", 5, [])

    # to_json always overwrites — the guard lives in the CLI; verify CLI raises
    from click.testing import CliRunner
    from mcpbench.cli import cli

    runner = CliRunner()
    # pass a non-existent test file so _load_bench fails before hitting the API,
    # but the file-exists check happens before that
    result = runner.invoke(cli, ["run", "nonexistent.py", "--save", str(existing)])
    assert result.exit_code != 0
    assert "already exists" in result.output


def test_save_force_overwrites(tmp_path):
    existing = tmp_path / "snap.json"
    existing.write_text('{"old": true}')

    snap = BenchSnapshot.build("claude-sonnet-4-20250514", 5, [])
    snap.to_json(existing)

    loaded = BenchSnapshot.from_json(existing)
    assert loaded.model == "claude-sonnet-4-20250514"

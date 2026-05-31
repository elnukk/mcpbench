import asyncio
import importlib.util
import sys
from pathlib import Path
import click
from mcpbench.bench import MCPBench
from mcpbench.runner import ScenarioResult
from mcpbench.diagnosis import diagnose
from mcpbench.snapshot import BenchSnapshot
from mcpbench.diff import compute_diff


def _load_bench(path: str) -> MCPBench:
    spec = importlib.util.spec_from_file_location("_mcpbench_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    for name in dir(module):
        obj = getattr(module, name)
        if isinstance(obj, MCPBench):
            return obj

    raise click.ClickException(f"No MCPBench instance found in {path}")


def _print_results(
    description: str,
    result: ScenarioResult | None,
    error: Exception | None,
    threshold: float,
):
    if error:
        click.echo(f"✗ {description}")
        click.echo(f"  {error}")
        return False

    n = len(result.runs)
    hits = sum(1 for r in result.runs if r.tool_called == result.expected_tool)
    rate = hits / n
    bar = "█" * hits + "░" * (n - hits)
    passed = rate >= threshold

    mark = "✓" if passed else "✗"
    click.echo(f"{mark} {description:<45} {bar}  {hits}/{n}  ({rate:.0%})")

    if not passed:
        click.echo(f"  ← below threshold ({threshold:.0%})")
        for tool, count in sorted(result.confusion.items(), key=lambda x: -x[1]):
            is_correct = tool == result.expected_tool
            marker = "✓" if is_correct else "✗"
            click.echo(f"    called {tool}: {count}x {marker}")

    return passed


async def _run_all(bench: MCPBench, threshold: float, run_diagnose: bool) -> tuple[bool, list[tuple[str, ScenarioResult | None]]]:
    all_passed = True
    collected: list[tuple[str, ScenarioResult | None]] = []
    for s in bench._scenarios:
        result = None
        error = None
        bench._last_result = None
        try:
            result = await s["fn"]()
            if not isinstance(result, ScenarioResult):
                raise RuntimeError("Scenario function must return the result of bench.run()")
        except Exception as e:
            error_msg = str(e) or f"{type(e).__name__} (no message)"
            error = Exception(error_msg)
            result = bench._last_result

        collected.append((s["description"], result))
        passed = _print_results(s["description"], result, error if result is None else None, threshold)
        if not passed:
            all_passed = False

        if not passed and run_diagnose and result is not None and result.expected_tool:
            wrong = max(
                (t for t in result.confusion if t != result.expected_tool),
                key=lambda t: result.confusion[t],
                default=None,
            )
            if wrong:
                click.echo()
                click.echo("  Diagnosing confusion...")
                try:
                    analysis = await diagnose(result.expected_tool, wrong, result.prompt, result.tools)
                    click.echo(f"\n  Diagnosis: {analysis['diagnosis']}")
                    click.echo(f"\n  Suggestion: {analysis['suggestion']}")
                except Exception as e:
                    click.echo(f"  (diagnosis failed: {e})")

    return all_passed, collected


@click.group()
def cli():
    pass


@cli.command()
@click.argument("path")
@click.option("--runs", default=5, show_default=True, help="Number of times to run each scenario")
@click.option("--threshold", default=0.8, show_default=True, help="Minimum hit rate to pass")
@click.option("--diagnose", "run_diagnose", is_flag=True, default=False, help="Diagnose failing scenarios with Claude")
@click.option("--save", "save_path", default=None, help="Write results to a snapshot JSON file")
@click.option("--force", is_flag=True, default=False, help="Overwrite existing snapshot file")
def run(path: str, runs: int, threshold: float, run_diagnose: bool, save_path: str | None, force: bool):
    """Run mcpbench scenarios from a test file."""
    if save_path and not force and Path(save_path).exists():
        raise click.ClickException(f"{save_path} already exists. Use --force to overwrite.")

    bench = _load_bench(path)
    bench.runs = runs

    click.echo(f"\nRunning {len(bench._scenarios)} scenario(s) × {runs} runs each...\n")

    all_passed, collected = asyncio.run(_run_all(bench, threshold, run_diagnose))

    if save_path:
        snapshot = BenchSnapshot.build(
            model=bench.model,
            runs_per_scenario=runs,
            scenario_results=collected,
        )
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        snapshot.to_json(save_path)
        click.echo(f"\nSnapshot saved to {save_path}")

    click.echo()
    if not all_passed:
        click.echo("Some scenarios below threshold.")
        sys.exit(1)
    else:
        click.echo("All scenarios passed.")


@cli.command("diff")
@click.argument("before_path")
@click.argument("after_path")
@click.option("--regression-threshold", default=0.05, show_default=True, help="Hit-rate drop that counts as a regression")
def diff_cmd(before_path: str, after_path: str, regression_threshold: float):
    """Diff two mcpbench snapshot files."""
    before = BenchSnapshot.from_json(before_path)
    after = BenchSnapshot.from_json(after_path)

    result = compute_diff(before, after, regression_threshold=regression_threshold)

    for warning in result.warnings:
        click.echo(f"Warning: {warning}")

    before_name = Path(before_path).name
    after_name = Path(after_path).name
    click.echo(f"\nComparing {before_name} → {after_name}")

    model_label = after.model or before.model
    runs_label = after.runs_per_scenario or before.runs_per_scenario
    click.echo(f"model: {model_label}  runs: {runs_label}")
    click.echo()

    col_w = 36
    click.echo(f"  {'scenario':<{col_w}} {'before':>6}  {'after':>6}  {'delta':>6}")
    click.echo("  " + "─" * (col_w + 24))

    for d in result.diffs:
        if d.status == "regressed":
            mark = "✗"
        elif d.status == "improved":
            mark = "✓"
        else:
            mark = " "

        before_str = f"{d.before_rate:.0%}" if d.before_rate is not None else "—"
        after_str = f"{d.after_rate:.0%}" if d.after_rate is not None else "—"

        if d.delta is None:
            delta_str = "—"
        elif d.delta == 0:
            delta_str = "—"
        else:
            delta_str = f"{d.delta:+.0%}"

        suffix = "  ← regressed" if d.status == "regressed" else ""
        click.echo(f"{mark} {d.name:<{col_w}} {before_str:>6}  {after_str:>6}  {delta_str:>6}{suffix}")

    regression_count = len(result.regressions)
    click.echo()
    if regression_count:
        click.echo(f"{regression_count} scenario{'s' if regression_count > 1 else ''} regressed.")
        sys.exit(1)
    else:
        click.echo("No regressions.")

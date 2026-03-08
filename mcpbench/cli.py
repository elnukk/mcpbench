import asyncio
import importlib.util
import sys
import click
from mcpbench.bench import MCPBench
from mcpbench.runner import ScenarioResult
from mcpbench.diagnosis import diagnose


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


async def _run_all(bench: MCPBench, threshold: float, run_diagnose: bool) -> bool:
    all_passed = True
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
            # recover the ScenarioResult even if expect() raised after bench.run()
            result = bench._last_result

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

    return all_passed


@click.group()
def cli():
    pass


@cli.command()
@click.argument("path")
@click.option("--runs", default=5, show_default=True, help="Number of times to run each scenario")
@click.option("--threshold", default=0.8, show_default=True, help="Minimum hit rate to pass")
@click.option("--diagnose", "run_diagnose", is_flag=True, default=False, help="Diagnose failing scenarios with Claude")
def run(path: str, runs: int, threshold: float, run_diagnose: bool):
    """Run mcpbench scenarios from a test file."""
    bench = _load_bench(path)
    bench.runs = runs

    click.echo(f"\nRunning {len(bench._scenarios)} scenario(s) × {runs} runs each...\n")

    all_passed = asyncio.run(_run_all(bench, threshold, run_diagnose))

    click.echo()
    if not all_passed:
        click.echo("Some scenarios below threshold.")
        sys.exit(1)
    else:
        click.echo("All scenarios passed.")

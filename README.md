# mcpbench

A testing library for MCP servers. Write a prompt, declare which tool you expect Claude to call, run it N times, and get a hit rate. When something fails, `--diagnose` asks Claude to explain why the tools are being confused and suggest a fix.

---

## The problem

MCP server developers write tool descriptions blind. You ship, and discover in production that Claude keeps calling `list_issues` when the user says "search for issues" — because `search_issues` and `list_issues` have descriptions that are too similar. `mcpbench` is that pre-ship check.

---

## Installation

```bash
pip install toolbench-mcp
```

You'll need an `ANTHROPIC_API_KEY` environment variable set for all runs. The `--diagnose` flag makes additional Claude API calls on top of the benchmark runs.

---

## Usage

### 1. Write a test file

```python
# tests/test_myserver.py
from mcpbench import MCPBench, expect
from myapp.server import mcp  # your FastMCP server

bench = MCPBench(server=mcp, model="claude-sonnet-4-6")

@bench.scenario("user wants to search by name")
async def test_search():
    result = await bench.run("find all users named John", expected_tool="search_users")
    expect(result).called_tool("search_users")
    expect(result).tool_param("query", contains="John")
    return result

@bench.scenario("user wants a specific record")
async def test_get():
    result = await bench.run("get me user with id 42", expected_tool="get_user")
    expect(result).called_tool("get_user")
    expect(result).tool_param("user_id", equals=42)
    return result
```

### Testing restraint

Not every prompt should trigger a tool call, and some prompts have an obvious "wrong but tempting" tool nearby. Pass `expected_tool=None` for prompts where Claude should call nothing, and use `did_not_call_tool` to check a specific distractor was avoided regardless of what else happened:

```python
@bench.scenario("small talk shouldn't trigger a tool call")
async def test_no_tool_needed():
    result = await bench.run("thanks, that's all I needed", expected_tool=None)
    expect(result).abstained()
    return result

@bench.scenario("search shouldn't fall back to delete_user")
async def test_avoids_distractor():
    result = await bench.run("find users named John", expected_tool="search_users")
    expect(result).called_tool("search_users")
    expect(result).did_not_call_tool("delete_user")
    return result
```

### 2. Run it

```bash
mcpbench run tests/test_myserver.py --runs 5
```

```
Running 2 scenario(s) × 5 runs each...

✓ user wants to search by name     ████░  4/5  (80%, 95% CI 38%–96%)
    avg 1.42s/call · 1830 tokens/call
✗ user wants a specific record     ███░░  3/5  (60%, 95% CI 23%–88%)
    avg 1.37s/call · 1795 tokens/call
  ← below threshold (80%)
    called list_users: 2x ✗
    called get_user:   3x ✓

Some scenarios below threshold.
```

Each hit rate comes with a 95% [Wilson score](https://en.wikipedia.org/wiki/Binomial_proportion_confidence_interval#Wilson_score_interval) confidence interval. At `--runs 5`, a 4/5 result is consistent with a true hit rate anywhere from ~38% to ~96%, so a wide interval means you need more runs before trusting the number. Average latency and token usage per call are reported alongside so you can see what a scenario costs.

The N runs of a scenario are sent to Claude concurrently, bounded by `--concurrency` (default 5).

### 3. Diagnose failures

```bash
mcpbench run tests/test_myserver.py --runs 5 --diagnose
```

When a scenario falls below threshold, `--diagnose` sends both tool descriptions plus the failing prompt to Claude and asks it to explain the confusion and suggest a fix:

```
✗ user wants a specific record     ███░░  3/5  (60%, 95% CI 23%–88%)
    avg 1.37s/call · 1795 tokens/call
  ← below threshold (80%)
    called list_users: 2x ✗
    called get_user:   3x ✓

  Diagnosing confusion...

  Diagnosis: Both tools describe retrieving user data, and the prompt "get me
  user with id 42" could match a list operation filtered by ID. The distinction
  between fetching a single record versus listing with a filter isn't clear.

  Suggestion: Update get_user to say "Fetches a single user by their exact
  numeric ID. Use this when you have a specific ID, not for searches or lists."
  Update list_users to clarify it returns multiple records.
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--runs N` | 5 | Number of times to run each scenario |
| `--concurrency N` | 5 | Max concurrent Claude calls per scenario |
| `--threshold F` | 0.8 | Minimum hit rate to pass (0.0–1.0) |
| `--diagnose` | off | Call Claude to explain and suggest fixes for failures |
| `--save PATH` | — | Write results to a JSON snapshot file |
| `--force` | off | Overwrite an existing snapshot file |

Exit code is `1` if any scenario is below threshold — useful for CI.

---

## Saving snapshots and diffing

Once you've edited your tool descriptions, you can compare results before and after with `mcpbench diff`.

**Save a baseline:**

```bash
mcpbench run tests/test_myserver.py --runs 10 --save results/v1.json
```

**Edit your tool descriptions, then save a new snapshot:**

```bash
mcpbench run tests/test_myserver.py --runs 10 --save results/v2.json
```

**Compare them:**

```bash
mcpbench diff results/v1.json results/v2.json
```

```
Comparing v1.json → v2.json
model: claude-sonnet-4-6  runs: 10

  scenario                          before  after   delta
  ─────────────────────────────────────────────────────────
✓ user wants to search by name       80%    100%    +20%  (not stat. significant at this n)
✗ user wants a specific record       60%     40%    -20%  ← regressed  (not stat. significant at this n)
  list open issues in a repo        100%    100%       —
    ⚠ tokens +45%, latency +0.62s (accuracy unchanged)

1 scenario regressed.
```

Exit code is `1` if any scenario regressed — safe to run in CI. Comparison is keyed on scenario name, not position, so reordering scenarios doesn't produce false regressions.

Two extra signals help you read a diff:

- **Statistical significance.** A regression or improvement is marked `(not stat. significant at this n)` when the before and after 95% confidence intervals overlap. The change is still reported and still counts toward the exit code. The marker means the difference could be noise, so rerun with a higher `--runs` to confirm it.
- **Cost changes.** If a scenario's hit rate is unchanged but its average tokens or latency per call moved by 20% or more, `diff` prints a `⚠` line. A description edit that keeps the right tool firing but doubles token spend shows up here.

Snapshots record average latency and token totals per scenario. Snapshots saved by older versions still load, and their cost fields read as zero, so no cost note appears for them.

The default regression threshold is a 5% hit-rate drop. Adjust it with `--regression-threshold`:

```bash
mcpbench diff results/v1.json results/v2.json --regression-threshold 0.1
```

---

## Demo: Testing GitHub's MCP server

GitHub publishes an [official MCP server](https://github.com/github/github-mcp-server). Install it:

```bash
brew install github-mcp-server
```

Set up a transport factory in your test file. Each scenario gets a fresh transport (see [Challenges and lessons learned](#challenges-and-lessons-learned) for why):

```python
# tests/github_server.py
import os
from fastmcp.client.transports import StdioTransport

token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN")

def make_transport() -> StdioTransport:
    return StdioTransport(
        command="github-mcp-server",
        args=["stdio"],
        env={**os.environ, "GITHUB_PERSONAL_ACCESS_TOKEN": token},
        keep_alive=False,
    )
```

```python
# tests/test_github.py
from mcpbench import MCPBench, expect
from tests.github_server import make_transport

bench = MCPBench(server=make_transport(), model="claude-sonnet-4-6")

@bench.scenario("search for open issues in a repo")
async def test_search_issues():
    bench.server = make_transport()
    result = await bench.run(
        "search for open issues in the anthropics/anthropic-sdk-python repo",
        expected_tool="search_issues",
    )
    expect(result).called_tool("search_issues")
    return result

@bench.scenario("list open issues in a repo")
async def test_list_issues():
    bench.server = make_transport()
    result = await bench.run(
        "list all open issues in anthropics/anthropic-sdk-python",
        expected_tool="list_issues",
    )
    expect(result).called_tool("list_issues")
    return result
```

```bash
export GITHUB_TOKEN=ghp_your_token
export ANTHROPIC_API_KEY=sk-ant-your_key

mcpbench run tests/test_github.py --runs 5 --diagnose
```

Results from a real run:

```
Running 2 scenario(s) × 5 runs each...

✗ search for open issues in a repo    ░░░░░  0/5  (0%, 95% CI 0%–43%)
  ← below threshold (80%)
    called list_issues: 5x ✗

  Diagnosing confusion...

  Diagnosis: The LLM is confusing these tools because both descriptions mention
  finding issues in repositories, and the word 'search' in the prompt doesn't
  clearly distinguish between a filtered listing operation versus a query-based
  search. The descriptions don't emphasize that search_issues uses GitHub's
  search syntax for complex queries while list_issues simply retrieves all issues.

  Suggestion: Change search_issues description to clarify it uses GitHub's
  advanced search query syntax (e.g. 'label:bug author:username'). Change
  list_issues to say "Use this for browsing all issues, not for search queries."

✓ list open issues in a repo          █████  5/5  (100%, 95% CI 57%–100%)

Some scenarios below threshold.
```

The diagnosis is correct: `search_issues` and `list_issues` in GitHub's MCP server have overlapping descriptions. The phrase "search for open issues" reads as colloquial English ("find me some issues"), not as a signal to use GitHub's search query API. Claude defaults to the simpler tool. The fix is in the tool descriptions, not the prompts.

---

## Challenges and lessons learned

**Async all the way down.**
FastMCP's client is async. The Anthropic SDK has both sync and async clients. Running everything inside a single `asyncio.run()` call (rather than calling `asyncio.run()` per scenario) was essential; multiple event loops caused `BrokenResourceError` from anyio's internal streams. Using `anthropic.AsyncAnthropic` as an async context manager (`async with`) ensures httpx connections are closed cleanly between calls.

**External MCP servers need a fresh process per session.**
The `github-mcp-server` binary speaks stdio MCP and exits after one session. FastMCP's `StdioTransport` defaults to `keep_alive=True`, which tries to reuse the process. Setting `keep_alive=False` forces a fresh subprocess per connection, which is the right behavior for servers that don't support persistent sessions.

**A stdio server's shutdown chatter can crash the client — and permanently break a shared transport.**
Some stdio MCP servers (`github-mcp-server` included) send notifications as part of their own shutdown sequence, racing the client's stream teardown. The `mcp` SDK's stdio client only guards against `anyio.ClosedResourceError` during that race, not the sibling `anyio.BrokenResourceError` — so it can surface even though the actual tool call you cared about already completed. `mcpbench` tolerates this specific race once it already has the data it needs (see `_get_anthropic_tools` in `runner.py`). Separately, some `fastmcp` versions' `StdioTransport.disconnect()` don't reset their internal connection state if that error propagates, which permanently breaks *that transport instance* for future reconnects. If you see "Client failed to connect" on the second scenario in a test file but not the first, construct a fresh transport per scenario instead of sharing one `StdioTransport` object across `bench.scenario` functions — see `tests/github_server.py`'s `make_transport()`.

**Hit rate is noisy at small N.**
A prompt that sits at 60% true hit rate will sometimes score 100% and sometimes 0% over 5 runs. The benchmark is most useful for catching clear failures (0–20%) and validating clear wins (100%). Borderline prompts need higher `--runs` to be meaningful. This is why `mcpbench` prints a confidence interval next to every hit rate and marks diffs whose intervals overlap: the CLI shows you when N is too small, so you don't have to work it out yourself.

---

## Contributing

Contributions are welcome. Here's how to get started:

```bash
git clone https://github.com/elnukk/mcpbench
cd mcp-bench
pip install -e ".[dev]"
pytest --ignore=tests/test_github.py
```

The unit tests (`test_stats.py`, `test_expect.py`, `test_runner.py`, `test_diff.py`) run offline. `tests/test_github.py` is an mcpbench scenario file, not a pytest suite, so it's excluded above. Run it with `mcpbench run`, which needs `GITHUB_TOKEN` and `ANTHROPIC_API_KEY`.

**Good first contributions:**
- Add support for testing against HTTP/SSE MCP servers (currently only stdio is documented)
- Add a `--model` flag to the CLI so you can benchmark against different Claude models without editing the test file
- Add CSV output format for snapshot data
- Write test scenarios for other popular MCP servers (Slack, Linear, Notion, etc.)

**Bigger ideas:**
- Auto-fix mode (`--fix`) — apply the `--diagnose` suggestion to a copy of the tool descriptions, rerun the scenarios, and report the before/after diff, so a suggested fix comes with evidence that it works
- Multi-turn scenarios — test tool selection partway through a conversation (e.g. after `search_issues` returns, does Claude call `get_issue` next?), including assertions on ordered tool sequences
- Whole-server confusion matrix — auto-generate prompts for every tool on a server and report which tool pairs get confused most, auditing a server without hand-written scenarios
- GitHub Actions template — drop-in workflow for running mcpbench and saving snapshots on every PR

**To submit a PR:**
1. Fork the repo and create a branch
2. Make your change
3. Add a scenario in `tests/` that exercises it
4. Open a PR with a description of what you changed and why

If you've benchmarked an interesting MCP server and found surprising results, opening an issue with your findings is also a useful contribution.

---

## Requirements

- Python 3.11+
- `anthropic`, `fastmcp`, `click`
- `ANTHROPIC_API_KEY` environment variable

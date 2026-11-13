import pytest
from mcpbench.expect import expect
from mcpbench.runner import ScenarioResult, ToolCall


def _make_result(expected: str | None, calls: list[str | None]) -> ScenarioResult:
    result = ScenarioResult(prompt="prompt", expected_tool=expected)
    result.runs = [ToolCall(tool_called=c, params={}) for c in calls]
    return result


def test_called_tool_passes():
    result = _make_result("search_users", ["search_users", "search_users", "list_users"])
    expect(result).called_tool("search_users")


def test_called_tool_fails():
    result = _make_result("search_users", ["list_users", "list_users", "search_users"])
    with pytest.raises(AssertionError):
        expect(result).called_tool("search_users")


def test_abstained_passes():
    result = _make_result(None, [None, None, "search_users"])
    expect(result).abstained()


def test_abstained_fails():
    result = _make_result(None, ["search_users", "search_users", None])
    with pytest.raises(AssertionError):
        expect(result).abstained()


def test_did_not_call_tool_passes():
    result = _make_result("search_users", ["search_users", "search_users", "search_users"])
    expect(result).did_not_call_tool("delete_user")


def test_did_not_call_tool_fails():
    result = _make_result("search_users", ["search_users", "delete_user", "search_users"])
    with pytest.raises(AssertionError):
        expect(result).did_not_call_tool("delete_user")


def test_hit_rate_with_expected_tool_none_counts_abstentions():
    result = _make_result(None, [None, None, "search_users", None])
    assert result.hit_rate == pytest.approx(0.75)


def test_hit_rate_with_expected_tool_none_all_calls_made():
    result = _make_result(None, ["search_users", "list_users"])
    assert result.hit_rate == pytest.approx(0.0)

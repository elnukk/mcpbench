from mcpbench.runner import ScenarioResult


class Expect:
    def __init__(self, result: ScenarioResult):
        self.result = result

    def called_tool(self, name: str) -> "Expect":
        most_common = max(self.result.confusion, key=self.result.confusion.get, default=None)
        if most_common != name:
            hits = self.result.confusion.get(name, 0)
            total = len(self.result.runs)
            raise AssertionError(
                f"Expected {name} (got {most_common} {self.result.confusion.get(most_common, 0)}/{total} times, "
                f"{name} only {hits}/{total} times)"
            )
        return self

    def tool_param(self, key: str, contains: str | None = None, equals=None) -> "Expect":
        successful = [r for r in self.result.runs if r.tool_called == self.result.expected_tool]
        if not successful:
            raise AssertionError(f"No successful runs to check param {key!r}")
        for run in successful:
            value = run.params.get(key)
            if equals is not None and value != equals:
                raise AssertionError(f"Param {key!r}: expected {equals!r}, got {value!r}")
            if contains is not None and (value is None or contains not in str(value)):
                raise AssertionError(f"Param {key!r}: expected to contain {contains!r}, got {value!r}")
        return self


def expect(result: ScenarioResult) -> Expect:
    return Expect(result)

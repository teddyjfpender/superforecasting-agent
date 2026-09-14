"""References never stand in for changed, failed or no-longer-retained evidence."""

import pytest

from agent.result_references import ResultReferences


@pytest.mark.parametrize(
    "change", ["content", "args", "name", "failure", "pruned", "edited", "multimodal"]
)
def test_changed_or_unavailable_original_is_not_referenced(change):
    tracker = ResultReferences()
    raw = "evidence " * 100
    assert (
        tracker.compact("read", {"path": "a"}, raw, "original", [], failed=False) == raw
    )
    history = [{"role": "tool", "tool_call_id": "original", "content": raw}]
    args, name, result, failed = {"path": "a"}, "read", raw, False
    if change == "content":
        result += "new measurement"
    elif change == "args":
        args = {"path": "b"}
    elif change == "name":
        name = "other"
    elif change == "failure":
        failed = True
    elif change == "pruned":
        history = []
    elif change == "edited":
        history[0]["content"] = "compacted"
    elif change == "multimodal":
        result = [{"type": "text", "text": raw}]
    assert tracker.compact(name, args, result, "next", history, failed=failed) == result


def test_intervening_call_resets_chain():
    tracker = ResultReferences()
    raw = "evidence " * 100
    tracker.compact("read", {}, raw, "a", [], failed=False)
    history = [{"role": "tool", "tool_call_id": "a", "content": raw}]
    tracker.compact("other", {}, "small", "b", history, failed=False)
    assert tracker.compact("read", {}, raw, "c", history, failed=False) == raw

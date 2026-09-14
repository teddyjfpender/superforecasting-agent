"""The recall control must expose omissions without leaking gold answers."""

from types import SimpleNamespace

from scripts.evaluate_context_recall import FACTS, evaluate


def test_control_distinguishes_lossy_summary_from_exact_retention():
    report = evaluate()
    assert report["mode"] == "mechanical_retention"
    policies = report["policies"]
    assert all(policies["uncompacted_control"]["exact_retention"].values())
    assert not any(policies["lossy_summary_control"]["exact_retention"].values())
    assert all(policies["lossy_summary_with_exact_index"]["exact_retention"].values())


def test_model_conditions_are_independent_and_lossy_control_has_no_gold(monkeypatch):
    calls = []

    def provider(**kwargs):
        content = kwargs["messages"][-1]["content"]
        key = content.rsplit("exact ", 1)[1].removesuffix("?")
        expected = FACTS[key]
        answer = expected if expected in content else "UNKNOWN"
        calls.append(content)
        return SimpleNamespace(model="frozen-fake", choices=[SimpleNamespace(message=SimpleNamespace(content=answer))])

    monkeypatch.setattr("agent.auxiliary_client.call_llm", provider)
    report = evaluate("local", "fake")
    assert all(item["exact_match"] for item in report["policies"]["uncompacted_control"]["recall"].values())
    assert not any(item["exact_match"] for item in report["policies"]["lossy_summary_control"]["recall"].values())
    assert all(item["exact_match"] for item in report["policies"]["lossy_summary_with_exact_index"]["recall"].values())
    assert all("UNKNOWN" not in content for content in calls)

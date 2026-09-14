from superforecasting_agent.runtime import cli_output


def test_password_prompt_uses_masked_secret_prompt(monkeypatch):
    seen = {}

    def fake_masked_secret_prompt(display):
        seen["display"] = display
        return " secret "

    monkeypatch.setattr(cli_output, "masked_secret_prompt", fake_masked_secret_prompt)

    assert cli_output.prompt("API key", default="old", password=True) == "secret"
    assert "API key [old]" in seen["display"]


def test_empty_password_prompt_returns_default(monkeypatch):
    monkeypatch.setattr(cli_output, "masked_secret_prompt", lambda _display: "")

    assert cli_output.prompt("API key", default="old", password=True) == "old"


import pytest


@pytest.mark.parametrize("error", [KeyboardInterrupt, EOFError])
def test_cancelled_confirmation_never_accepts_default(monkeypatch, error):
    def cancel(_display):
        raise error

    monkeypatch.setattr("builtins.input", cancel)
    assert cli_output.prompt_yes_no("Replace settings?", default=True) is False
    assert cli_output.prompt("Optional value") == ""


@pytest.mark.parametrize("answer,expected", [("", True), ("yes", True), ("Y", True), ("no", False)])
def test_confirmation_requires_explicit_yes_or_enter(monkeypatch, answer, expected):
    monkeypatch.setattr("builtins.input", lambda _: answer)
    assert cli_output.prompt_yes_no("Continue?") is expected


@pytest.mark.parametrize("surface", ["shared", "setup"])
def test_invalid_confirmation_reprompts_consistently(monkeypatch, capsys, surface):
    from superforecasting_agent.runtime import setup

    answers = iter(["yesterday", "n"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    owner = cli_output if surface == "shared" else setup
    assert owner.prompt_yes_no("Continue?") is False
    assert "Please enter 'y' or 'n'" in capsys.readouterr().out

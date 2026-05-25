"""Regression tests for fork-native contributor audit defaults."""

from __future__ import annotations

import json

from scripts import contributor_audit


def test_default_github_repo_is_fork_native():
    assert contributor_audit.DEFAULT_GITHUB_REPO == "teddyjfpender/superforecasting-agent"


def test_gh_pr_list_uses_supplied_repo(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))

        class Result:
            returncode = 0
            stdout = json.dumps([])
            stderr = ""

        return Result()

    monkeypatch.setattr(contributor_audit.subprocess, "run", fake_run)

    assert contributor_audit.gh_pr_list("owner/project") == []
    args, kwargs = calls[0]
    assert args[args.index("--repo") + 1] == "owner/project"
    assert kwargs["timeout"] == 60


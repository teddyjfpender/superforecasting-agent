from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from forecasting import ForecastLedger
from forecasting.cli import collaboration_admin
from forecasting.workspace import export_workspace


def _parse(*argv: str):
    parser = argparse.ArgumentParser()
    collaboration_admin.register_cli(parser.add_subparsers(dest="command"))
    return parser.parse_args(list(argv))


def test_workspace_init_exports_and_links(tmp_path, monkeypatch, capsys):
    ledger = ForecastLedger(tmp_path / "ledger.db")
    destination = tmp_path / "managed" / "repository"
    links = []
    monkeypatch.setattr(collaboration_admin, "managed_checkout_path", lambda _: destination)
    monkeypatch.setattr(collaboration_admin, "_save_link", lambda **value: links.append(value))

    args = _parse(
        "workspace",
        "--db",
        str(ledger.db_path),
        "init",
        "desk_1",
        "--repository",
        "owner/ledger",
        "--json",
    )
    args.func(args)

    assert (destination / "forecast-workspace.yaml").is_file()
    assert links == [
        {"repository": "owner/ledger", "workspace_id": "desk_1", "default_branch": "main"}
    ]
    assert '"action": "initialized"' in capsys.readouterr().out


def test_workspace_clone_activates_only_after_validated_bootstrap(tmp_path, monkeypatch):
    source_ledger = ForecastLedger(tmp_path / "source.db")
    source = tmp_path / "source-workspace"
    export_workspace(source_ledger, source, workspace_id="desk_clone")
    home = tmp_path / "home"
    final_checkout = home / "workspaces" / "desk_clone" / "repository"
    links = []

    class FakeGit:
        def clone(self, _source, destination, **_kwargs):
            shutil.copytree(source, destination)

    monkeypatch.setattr(collaboration_admin, "ManagedGit", FakeGit)
    monkeypatch.setattr(collaboration_admin, "get_hermes_home", lambda: home)
    monkeypatch.setattr(
        collaboration_admin,
        "managed_checkout_path",
        lambda workspace_id: home / "workspaces" / workspace_id / "repository",
    )
    monkeypatch.setattr(collaboration_admin, "_save_link", lambda **value: links.append(value))

    args = _parse("workspace", "clone", "owner/ledger", "--json")
    args.func(args)

    assert final_checkout.is_dir()
    assert (final_checkout.parent / "forecasting.db").is_file()
    assert links[0]["ledger_path"] == final_checkout.parent / "forecasting.db"
    assert not list((home / "workspaces").glob(".staging-*"))


def test_workspace_reconcile_requires_explicit_confirmation(monkeypatch):
    monkeypatch.setattr(
        collaboration_admin,
        "_linked",
        lambda: ("owner/ledger", "desk_1", "main"),
    )
    args = _parse("workspace", "reconcile", "--from-ledger")
    try:
        args.func(args)
    except Exception as exc:
        assert "--yes" in str(exc)
    else:
        raise AssertionError("reconcile unexpectedly ran without confirmation")

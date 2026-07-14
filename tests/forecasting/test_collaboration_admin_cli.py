from __future__ import annotations

import argparse
import base64
import shutil

import pytest

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


def test_github_status_and_changeset_commands_never_emit_token_ciphertext(tmp_path, capsys):
    ledger = ForecastLedger(tmp_path / "ledger.db")
    from forecasting.change_control import ChangeControl

    control = ChangeControl(ledger)
    binding = control.bind_identity(
        owner_id="owner_1",
        slack_team_id="T1",
        slack_user_id="U1",
        agent_instance_id="agent_1",
        agent_persona="Mira",
        github_user_id="101",
        github_node_id="node-101",
        github_login="octocat",
    )
    with ledger._connect() as conn:
        conn.execute(
            """INSERT INTO github_user_tokens
               (id, identity_binding_id, access_ciphertext, token_type, status,
                created_at, updated_at)
               VALUES ('token_1', ?, 'ciphertext-secret', 'bearer', 'active',
                       datetime('now'), datetime('now'))""",
            (binding["id"],),
        )
    changeset = control.create_changeset(workspace_id="desk_1")

    status = _parse("github", "--db", str(ledger.db_path), "status", "--json")
    status.func(status)
    listed = _parse("changeset", "--db", str(ledger.db_path), "list", "--json")
    listed.func(listed)
    shown = _parse(
        "changeset", "--db", str(ledger.db_path), "show", changeset["id"], "--json"
    )
    shown.func(shown)
    output = capsys.readouterr().out

    assert "octocat" in output
    assert changeset["id"] in output
    assert "ciphertext-secret" not in output


def test_github_install_starts_exact_app_flow(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        collaboration_admin,
        "_configuration",
        lambda: (
            {
                "github": {
                    "app_id": "1234",
                    "app_slug": "forecast-desk",
                    "installation_state_ttl_seconds": 600,
                }
            },
            {"slug": "acme/forecasts"},
        ),
    )
    args = _parse(
        "github", "--db", str(tmp_path / "ledger.db"), "install", "--json"
    )
    args.func(args)
    output = capsys.readouterr().out
    assert "https://github.com/apps/forecast-desk/installations/new" in output
    assert "acme/forecasts" in output


def test_changeset_mutations_require_confirmation(tmp_path):
    ledger = ForecastLedger(tmp_path / "ledger.db")
    from forecasting.change_control import ChangeControl

    changeset = ChangeControl(ledger).create_changeset(workspace_id="desk_1")
    args = _parse("changeset", "--db", str(ledger.db_path), "abandon", changeset["id"])
    with pytest.raises(Exception, match="--yes"):
        args.func(args)


def test_review_policy_and_status_are_inspectable(tmp_path, monkeypatch, capsys):
    ledger = ForecastLedger(tmp_path / "ledger.db")
    from forecasting.change_control import ChangeControl

    control = ChangeControl(ledger)
    changeset = control.create_changeset(workspace_id="desk_1")
    monkeypatch.setattr(
        collaboration_admin,
        "_configuration",
        lambda: (
            {"review": {"materiality_threshold": 0.15, "risk_overrides": {}}},
            {},
        ),
    )

    policy = _parse("changeset", "--db", str(ledger.db_path), "review-policy", "--json")
    policy.func(policy)
    status = _parse(
        "changeset", "--db", str(ledger.db_path), "review-status",
        changeset["id"], "--json",
    )
    status.func(status)
    output = capsys.readouterr().out

    assert '"materiality_threshold": 0.15' in output
    assert changeset["id"] in output
    assert '"ledger_apply_status": "draft"' in output


def test_trace_retention_and_access_audit_never_emit_private_content(tmp_path, capsys):
    from forecasting.change_control import ChangeControl
    from forecasting.change_control.trace_archive import (
        capture_trace_archive,
        read_trace_archive,
    )

    ledger = ForecastLedger(tmp_path / "ledger.db")
    control = ChangeControl(ledger)
    changeset = control.create_changeset(workspace_id="desk_1")
    key = base64.urlsafe_b64encode(b"k" * 32).decode()
    archive = capture_trace_archive(
        ledger,
        changeset["id"],
        {"private": "raw transcript must never print"},
        workspace_key=key,
        retention_days=0,
        object_dir=tmp_path / "private",
    )
    with pytest.raises(PermissionError):
        read_trace_archive(
            ledger,
            archive["id"],
            actor_id="auditor_1",
            reason="private review reason",
            authorize=lambda record, actor: False,
            workspace_key=key,
        )

    retention = _parse(
        "changeset", "--db", str(ledger.db_path), "transcript-retention",
        "--sweep", "--dry-run", "--json",
    )
    retention.func(retention)
    access = _parse(
        "changeset", "--db", str(ledger.db_path), "transcript-access-audit",
        "--archive-id", archive["id"], "--json",
    )
    access.func(access)
    output = capsys.readouterr().out

    assert archive["id"] in output
    assert "raw transcript must never print" not in output
    assert "private review reason" not in output
    assert "reason_digest" in output
    assert "object_locator" not in output

    destructive = _parse(
        "changeset", "--db", str(ledger.db_path), "transcript-retention", "--sweep"
    )
    with pytest.raises(Exception, match="--yes"):
        destructive.func(destructive)

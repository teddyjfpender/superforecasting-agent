"""Local administration for portable forecast workspaces and changesets."""

from __future__ import annotations

import argparse
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from hermes_constants import get_hermes_home
from hermes_cli.config import get_config_path, load_config
from utils import atomic_roundtrip_yaml_update

from forecasting import ForecastLedger
from forecasting.change_control import ChangeControl
from forecasting.models import ValidationError
from forecasting.workspace import (
    ManagedGit,
    bootstrap_workspace,
    export_workspace,
    managed_checkout_path,
    validate_workspace,
)
from forecasting.workspace.manifest import WorkspaceManifest


_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def register_cli(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "workspace",
        help="Manage the portable Git-backed forecast workspace",
    )
    parser.add_argument("--db", help="Override the active forecast ledger database")
    commands = parser.add_subparsers(dest="workspace_command", required=True)

    init = commands.add_parser("init", help="Export and link a new managed workspace")
    init.add_argument("workspace_id")
    init.add_argument("--repository", help="Canonical GitHub repository as OWNER/REPO")
    init.add_argument("--default-branch", default="main")
    init.add_argument("--dry-run", action="store_true")
    init.add_argument("--json", action="store_true")
    init.set_defaults(func=_cmd_init)

    clone = commands.add_parser("clone", help="Clone, validate, and reconstruct a workspace")
    clone.add_argument("repository", help="Canonical GitHub repository as OWNER/REPO")
    clone.add_argument("--default-branch", default="main")
    clone.add_argument("--dry-run", action="store_true")
    clone.add_argument("--json", action="store_true")
    clone.set_defaults(func=_cmd_clone)

    link = commands.add_parser("link", help="Link an existing managed checkout")
    link.add_argument("repository", help="Canonical GitHub repository as OWNER/REPO")
    link.add_argument("--workspace-id", required=True)
    link.add_argument("--default-branch", default="main")
    link.add_argument("--dry-run", action="store_true")
    link.add_argument("--json", action="store_true")
    link.set_defaults(func=_cmd_link)

    status = commands.add_parser("status", help="Inspect ledger/repository alignment")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=_cmd_status)

    pull = commands.add_parser("pull", help="Fast-forward a clean managed checkout")
    pull.add_argument("--dry-run", action="store_true")
    pull.add_argument("--json", action="store_true")
    pull.set_defaults(func=_cmd_pull)

    export = commands.add_parser("export", help="Regenerate portable state from the ledger")
    export.add_argument("--output", type=Path)
    export.add_argument("--dry-run", action="store_true")
    export.add_argument("--json", action="store_true")
    export.set_defaults(func=_cmd_export)

    reconcile = commands.add_parser(
        "reconcile", help="Repair portable state or replay a merged changeset"
    )
    mode = reconcile.add_mutually_exclusive_group()
    mode.add_argument("--from-ledger", action="store_true")
    mode.add_argument("--apply-merged", metavar="CHANGESET_ID")
    reconcile.add_argument("--yes", action="store_true", help="Confirm the requested repair")
    reconcile.add_argument("--dry-run", action="store_true")
    reconcile.add_argument("--json", action="store_true")
    reconcile.set_defaults(func=_cmd_reconcile)

    github = subparsers.add_parser("github", help="Manage delegated GitHub identities")
    github.add_argument("--db", help="Override the active forecast ledger database")
    github_commands = github.add_subparsers(dest="github_command", required=True)
    auth = github_commands.add_parser("auth", help="Begin GitHub App user authorization")
    for flag in ("owner-id", "slack-team-id", "slack-user-id", "agent-instance-id", "agent-persona"):
        auth.add_argument(f"--{flag}", required=True)
    auth.add_argument("--agent-avatar-url")
    auth.add_argument("--slack-bot-user-id")
    auth.add_argument("--json", action="store_true")
    auth.set_defaults(func=_cmd_github_auth)
    install = github_commands.add_parser("install", help="Open the GitHub App installation flow")
    install.add_argument("--json", action="store_true")
    install.set_defaults(func=_cmd_github_install)
    github_status = github_commands.add_parser("status", help="List linked identities safely")
    github_status.add_argument("--json", action="store_true")
    github_status.set_defaults(func=_cmd_github_status)
    revoke = github_commands.add_parser("revoke", help="Revoke a delegated GitHub identity")
    revoke.add_argument("binding_id")
    revoke.add_argument("--yes", action="store_true")
    revoke.add_argument("--json", action="store_true")
    revoke.set_defaults(func=_cmd_github_revoke)

    changeset = subparsers.add_parser("changeset", help="Inspect and recover ledger changesets")
    changeset.add_argument("--db", help="Override the active forecast ledger database")
    changeset_commands = changeset.add_subparsers(dest="changeset_command", required=True)
    changeset_list = changeset_commands.add_parser("list", help="List ledger changesets")
    changeset_list.add_argument("--workspace-id")
    changeset_list.add_argument("--status")
    changeset_list.add_argument("--limit", type=int, default=100)
    changeset_list.add_argument("--json", action="store_true")
    changeset_list.set_defaults(func=_cmd_changeset_list)
    for name, handler, help_text in (
        ("show", _cmd_changeset_show, "Show one changeset"),
        ("preview", _cmd_changeset_preview, "Validate and preview operations"),
    ):
        command = changeset_commands.add_parser(name, help=help_text)
        command.add_argument("changeset_id")
        command.add_argument("--json", action="store_true")
        command.set_defaults(func=handler)

    review_policy = changeset_commands.add_parser(
        "review-policy", help="Show effective changeset risk and quorum policy"
    )
    review_policy.add_argument("--json", action="store_true")
    review_policy.set_defaults(func=_cmd_review_policy)
    review_status = changeset_commands.add_parser(
        "review-status", help="Show current review and quorum state"
    )
    review_status.add_argument("changeset_id", nargs="?")
    review_status.add_argument("--limit", type=int, default=100)
    review_status.add_argument("--json", action="store_true")
    review_status.set_defaults(func=_cmd_review_status)
    retention = changeset_commands.add_parser(
        "transcript-retention", help="Audit or sweep private trace retention"
    )
    retention.add_argument("--changeset-id")
    retention.add_argument("--state")
    retention.add_argument("--limit", type=int, default=100)
    retention.add_argument("--sweep", action="store_true")
    retention.add_argument("--yes", action="store_true")
    retention.add_argument("--dry-run", action="store_true")
    retention.add_argument("--json", action="store_true")
    retention.set_defaults(func=_cmd_transcript_retention)
    access = changeset_commands.add_parser(
        "transcript-access-audit", help="Audit private trace access without trace content"
    )
    access.add_argument("--changeset-id")
    access.add_argument("--archive-id")
    access.add_argument("--actor-id")
    access.add_argument("--limit", type=int, default=100)
    access.add_argument("--json", action="store_true")
    access.set_defaults(func=_cmd_transcript_access_audit)
    for name, handler, help_text in (
        ("apply", _cmd_changeset_apply, "Apply a merge-ready changeset"),
        ("retry", _cmd_changeset_retry, "Retry a transient merge-apply failure"),
        ("abandon", _cmd_changeset_abandon, "Abandon an unmerged changeset"),
    ):
        command = changeset_commands.add_parser(name, help=help_text)
        command.add_argument("changeset_id")
        command.add_argument("--yes", action="store_true")
        command.add_argument("--dry-run", action="store_true")
        command.add_argument("--json", action="store_true")
        command.set_defaults(func=handler)


def _ledger(args: argparse.Namespace) -> ForecastLedger:
    return ForecastLedger(getattr(args, "db", None))


def _repository(value: str) -> str:
    value = str(value or "").strip()
    if not _REPOSITORY.fullmatch(value):
        raise ValidationError("repository must use OWNER/REPO form")
    return value


def _configuration() -> tuple[dict[str, Any], dict[str, Any]]:
    collaboration = dict(load_config().get("collaboration") or {})
    return collaboration, dict(collaboration.get("repository") or {})


def _linked() -> tuple[str, str, str]:
    _, repository = _configuration()
    slug = _repository(str(repository.get("slug") or ""))
    workspace_id = str(repository.get("workspace_id") or "").strip()
    branch = str(repository.get("default_branch") or "main").strip()
    if not workspace_id:
        raise ValidationError("no forecast workspace is linked")
    return slug, workspace_id, branch


def _save_link(
    *,
    repository: str,
    workspace_id: str,
    default_branch: str,
    ledger_path: Path | None = None,
) -> None:
    path = get_config_path()
    for key, value in (
        ("collaboration.enabled", True),
        ("collaboration.github.enabled", True),
        ("collaboration.repository.slug", repository),
        ("collaboration.repository.workspace_id", workspace_id),
        ("collaboration.repository.default_branch", default_branch),
    ):
        atomic_roundtrip_yaml_update(path, key, value)
    if ledger_path is not None:
        atomic_roundtrip_yaml_update(path, "env.FORECAST_LEDGER_DB", str(ledger_path))
    try:
        path.chmod(0o600)
    except (OSError, NotImplementedError):
        pass


def _emit(args: argparse.Namespace, payload: dict[str, Any]) -> None:
    if getattr(args, "json", False):
        print(json.dumps(payload, sort_keys=True, indent=2))
        return
    for key, value in payload.items():
        print(f"{key}: {json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value}")


def _credential_callback():
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        return None
    return lambda: ("x-access-token", token)


def _cmd_init(args: argparse.Namespace) -> None:
    workspace_id = str(args.workspace_id).strip()
    destination = managed_checkout_path(workspace_id)
    repository = _repository(args.repository) if args.repository else ""
    if args.dry_run:
        _emit(args, {"action": "init", "workspace_id": workspace_id, "path": str(destination)})
        return
    if destination.exists() and any(destination.iterdir()):
        raise ValidationError(f"managed workspace already exists: {destination}")
    manifest = export_workspace(
        _ledger(args), destination, workspace_id=workspace_id, default_branch=args.default_branch
    )
    if repository:
        _save_link(
            repository=repository,
            workspace_id=workspace_id,
            default_branch=args.default_branch,
        )
    _emit(
        args,
        {
            "action": "initialized",
            "workspace_id": workspace_id,
            "path": str(destination),
            "content_digest": manifest.content_digest,
            "linked": bool(repository),
        },
    )


def _cmd_clone(args: argparse.Namespace) -> None:
    repository = _repository(args.repository)
    source = f"https://github.com/{repository}.git"
    staging = get_hermes_home() / "workspaces" / f".staging-{uuid.uuid4().hex[:12]}"
    if args.dry_run:
        _emit(args, {"action": "clone", "repository": repository, "staging_path": str(staging)})
        return
    checkout = staging / "repository"
    try:
        ManagedGit().clone(
            source,
            checkout,
            branch=args.default_branch,
            credential_callback=_credential_callback(),
        )
        report = validate_workspace(checkout, raise_on_error=True)
        manifest = WorkspaceManifest.from_yaml(
            (checkout / "forecast-workspace.yaml").read_text("utf-8")
        )
        final_root = managed_checkout_path(manifest.workspace_id).parent
        if final_root.exists():
            raise ValidationError(f"managed workspace already exists: {final_root}")
        bootstrap_workspace(checkout, staging / "forecasting.db")
        final_root.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, final_root)
        _save_link(
            repository=repository,
            workspace_id=manifest.workspace_id,
            default_branch=manifest.default_branch,
            ledger_path=final_root / "forecasting.db",
        )
    except Exception as exc:
        raise ValidationError(f"workspace clone failed; resumable staging path: {staging}: {exc}") from exc
    _emit(
        args,
        {
            "action": "cloned",
            "repository": repository,
            "workspace_id": manifest.workspace_id,
            "path": str(final_root / "repository"),
            "ledger_path": str(final_root / "forecasting.db"),
            "content_digest": report.content_digest,
        },
    )


def _cmd_link(args: argparse.Namespace) -> None:
    repository = _repository(args.repository)
    checkout = managed_checkout_path(args.workspace_id)
    if checkout.is_dir():
        report = validate_workspace(checkout)
        if not report.valid:
            raise ValidationError("managed checkout is invalid: " + "; ".join(report.errors))
        manifest = WorkspaceManifest.from_yaml(
            (checkout / "forecast-workspace.yaml").read_text("utf-8")
        )
        if manifest.workspace_id != args.workspace_id:
            raise ValidationError("managed checkout workspace identity does not match")
    if not args.dry_run:
        _save_link(
            repository=repository,
            workspace_id=args.workspace_id,
            default_branch=args.default_branch,
        )
    _emit(
        args,
        {
            "action": "link" if args.dry_run else "linked",
            "repository": repository,
            "workspace_id": args.workspace_id,
            "path": str(checkout),
        },
    )


def _status_payload(args: argparse.Namespace) -> dict[str, Any]:
    from forecasting.collaboration_health import collaboration_health

    health = collaboration_health(_ledger(args))
    try:
        repository, workspace_id, branch = _linked()
    except ValidationError:
        return {
            "linked": False,
            "github_merge_status": "unlinked",
            "ledger_apply_status": "local",
            "collaboration_health": health,
        }
    checkout = managed_checkout_path(workspace_id)
    payload: dict[str, Any] = {
        "linked": True,
        "repository": repository,
        "workspace_id": workspace_id,
        "default_branch": branch,
        "path": str(checkout),
        "github_merge_status": "unknown",
        "ledger_apply_status": "authoritative-local",
        "collaboration_health": health,
    }
    if not checkout.is_dir():
        payload["repository_status"] = "missing"
        return payload
    payload["git"] = ManagedGit().status(checkout)
    report = validate_workspace(checkout)
    payload["validation"] = {
        "valid": report.valid,
        "errors": list(report.errors),
        "content_digest": report.content_digest,
    }
    payload["ledger_revision"] = ChangeControl(_ledger(args)).current_revision()["revision"]
    return payload


def _cmd_status(args: argparse.Namespace) -> None:
    _emit(args, _status_payload(args))


def _cmd_pull(args: argparse.Namespace) -> None:
    _, workspace_id, _ = _linked()
    checkout = managed_checkout_path(workspace_id)
    if args.dry_run:
        payload = _status_payload(args)
        payload["action"] = "pull"
        _emit(args, payload)
        return
    status = ManagedGit().pull_ff_only(
        checkout, credential_callback=_credential_callback()
    )
    report = validate_workspace(checkout, raise_on_error=True)
    _emit(args, {"action": "pulled", "git": status, "content_digest": report.content_digest})


def _cmd_export(args: argparse.Namespace) -> None:
    _, workspace_id, branch = _linked()
    destination = getattr(args, "output", None) or managed_checkout_path(workspace_id)
    if args.dry_run:
        _emit(args, {"action": "export", "workspace_id": workspace_id, "path": str(destination)})
        return
    manifest = export_workspace(
        _ledger(args), destination, workspace_id=workspace_id, default_branch=branch
    )
    validate_workspace(destination, raise_on_error=True)
    _emit(
        args,
        {
            "action": "exported",
            "workspace_id": workspace_id,
            "path": str(destination),
            "ledger_revision": manifest.ledger_revision,
            "content_digest": manifest.content_digest,
        },
    )


def _cmd_reconcile(args: argparse.Namespace) -> None:
    if not args.from_ledger and not args.apply_merged:
        _emit(args, _status_payload(args))
        return
    action = "export authoritative ledger" if args.from_ledger else f"apply {args.apply_merged}"
    if args.dry_run:
        _emit(args, {"action": action, "dry_run": True})
        return
    if not args.yes:
        raise ValidationError("reconcile changes state; rerun with --yes after review")
    if args.from_ledger:
        _cmd_export(args)
        return
    _, workspace_id, _ = _linked()
    validate_workspace(managed_checkout_path(workspace_id), raise_on_error=True)
    result = ChangeControl(_ledger(args)).apply(args.apply_merged)
    _emit(
        args,
        {
            "action": "applied",
            "changeset_id": args.apply_merged,
            "github_merge_status": "merged",
            "ledger_apply_status": "applied",
            "result": result,
        },
    )


def _github_oauth(args: argparse.Namespace):
    from urllib.parse import urljoin

    from forecasting.github import GitHubOAuthService

    collaboration, _ = _configuration()
    github = collaboration.get("github") or {}
    client_secret = os.environ.get("GITHUB_APP_CLIENT_SECRET", "")
    token_key = os.environ.get("GITHUB_TOKEN_ENCRYPTION_KEY", "")
    client_id = str(github.get("client_id") or "")
    public_base = str(github.get("public_base_url") or "").rstrip("/")
    if not all((client_id, client_secret, token_key, public_base)):
        raise ValidationError("GitHub OAuth client, secrets, and public_base_url are required")
    callback_path = str(github.get("oauth_callback_path") or "/api/oauth/github/callback")
    service = GitHubOAuthService(
        _ledger(args),
        client_id=client_id,
        client_secret=client_secret,
        token_key=token_key,
        api_url=str(github.get("api_url") or "https://api.github.com"),
        api_version=str(github.get("api_version") or "2026-03-10"),
        state_ttl_seconds=int(github.get("oauth_state_ttl_seconds") or 600),
    )
    return service, urljoin(public_base + "/", callback_path.lstrip("/"))


def _cmd_github_auth(args: argparse.Namespace) -> None:
    service, redirect_uri = _github_oauth(args)
    result = service.begin(
        owner_id=args.owner_id,
        slack_team_id=args.slack_team_id,
        slack_user_id=args.slack_user_id,
        agent_instance_id=args.agent_instance_id,
        agent_persona=args.agent_persona,
        agent_avatar_url=args.agent_avatar_url,
        slack_bot_user_id=args.slack_bot_user_id,
        redirect_uri=redirect_uri,
    )
    _emit(args, {"authorization_url": result["authorization_url"], "expires_in_seconds": 600})


def _cmd_github_install(args: argparse.Namespace) -> None:
    from forecasting.github import GitHubInstallationRegistry

    collaboration, repository = _configuration()
    github = collaboration.get("github") or {}
    registry = GitHubInstallationRegistry(
        _ledger(args),
        app_id=str(github.get("app_id") or ""),
        repository_slug=str(repository.get("slug") or ""),
    )
    result = registry.begin(
        app_slug=str(github.get("app_slug") or ""),
        ttl_seconds=int(github.get("installation_state_ttl_seconds") or 600),
    )
    result["next_action"] = (
        "Install the App for the exact workspace repository; the signed webhook "
        "must record the grant before the setup callback can complete."
    )
    _emit(args, result)


def _cmd_github_status(args: argparse.Namespace) -> None:
    ledger = _ledger(args)
    ChangeControl(ledger)
    with ledger._connect() as conn:
        rows = conn.execute(
            """SELECT b.id, b.owner_id, b.slack_team_id, b.slack_user_id,
                      b.agent_instance_id, b.agent_persona, b.github_user_id,
                      b.github_login, b.status, t.status AS token_status,
                      t.expires_at, t.refresh_expires_at
               FROM collaboration_identity_bindings b
               LEFT JOIN github_user_tokens t ON t.identity_binding_id = b.id
               ORDER BY b.created_at, b.id"""
        ).fetchall()
    collaboration, repository = _configuration()
    github = collaboration.get("github") or {}
    installations = []
    if github.get("app_id") and repository.get("slug"):
        from forecasting.github import GitHubInstallationRegistry

        installations = GitHubInstallationRegistry(
            ledger,
            app_id=str(github["app_id"]),
            repository_slug=str(repository["slug"]),
        ).status()
    _emit(
        args,
        {"identities": [dict(row) for row in rows], "installations": installations},
    )


def _cmd_github_revoke(args: argparse.Namespace) -> None:
    if not args.yes:
        raise ValidationError("revocation is destructive; rerun with --yes")
    ledger = _ledger(args)
    binding = ChangeControl(ledger).revoke_identity(args.binding_id)
    with ledger._connect() as conn:
        conn.execute(
            """UPDATE github_user_tokens SET status = 'revoked', revoked_at = datetime('now'),
                      updated_at = datetime('now') WHERE identity_binding_id = ?""",
            (args.binding_id,),
        )
    _emit(
        args,
        {"binding_id": binding["id"], "owner_id": binding["owner_id"], "status": "revoked"},
    )


def _changeset_packet(control: ChangeControl, changeset_id: str) -> dict[str, Any]:
    return {
        "changeset": control.get_changeset(changeset_id),
        "operations": [
            operation.as_dict() for operation in control.list_operations(changeset_id)
        ],
        "reviews": control.list_reviews(changeset_id),
        "quorum": vars(control.quorum(changeset_id)),
    }


def _cmd_changeset_list(args: argparse.Namespace) -> None:
    rows = ChangeControl(_ledger(args)).list_changesets(
        workspace_id=args.workspace_id,
        status=args.status,
        limit=args.limit,
    )
    _emit(args, {"changesets": rows})


def _cmd_changeset_show(args: argparse.Namespace) -> None:
    _emit(args, _changeset_packet(ChangeControl(_ledger(args)), args.changeset_id))


def _cmd_changeset_preview(args: argparse.Namespace) -> None:
    _emit(args, ChangeControl(_ledger(args)).preview(args.changeset_id))


def _confirm_changeset(args: argparse.Namespace, action: str) -> bool:
    if args.dry_run:
        _emit(args, {"action": action, "changeset_id": args.changeset_id, "dry_run": True})
        return False
    if not args.yes:
        raise ValidationError(f"{action} changes state; rerun with --yes")
    return True


def _cmd_changeset_apply(args: argparse.Namespace) -> None:
    if _confirm_changeset(args, "apply"):
        result = ChangeControl(_ledger(args)).apply(args.changeset_id)
        _emit(args, {"action": "applied", "result": result})


def _cmd_changeset_retry(args: argparse.Namespace) -> None:
    if not _confirm_changeset(args, "retry"):
        return
    from forecasting.github import MergeApplyReconciler

    _emit(args, MergeApplyReconciler(_ledger(args)).reconcile(args.changeset_id))


def _cmd_changeset_abandon(args: argparse.Namespace) -> None:
    if not _confirm_changeset(args, "abandon"):
        return
    result = ChangeControl(_ledger(args)).transition(args.changeset_id, "abandoned")
    _emit(args, {"action": "abandoned", "changeset": result})


def _cmd_review_policy(args: argparse.Namespace) -> None:
    collaboration, _ = _configuration()
    configured = dict(collaboration.get("review") or {})
    _emit(
        args,
        {
            "version": 1,
            "materiality_threshold": float(
                configured.get("materiality_threshold", 0.10)
            ),
            "risk_overrides": dict(configured.get("risk_overrides") or {}),
            "human_approvals": {"low": 0, "medium": 1, "high": 2},
            "high_risk_owner_or_steward_required": True,
            "contributing_owners_may_not_self_approve": True,
            "approval_binding": ["changeset_digest", "head_sha"],
        },
    )


def _review_status(control: ChangeControl, changeset_id: str) -> dict[str, Any]:
    changeset = control.get_changeset(changeset_id)
    quorum = control.quorum(changeset_id)
    reviews = control.list_reviews(changeset_id)
    return {
        "changeset_id": changeset_id,
        "status": changeset["status"],
        "risk_tier": changeset["risk_tier"],
        "changeset_digest": changeset["digest"],
        "head_sha": changeset.get("head_sha"),
        "pr_number": changeset.get("pr_number"),
        "github_merge_status": (
            "merged" if changeset.get("merge_sha") else "not_merged"
        ),
        "ledger_apply_status": changeset["status"],
        "quorum": vars(quorum),
        "reviews": reviews,
    }


def _cmd_review_status(args: argparse.Namespace) -> None:
    control = ChangeControl(_ledger(args))
    if args.changeset_id:
        rows = [_review_status(control, args.changeset_id)]
    else:
        pending = control.list_changesets(limit=max(1, min(int(args.limit), 1000)))
        rows = [
            _review_status(control, row["id"])
            for row in pending
            if row["status"] not in {
                "applied",
                "rejected",
                "cancelled",
                "abandoned",
                "superseded",
            }
        ]
    _emit(args, {"review_status": rows})


def _retention_rows(args: argparse.Namespace) -> list[dict[str, Any]]:
    clauses: list[str] = []
    values: list[Any] = []
    if args.changeset_id:
        clauses.append("b.changeset_id = ?")
        values.append(args.changeset_id)
    if args.state:
        clauses.append("a.state = ?")
        values.append(args.state)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    values.append(max(1, min(int(args.limit), 1000)))
    ledger = _ledger(args)
    ChangeControl(ledger)
    with ledger._connect() as conn:
        rows = conn.execute(
            f"""SELECT a.id, b.changeset_id, a.byte_size, a.retention_deadline,
                       a.key_version, a.state, a.pin_reason, a.pin_expires_at,
                       a.legal_hold, a.created_at, a.deleted_at
                FROM provenance_trace_archives a
                JOIN provenance_bundles b ON b.id = a.bundle_id
                {where}
                ORDER BY a.retention_deadline, a.id LIMIT ?""",
            values,
        ).fetchall()
    return [{**dict(row), "legal_hold": bool(row["legal_hold"])} for row in rows]


def _cmd_transcript_retention(args: argparse.Namespace) -> None:
    rows = _retention_rows(args)
    payload: dict[str, Any] = {"archives": rows, "swept_archive_ids": []}
    if args.sweep:
        if args.dry_run:
            from forecasting.models import utc_now_iso

            now = utc_now_iso()
            payload["would_sweep_archive_ids"] = [
                row["id"]
                for row in rows
                if row["state"] == "active"
                and row["retention_deadline"] <= now
                and not row["legal_hold"]
                and (not row["pin_expires_at"] or row["pin_expires_at"] <= now)
            ]
        else:
            if not args.yes:
                raise ValidationError("retention sweep deletes ciphertext; rerun with --yes")
            from forecasting.change_control.trace_archive import sweep_expired_traces

            payload["swept_archive_ids"] = sweep_expired_traces(_ledger(args))
    _emit(args, payload)


def _cmd_transcript_access_audit(args: argparse.Namespace) -> None:
    from forecasting.change_control.models import content_digest

    clauses: list[str] = []
    values: list[Any] = []
    for column, value in (
        ("b.changeset_id", args.changeset_id),
        ("e.archive_id", args.archive_id),
        ("e.actor_id", args.actor_id),
    ):
        if value:
            clauses.append(f"{column} = ?")
            values.append(value)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    values.append(max(1, min(int(args.limit), 1000)))
    ledger = _ledger(args)
    ChangeControl(ledger)
    with ledger._connect() as conn:
        rows = conn.execute(
            f"""SELECT e.id, e.archive_id, b.changeset_id, e.actor_id,
                       e.action, e.reason, e.occurred_at
                FROM provenance_access_events e
                JOIN provenance_trace_archives a ON a.id = e.archive_id
                JOIN provenance_bundles b ON b.id = a.bundle_id
                {where}
                ORDER BY e.occurred_at DESC, e.id DESC LIMIT ?""",
            values,
        ).fetchall()
    events = [
        {
            "id": row["id"],
            "archive_id": row["archive_id"],
            "changeset_id": row["changeset_id"],
            "actor_id": row["actor_id"],
            "action": row["action"],
            "reason_digest": content_digest(row["reason"]),
            "occurred_at": row["occurred_at"],
        }
        for row in rows
    ]
    _emit(args, {"access_events": events})


__all__ = ["register_cli"]

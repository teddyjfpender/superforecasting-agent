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
    try:
        repository, workspace_id, branch = _linked()
    except ValidationError:
        return {"linked": False, "github_merge_status": "unlinked", "ledger_apply_status": "local"}
    checkout = managed_checkout_path(workspace_id)
    payload: dict[str, Any] = {
        "linked": True,
        "repository": repository,
        "workspace_id": workspace_id,
        "default_branch": branch,
        "path": str(checkout),
        "github_merge_status": "unknown",
        "ledger_apply_status": "authoritative-local",
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


__all__ = ["register_cli"]

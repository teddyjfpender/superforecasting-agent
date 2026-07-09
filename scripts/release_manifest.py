#!/usr/bin/env python3
"""Machine-readable release manifest for the formal artifact set.

Every formal release (tag ``vX.Y.Z``) ships a ``release-manifest.json`` that
names every artifact, pins its SHA256, records the multi-arch image digest, and
declares the oldest on-disk ledger schema this build can open + forward-migrate
(``min_migration_version`` — the machine-readable half of the P1.4 PRAGMA
``user_version`` downgrade guard).

The manifest is the contract the one-line installer and the Hetzner bootstrap
resolve against, so a box always knows *exactly* which wheel + image digest a
tag corresponds to instead of trusting a floating ``:latest``.

``SCHEMA`` here is the single source of truth; ``scripts/release-manifest.schema.json``
is generated from it (``python -m scripts.release_manifest --emit-schema``) and a
test asserts the two stay in lockstep.

CLI:
    python -m scripts.release_manifest --emit-schema [PATH]
    python -m scripts.release_manifest build \
        --version 0.18.0 --tag v0.18.0 \
        --min-migration 0.17.0 \
        --artifact wheel=dist/foo.whl --artifact sdist=dist/foo.tar.gz \
        --artifact installer=dist/install.sh --artifact checksums=dist/SHA256SUMS \
        --image-registry ghcr.io --image-repo teddyjfpender/superforecasting-agent \
        --image-tag v0.18.0 --image-tag latest \
        --image-digest sha256:... \
        [--out dist/release-manifest.json]
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA_VERSION = "1"
PRODUCT = "superforecasting-agent"

_SEMVER_RE = r"^[0-9]+\.[0-9]+\.[0-9]+$"
_TAG_RE = r"^v[0-9]+\.[0-9]+\.[0-9]+$"
_SHA256_RE = r"^[0-9a-f]{64}$"
_DIGEST_RE = r"^sha256:[0-9a-f]{64}$"

# The roles every formal release MUST carry. Extra roles are permitted.
REQUIRED_ARTIFACT_ROLES = ("wheel", "sdist", "installer", "checksums")

# JSON Schema (draft 2020-12). Single source of truth for the manifest shape.
SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://github.com/teddyjfpender/superforecasting-agent/"
    "release-manifest.schema.json",
    "title": "Superforecasting Agent release manifest",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "product",
        "version",
        "tag",
        "released",
        "min_migration_version",
        "git",
        "artifacts",
        "image",
    ],
    "properties": {
        "schema_version": {"const": MANIFEST_SCHEMA_VERSION},
        "product": {"const": PRODUCT},
        "version": {"type": "string", "pattern": _SEMVER_RE},
        "tag": {"type": "string", "pattern": _TAG_RE},
        "released": {"type": "string", "format": "date-time"},
        # Oldest prior release whose ledger this build opens + forward-migrates.
        "min_migration_version": {"type": "string", "pattern": _SEMVER_RE},
        "git": {
            "type": "object",
            "additionalProperties": False,
            "required": ["commit"],
            "properties": {
                "commit": {"type": "string", "pattern": "^[0-9a-f]{7,40}$"},
                "branch": {"type": ["string", "null"]},
            },
        },
        "artifacts": {
            "type": "object",
            "minProperties": len(REQUIRED_ARTIFACT_ROLES),
            "required": list(REQUIRED_ARTIFACT_ROLES),
            "additionalProperties": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "sha256", "size_bytes"],
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "sha256": {"type": "string", "pattern": _SHA256_RE},
                    "size_bytes": {"type": "integer", "minimum": 0},
                },
            },
        },
        "image": {
            "type": "object",
            "additionalProperties": False,
            "required": ["registry", "repository", "tags", "platforms", "digest"],
            "properties": {
                "registry": {"type": "string", "minLength": 1},
                "repository": {"type": "string", "minLength": 1},
                "tags": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string", "minLength": 1},
                },
                "platforms": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string", "minLength": 1},
                },
                # null in a dry-run (nothing was pushed); a manifest-list digest
                # once the multi-arch image lands in the registry.
                "digest": {
                    "type": ["string", "null"],
                    "pattern": _DIGEST_RE,
                },
            },
        },
    },
}


def sha256_file(path: str | Path) -> str:
    """Return the lowercase hex SHA256 of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return out.stdout.strip() or None
    except (subprocess.SubprocessError, OSError):
        return None


def artifact_entry(path: str | Path) -> dict[str, Any]:
    """Build a {name, sha256, size_bytes} entry from a local file."""
    p = Path(path)
    return {
        "name": p.name,
        "sha256": sha256_file(p),
        "size_bytes": p.stat().st_size,
    }


def build_manifest(
    *,
    version: str,
    tag: str,
    min_migration_version: str,
    artifacts: dict[str, str | Path],
    image_registry: str,
    image_repository: str,
    image_tags: list[str],
    image_platforms: list[str],
    image_digest: str | None = None,
    git_commit: str | None = None,
    git_branch: str | None = None,
    released: str | None = None,
) -> dict[str, Any]:
    """Assemble a release manifest dict from artifact paths + image metadata.

    ``artifacts`` maps role -> path; each path is hashed here. ``image_digest``
    is ``None`` for a dry-run (nothing pushed).
    """
    if released is None:
        released = (
            _dt.datetime.now(_dt.timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
    commit = git_commit if git_commit is not None else _git("rev-parse", "HEAD")
    branch = (
        git_branch
        if git_branch is not None
        else _git("rev-parse", "--abbrev-ref", "HEAD")
    )
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "product": PRODUCT,
        "version": version,
        "tag": tag,
        "released": released,
        "min_migration_version": min_migration_version,
        "git": {"commit": commit or "0000000", "branch": branch},
        "artifacts": {
            role: artifact_entry(path) for role, path in artifacts.items()
        },
        "image": {
            "registry": image_registry,
            "repository": image_repository,
            "tags": list(image_tags),
            "platforms": list(image_platforms),
            "digest": image_digest,
        },
    }


class ManifestValidationError(ValueError):
    """Raised when a manifest does not satisfy the schema."""


def validate_manifest(manifest: dict[str, Any]) -> None:
    """Validate a manifest against ``SCHEMA``.

    Uses ``jsonschema`` when available (the test venv has it); otherwise falls
    back to a minimal structural check so the manifest can still be validated in
    a bare release environment.
    """
    try:
        import jsonschema  # type: ignore
    except ImportError:
        _validate_minimal(manifest)
        return

    validator_cls = getattr(
        jsonschema.validators, "Draft202012Validator", jsonschema.Draft7Validator
    )
    errors = sorted(
        validator_cls(SCHEMA).iter_errors(manifest),
        key=lambda e: list(e.path),
    )
    if errors:
        joined = "; ".join(
            f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}"
            for e in errors
        )
        raise ManifestValidationError(joined)


def _validate_minimal(manifest: dict[str, Any]) -> None:
    """jsonschema-free fallback: the load-bearing invariants only."""
    for key in SCHEMA["required"]:
        if key not in manifest:
            raise ManifestValidationError(f"missing required key: {key}")
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ManifestValidationError("schema_version mismatch")
    if manifest.get("product") != PRODUCT:
        raise ManifestValidationError("product mismatch")
    if not re.match(_SEMVER_RE, str(manifest.get("version", ""))):
        raise ManifestValidationError("version is not semver")
    if not re.match(_TAG_RE, str(manifest.get("tag", ""))):
        raise ManifestValidationError("tag is not vX.Y.Z")
    if not re.match(_SEMVER_RE, str(manifest.get("min_migration_version", ""))):
        raise ManifestValidationError("min_migration_version is not semver")
    arts = manifest.get("artifacts")
    if not isinstance(arts, dict):
        raise ManifestValidationError("artifacts must be an object")
    for role in REQUIRED_ARTIFACT_ROLES:
        if role not in arts:
            raise ManifestValidationError(f"missing required artifact: {role}")
        entry = arts[role]
        if not re.match(_SHA256_RE, str(entry.get("sha256", ""))):
            raise ManifestValidationError(f"{role}: sha256 is not 64 hex chars")
    image = manifest.get("image")
    if not isinstance(image, dict):
        raise ManifestValidationError("image must be an object")
    digest = image.get("digest")
    if digest is not None and not re.match(_DIGEST_RE, str(digest)):
        raise ManifestValidationError("image.digest is not sha256:<64hex> or null")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _emit_schema(path: Path) -> None:
    path.write_text(json.dumps(SCHEMA, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _cmd_build(args: argparse.Namespace) -> int:
    artifacts: dict[str, str] = {}
    for spec in args.artifact or []:
        if "=" not in spec:
            print(f"error: --artifact expects role=path, got {spec!r}", file=sys.stderr)
            return 2
        role, path = spec.split("=", 1)
        artifacts[role] = path

    digest = args.image_digest
    if digest in ("", "null", "none", "None"):
        digest = None

    manifest = build_manifest(
        version=args.version,
        tag=args.tag,
        min_migration_version=args.min_migration,
        artifacts=artifacts,
        image_registry=args.image_registry,
        image_repository=args.image_repo,
        image_tags=args.image_tag or [],
        image_platforms=args.image_platform or ["linux/amd64", "linux/arm64"],
        image_digest=digest,
        released=args.released,
    )
    try:
        validate_manifest(manifest)
    except ManifestValidationError as exc:
        print(f"error: manifest failed validation: {exc}", file=sys.stderr)
        return 1

    text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--emit-schema",
        nargs="?",
        const="scripts/release-manifest.schema.json",
        metavar="PATH",
        help="write the JSON Schema to PATH and exit",
    )
    sub = parser.add_subparsers(dest="command")

    b = sub.add_parser("build", help="build + validate a manifest")
    b.add_argument("--version", required=True)
    b.add_argument("--tag", required=True)
    b.add_argument("--min-migration", required=True)
    b.add_argument("--artifact", action="append", help="role=path (repeatable)")
    b.add_argument("--image-registry", default="ghcr.io")
    b.add_argument("--image-repo", default="teddyjfpender/superforecasting-agent")
    b.add_argument("--image-tag", action="append", help="image tag (repeatable)")
    b.add_argument("--image-platform", action="append", help="platform (repeatable)")
    b.add_argument("--image-digest", default=None)
    b.add_argument("--released", default=None, help="ISO-8601; default: now (UTC)")
    b.add_argument("--out", default=None, help="write to PATH instead of stdout")
    b.set_defaults(func=_cmd_build)

    args = parser.parse_args(argv)

    if args.emit_schema:
        _emit_schema(Path(args.emit_schema))
        print(f"wrote {args.emit_schema}")
        return 0

    if not getattr(args, "command", None):
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

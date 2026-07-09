"""Tests for the machine-readable release manifest (scripts/release_manifest.py).

The manifest is the installer's contract: it names every artifact, pins its
SHA256, records the multi-arch image digest, and declares min_migration_version.
A malformed manifest that still validated would let a release ship with, e.g., a
truncated hash or a missing wheel — so the schema is the load-bearing guard.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import release_manifest as rm

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_FILE = REPO_ROOT / "scripts" / "release-manifest.schema.json"


@pytest.fixture()
def artifacts(tmp_path: Path) -> dict[str, Path]:
    files = {}
    for role, content in {
        "wheel": b"wheel-bytes",
        "sdist": b"sdist-bytes",
        "installer": b"#!/bin/sh\n",
        "checksums": b"deadbeef  x\n",
    }.items():
        p = tmp_path / f"{role}.bin"
        p.write_bytes(content)
        files[role] = p
    return files


def _valid_manifest(artifacts: dict[str, Path], **overrides) -> dict:
    m = rm.build_manifest(
        version="0.18.0",
        tag="v0.18.0",
        min_migration_version="0.17.0",
        artifacts=artifacts,
        image_registry="ghcr.io",
        image_repository="teddyjfpender/superforecasting-agent",
        image_tags=["v0.18.0", "latest"],
        image_platforms=["linux/amd64", "linux/arm64"],
        image_digest=None,
        git_commit="1234567",
        git_branch="main",
    )
    m.update(overrides)
    return m


def test_schema_file_is_in_sync_with_module():
    """scripts/release-manifest.schema.json is generated from SCHEMA."""
    assert SCHEMA_FILE.exists(), "schema file missing — run --emit-schema"
    on_disk = json.loads(SCHEMA_FILE.read_text())
    from_module = json.loads(json.dumps(rm.SCHEMA, sort_keys=True))
    assert on_disk == from_module, (
        "schema drift: run `python -m scripts.release_manifest --emit-schema`"
    )


def test_build_manifest_is_valid_and_hashes_files(artifacts):
    m = _valid_manifest(artifacts)
    rm.validate_manifest(m)  # must not raise
    # Each artifact carries a real 64-hex sha and byte size.
    for role, path in artifacts.items():
        entry = m["artifacts"][role]
        assert entry["sha256"] == rm.sha256_file(path)
        assert entry["size_bytes"] == path.stat().st_size
        assert len(entry["sha256"]) == 64
    assert m["schema_version"] == rm.MANIFEST_SCHEMA_VERSION
    assert m["product"] == rm.PRODUCT
    assert m["image"]["digest"] is None  # dry-run


def test_real_digest_validates(artifacts):
    digest = "sha256:" + "a" * 64
    m = _valid_manifest(artifacts, image=None)
    m["image"] = {
        "registry": "ghcr.io",
        "repository": "teddyjfpender/superforecasting-agent",
        "tags": ["v0.18.0", "latest"],
        "platforms": ["linux/amd64", "linux/arm64"],
        "digest": digest,
    }
    rm.validate_manifest(m)


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda m: m.pop("version"), id="missing-version"),
        pytest.param(
            lambda m: m.__setitem__("version", "0.18"), id="bad-semver"
        ),
        pytest.param(
            lambda m: m.__setitem__("tag", "0.18.0"), id="tag-missing-v"
        ),
        pytest.param(
            lambda m: m["artifacts"].pop("wheel"), id="missing-wheel"
        ),
        pytest.param(
            lambda m: m["artifacts"]["wheel"].__setitem__("sha256", "xyz"),
            id="short-sha",
        ),
        pytest.param(
            lambda m: m["image"].__setitem__("digest", "notadigest"),
            id="bad-digest",
        ),
        pytest.param(
            lambda m: m.__setitem__("schema_version", "9"),
            id="wrong-schema-version",
        ),
        pytest.param(
            lambda m: m.__setitem__(
                "min_migration_version", "latest"
            ),
            id="bad-min-migration",
        ),
    ],
)
def test_validation_rejects_malformed(artifacts, mutate):
    m = _valid_manifest(artifacts)
    mutate(m)
    with pytest.raises(rm.ManifestValidationError):
        rm.validate_manifest(m)


def test_minimal_fallback_matches_jsonschema(artifacts, monkeypatch):
    """The jsonschema-free fallback must reject the same core violations."""
    m = _valid_manifest(artifacts)
    m["artifacts"]["wheel"]["sha256"] = "tooshort"
    with pytest.raises(rm.ManifestValidationError):
        rm._validate_minimal(m)
    # A good manifest passes the fallback.
    rm._validate_minimal(_valid_manifest(artifacts))


def test_all_required_roles_enforced(artifacts):
    for role in rm.REQUIRED_ARTIFACT_ROLES:
        m = _valid_manifest(artifacts)
        del m["artifacts"][role]
        with pytest.raises(rm.ManifestValidationError):
            rm.validate_manifest(m)

"""Tests for scripts/check-release-ready.sh and scripts/release.sh (dry-run).

The gate is the shared red/green decision for "cut a release or not", used by
production-release.yml and a pre-tag hook. release.sh is its offline dry-run
twin. These tests pin the red/green cases so a broken gate can't silently green.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE = REPO_ROOT / "scripts" / "check-release-ready.sh"
RELEASE = REPO_ROOT / "scripts" / "release.sh"
WINDOWS_INSTALLER = REPO_ROOT / "scripts" / "install-release.ps1"


def test_github_actions_are_pinned_to_commits():
    unpinned = []
    for workflow in sorted((REPO_ROOT / ".github" / "workflows").glob("*.y*ml")):
        for lineno, line in enumerate(workflow.read_text().splitlines(), 1):
            match = re.match(r"\s*-?\s*uses:\s*([^\s#]+)", line)
            if not match or match.group(1).startswith("./"):
                continue
            ref = match.group(1).rpartition("@")[2]
            if not re.fullmatch(r"[0-9a-f]{40}", ref):
                unpinned.append(f"{workflow.name}:{lineno}: {match.group(1)}")
    assert not unpinned, "unpinned GitHub Actions:\n" + "\n".join(unpinned)


def test_formal_workflow_is_the_only_release_publisher():
    assert not (REPO_ROOT / ".github" / "workflows" / "release.yml").exists()
    production = (REPO_ROOT / ".github" / "workflows" / "production-release.yml").read_text()
    local = RELEASE.read_text()
    legacy = (REPO_ROOT / "scripts" / "release.py").read_text()

    assert "python -m pytest tests/e2e/" in production
    assert "uses: ./.github/actions/hermes-smoke-test" in production
    assert '--verify-tag --draft' in production
    assert 'gh release edit "$TAG" --draft=false --latest' in production
    assert "Move latest after the formal release verifies" in production
    assert "Mirror verified image digest to Docker Hub" in production
    assert '"$IMAGE@$IMAGE_DIGEST"' in production
    assert "it does not rely on a GITHUB_TOKEN-created release event" in production
    assert "org.opencontainers.image.revision=${{ env.REVISION }}" in production
    assert "--json isDraft" in production
    assert "github.event.repository.default_branch" in production
    assert 'git merge-base --is-ancestor HEAD "origin/${DEFAULT_BRANCH}"' in production
    assert "already published and immutable" in production
    assert "diff -u /tmp/expected-release-assets /tmp/release-assets" in production
    assert 'cmp "dist/$asset" "$VERIFY_DIR/$asset"' in production
    assert "sigstore/gh-action-sigstore-python" in production
    assert production.index("Create draft GitHub Release") < production.index(
        "Verify immutable release assets and image"
    ) < production.index("Move latest after the formal release verifies") < production.index(
        "Mirror verified image digest to Docker Hub"
    ) < production.index(
        "Publish verified GitHub Release"
    )
    assert production.index("Refuse mutation of a published release") < production.index(
        "Build + push multi-arch image"
    )
    assert "python-version: ['3.12', '3.13']" in production
    assert "windows-release-installer" in production
    assert "needs: [gate, test, python-compat, windows-release-installer, tui]" in production
    image_push = production.split("Build + push multi-arch image", 1)[1].split(
        "# ---- assemble", 1
    )[0]
    assert "${{ env.IMAGE }}:latest" not in image_push
    assert "--publish" not in local
    assert "git push" not in local
    assert "gh release" not in local
    assert 'parser.add_argument("--publish"' not in legacy
    assert 'git_result("push", "origin"' not in legacy
    for workflow in (REPO_ROOT / ".github" / "workflows").glob("*.y*ml"):
        if workflow.name != "production-release.yml":
            contents = workflow.read_text()
            assert "gh release create" not in contents
            assert "gh release edit" not in contents
            assert "gh release upload" not in contents


def test_windows_release_installer_verifies_before_installing():
    source = WINDOWS_INSTALLER.read_text(encoding="utf-8")

    assert "Get-FileHash -Algorithm SHA256" in source
    assert 'release-manifest.json' in source
    assert "Python 3.11-3.13 is required" in source
    assert 'Set-Content -LiteralPath (Join-Path $agentHome ".install_method")' in source
    assert source.index("Get-FileHash -Algorithm SHA256") < source.index(
        "-m pipx install --force"
    )
    assert "[switch]$VerifyOnly" in source


def test_main_ci_filters_also_cover_the_fork_default_branch():
    missing = []
    for workflow in sorted((REPO_ROOT / ".github" / "workflows").glob("*.y*ml")):
        for lineno, line in enumerate(workflow.read_text().splitlines(), 1):
            if "branches:" in line and "main" in line and "superforecasting-agent-snapshot" not in line:
                missing.append(f"{workflow.name}:{lineno}: {line.strip()}")
    assert not missing, "CI branch filters miss the production branch:\n" + "\n".join(missing)


def test_required_ledger_exports_module_is_tracked():
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "--error-unmatch",
            "forecasting/ledger/exports.py",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "forecasting/ledger/exports.py is required by the ledger facade but is "
        "missing from Git (check the broad export* ignore rule)"
    )


def _run(cmd, **env):
    e = dict(os.environ)
    e.update(env)
    return subprocess.run(
        cmd, cwd=REPO_ROOT, env=e, capture_output=True, text=True, timeout=600
    )


def _pyproject_version() -> str:
    for line in (REPO_ROOT / "pyproject.toml").read_text().splitlines():
        if line.startswith("version = "):
            return line.split('"')[1]
    raise AssertionError("no version in pyproject.toml")


def test_gate_green_for_current_version(tmp_path):
    # Deterministic PRE-TAG mode regardless of environment: run in a clone
    # with the version tag removed (the real repo may legitimately carry it
    # mid-release) and GITHUB_REF cleared (ambient on CI tag runs, where it
    # would flip the gate into tag-run mode).
    clone = _clone_repo(tmp_path / "clone")
    ver = _pyproject_version()
    subprocess.run(
        ["git", "-C", str(clone), "tag", "-d", f"v{ver}"],
        check=False, capture_output=True,
    )
    gate = clone / "scripts" / "check-release-ready.sh"
    r = _run_in(clone, ["bash", str(gate), "--version", ver], GITHUB_REF=None)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "CHECKS PASSED" in r.stdout
    assert "version consistent" in r.stdout


def test_gate_red_on_version_mismatch():
    r = _run(["bash", str(GATE), "--version", "0.0.99"])
    assert r.returncode == 1
    assert "NOT READY" in r.stdout
    assert "!= pyproject" in r.stdout


def test_gate_red_when_changelog_entry_missing():
    # 3.2.1 is valid semver with no changelog section -> red on the changelog
    # check (and consequently on the version-mismatch check too).
    r = _run(["bash", str(GATE), "--version", "3.2.1"])
    assert r.returncode == 1
    assert "changelog has no non-empty" in r.stdout


def test_gate_red_when_tag_already_exists(monkeypatch):
    # PRE-TAG mode assertion: an already-existing tag is a red ("bump first").
    # On CI the tag push sets GITHUB_REF=refs/tags/vX.Y.Z, which flips the gate
    # into TAG-RUN mode (an existing tag is expected, not a conflict) and this
    # would go green. Clear it so the gate exercises the local pre-tag path the
    # assertion is about; test_gate_tag_run_* below pin the tag-run behaviour.
    monkeypatch.delenv("GITHUB_REF", raising=False)
    ver = _pyproject_version()
    tag = f"v{ver}"
    existing = subprocess.run(
        ["git", "tag", "-l", tag], cwd=REPO_ROOT, capture_output=True, text=True
    ).stdout.strip()
    if not existing:
        pytest.skip(f"{tag} is not an existing tag in this checkout")
    r = _run(["bash", str(GATE), "--version", ver])
    assert r.returncode == 1
    assert "already exists" in r.stdout


def _clone_repo(dest: Path) -> Path:
    """Local clone of the repo (full history + tags) for tag-position tests.

    Isolated in tmp — we move a tag here to exercise the gate's tag-run modes
    without ever touching (or pushing) a tag in the real repo.
    """
    if shutil.which("git") is None:
        pytest.skip("git is required for tag-run gate tests")
    r = subprocess.run(
        ["git", "clone", "--local", "--quiet", str(REPO_ROOT), str(dest)],
        capture_output=True, text=True, timeout=120,
    )
    if r.returncode != 0:
        pytest.skip(f"git clone --local unavailable: {r.stderr.strip()}")
    # Local clones include committed objects only. Copy the gate under test so
    # these tests exercise the current worktree implementation before commit.
    shutil.copy2(GATE, dest / "scripts" / GATE.name)
    return dest


def test_strict_gate_rejects_a_dirty_release_candidate(tmp_path):
    clone = _clone_repo(tmp_path / "clone")
    ver = _pyproject_version()
    subprocess.run(
        ["git", "-C", str(clone), "tag", "-d", f"v{ver}"],
        check=False,
        capture_output=True,
    )
    (clone / "uncommitted-release-file.txt").write_text("not in the candidate\n")
    gate = clone / "scripts" / "check-release-ready.sh"

    r = _run_in(
        clone,
        ["bash", str(gate), "--strict", "--version", ver],
        GITHUB_REF=None,
        PYTHON=sys.executable,
    )

    assert r.returncode == 1
    assert "worktree dirty" in r.stdout
    assert "NOT READY" in r.stdout


def _run_in(repo: Path, cmd, **env):
    e = dict(os.environ)
    # None means "ensure absent" (e.g. GITHUB_REF leaks in ambient CI env).
    for k, v in env.items():
        if v is None:
            e.pop(k, None)
        else:
            e[k] = v
    return subprocess.run(
        cmd, cwd=repo, env=e, capture_output=True, text=True, timeout=600
    )


def test_gate_tag_run_ready_when_tag_points_at_head(tmp_path):
    # TAG-RUN mode (CI on a tag push): the tag exists by definition; the real
    # invariant is that it points at HEAD → READY.
    clone = _clone_repo(tmp_path / "clone")
    ver = _pyproject_version()
    tag = f"v{ver}"
    subprocess.run(
        ["git", "-C", str(clone), "tag", "-f", tag, "HEAD"],
        check=True, capture_output=True,
    )
    gate = clone / "scripts" / "check-release-ready.sh"
    r = _run_in(clone, ["bash", str(gate), "--version", ver],
                GITHUB_REF=f"refs/tags/{tag}")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "tag-run" in r.stdout and "points at HEAD" in r.stdout
    assert "CHECKS PASSED" in r.stdout


def test_gate_tag_run_not_ready_when_tag_points_elsewhere(tmp_path):
    # TAG-RUN mode but the tag was cut at a different commit than HEAD → red.
    clone = _clone_repo(tmp_path / "clone")
    ver = _pyproject_version()
    tag = f"v{ver}"
    # Tag a fresh commit we mint ourselves, then move HEAD past it — never
    # HEAD~1, which does not exist under CI's shallow (depth-1) checkout.
    subprocess.run(
        ["git", "-C", str(clone), "tag", "-f", tag, "HEAD"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(clone), "commit", "--allow-empty", "-m", "advance"],
        check=True, capture_output=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"},
    )
    gate = clone / "scripts" / "check-release-ready.sh"
    r = _run_in(clone, ["bash", str(gate), "--version", ver],
                GITHUB_REF=f"refs/tags/{tag}")
    assert r.returncode == 1
    assert "does not point at HEAD" in r.stdout
    assert "NOT READY" in r.stdout


def test_strict_gate_reports_stale_generated_doc_paths(tmp_path):
    clone = _clone_repo(tmp_path / "clone")
    ver = _pyproject_version()
    subprocess.run(
        ["git", "-C", str(clone), "tag", "-d", f"v{ver}"],
        check=False, capture_output=True,
    )
    gate = clone / "scripts" / "check-release-ready.sh"
    shutil.copy2(GATE, gate)
    fake_python = tmp_path / "python"
    fake_python.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-c" ]; then exit 0; fi\n'
        'echo "  docs/reference/README.md" >&2\n'
        "exit 1\n"
    )
    fake_python.chmod(0o755)

    r = _run_in(
        clone,
        ["bash", str(gate), "--strict", "--version", ver],
        GITHUB_REF=None,
        PYTHON=str(fake_python),
    )

    assert r.returncode == 1
    assert "docs/reference/README.md" in r.stderr


@pytest.mark.skipif(
    shutil.which("uv") is None or not (REPO_ROOT / "ui-tui" / "dist" / "entry.js").exists(),
    reason="dry-run needs uv + a prebuilt TUI bundle (ui-tui/dist/entry.js)",
)
def test_release_dry_run_produces_full_artifact_set(tmp_path):
    out = tmp_path / "rel"
    py = str(REPO_ROOT / ".venv" / "bin" / "python")
    if not Path(py).exists():
        py = shutil.which("python3") or "python3"
    # The gate has its own dedicated tests (both modes, above). This test's
    # subject is the ARTIFACT SET, and the repo may legitimately carry the
    # version tag mid-release — so use the sanctioned tests/CI gate skip.
    r = _run(["bash", str(RELEASE), "--out", str(out)], PYTHON=py, SKIP_GATE="1")
    assert r.returncode == 0, r.stdout + r.stderr
    ver = _pyproject_version()
    expected = [
        f"superforecasting_agent-{ver}-py3-none-any.whl",
        f"superforecasting_agent-{ver}.tar.gz",
        "install.sh",
        "install.ps1",
        "SHA256SUMS",
        "release-manifest.json",
        "RELEASE_NOTES.md",
    ]
    for name in expected:
        assert (out / name).exists(), f"missing {name}\n{r.stdout}"

    # The emitted manifest must validate against the schema and be dry-run
    # (digest null, image aimed at ghcr.io).
    import json

    from scripts import release_manifest as rm

    manifest = json.loads((out / "release-manifest.json").read_text())
    rm.validate_manifest(manifest)
    assert manifest["version"] == ver
    assert manifest["tag"] == f"v{ver}"
    assert manifest["image"]["registry"] == "ghcr.io"
    assert manifest["image"]["digest"] is None
    assert set(manifest["artifacts"]) >= set(rm.REQUIRED_ARTIFACT_ROLES)
    assert manifest["artifacts"]["windows_installer"]["name"] == "install.ps1"

    # SHA256SUMS entries must match the manifest hashes.
    sums = {}
    for line in (out / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split()
        sums[name] = digest
    assert sums[manifest["artifacts"]["wheel"]["name"]] == (
        manifest["artifacts"]["wheel"]["sha256"]
    )


def test_release_script_rejects_publish_mode():
    result = _run(["bash", str(RELEASE), "--publish"])
    assert result.returncode == 2
    assert "unknown arg: --publish" in result.stderr

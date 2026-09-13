"""Reject newly introduced legacy product names outside reviewed boundaries."""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = "scripts/legacy-naming-policy.json"
TOKEN = re.compile(r"[a-zA-Z0-9_.-]*hermes[a-zA-Z0-9_.-]*", re.IGNORECASE)


def git(*args: str, root: Path = ROOT) -> bytes:
    return subprocess.check_output(["git", *args], cwd=root, input=b"")


def contents(ref: str, path: str, root: Path) -> str:
    if ref == "WORKTREE":
        file = root / path
        data = file.read_bytes() if file.is_file() else b""
    else:
        result = subprocess.run(
            ["git", "show", f"{ref}:{path}"], cwd=root, capture_output=True
        )
        data = result.stdout if result.returncode == 0 else b""
    if b"\0" in data:
        return ""
    return data.decode("utf-8", errors="replace")


def violations(base: str, head: str, *, root: Path = ROOT) -> list[str]:
    policy = json.loads((root / POLICY).read_text(encoding="utf-8"))
    anchor = policy.get("baseline")
    policy = policy["exceptions"]
    if anchor:
        # Existing, reviewed compatibility names predate this gate. For a new
        # remote or a PR against older history, measure growth from that audit.
        git("cat-file", "-e", anchor + "^{commit}", root=root)
        descendant = subprocess.run(
            ["git", "merge-base", "--is-ancestor", anchor, base],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if descendant.returncode:
            base = anchor
    for rule in policy:
        if not rule.get("reason") or rule.get("category") not in {
            "compatibility",
            "stored-identity",
            "upstream",
            "guard-fixture",
        }:
            raise ValueError("Naming exceptions require a category and reason")
    refs = [base] if head == "WORKTREE" else [base, head]
    paths = git(
        "diff",
        "--name-only",
        "--no-renames",
        "--diff-filter=ACM",
        "-z",
        *refs,
        root=root,
    )
    failures = []
    for raw in paths.split(b"\0"):
        if not raw:
            continue
        path = raw.decode("utf-8")
        before = contents(base, path, root)
        after = contents(head, path, root)
        # Multisets allow unchanged compatibility references to move within a
        # file, but adding another reference or a legacy filename needs review.
        old = Counter(TOKEN.findall(before))
        new = Counter(TOKEN.findall(after))
        existed = (
            subprocess.run(
                ["git", "cat-file", "-e", f"{base}:{path}"],
                cwd=root,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ).returncode
            == 0
        )
        if not existed:
            new.update(TOKEN.findall(path))
        for token, count in (new - old).items():
            allowed = any(
                any(fnmatch.fnmatchcase(path, pattern) for pattern in rule["paths"])
                and re.fullmatch(rule["token"], token)
                for rule in policy
            )
            if not allowed:
                failures.append(
                    f"{path}: new legacy name {token!r} ({count} occurrence(s))"
                )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base")
    parser.add_argument("--head", default="WORKTREE")
    args = parser.parse_args()
    base = args.base
    if base is None:
        # Local staged edits compare against HEAD. A clean CI checkout compares
        # against its parent (the PR merge commit's first parent is its base).
        base = "HEAD" if git("diff", "HEAD", "--name-only").strip() else "HEAD^"
        if subprocess.run(
            ["git", "rev-parse", "--verify", base],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode:
            base = git("hash-object", "-w", "-t", "tree", "--stdin").decode().strip()
    failures = violations(base, args.head)
    for failure in failures:
        print(failure)
    if failures:
        print(
            "Use canonical naming, or declare a narrow, reasoned exception in " + POLICY
        )
    return bool(failures)


if __name__ == "__main__":
    raise SystemExit(main())

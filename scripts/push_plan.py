"""Resolve every pushed ref against its own base without assuming a branch name."""

from __future__ import annotations

import argparse
import subprocess
import sys

ZERO = "0" * 40


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def default_base(remote: str, head: str) -> str:
    # Query the actual push destination: origin/HEAD can be stale or absent.
    advertised = git("ls-remote", "--symref", remote, "HEAD")
    for line in advertised.splitlines():
        value, ref = line.split("\t", 1)
        if ref == "HEAD" and not value.startswith("ref: "):
            present = subprocess.run(
                ["git", "cat-file", "-e", value + "^{commit}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if present.returncode == 0:
                result = subprocess.run(
                    ["git", "merge-base", value, head], capture_output=True, text=True
                )
                if result.returncode == 0:
                    return result.stdout.strip()
    # Empty remote, shallow clone or unrelated histories: inspect every file.
    # Never substitute head^, which could hide earlier frontend changes.
    return (
        subprocess
        .check_output(["git", "hash-object", "-w", "-t", "tree", "--stdin"], input=b"")
        .decode()
        .strip()
    )


def plan(remote: str, updates: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for line in updates.splitlines():
        if not line.strip():
            continue
        _, head, _, previous = line.split()
        if head == ZERO:
            continue
        git("rev-parse", "--verify", head + "^{commit}")
        base = default_base(remote, head) if previous == ZERO else previous
        # Remote tips not present locally also require conservative full coverage.
        if subprocess.run(
            ["git", "cat-file", "-e", base + "^{tree}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode:
            base = (
                subprocess
                .check_output(
                    ["git", "hash-object", "-w", "-t", "tree", "--stdin"], input=b""
                )
                .decode()
                .strip()
            )
        if (base, head) not in pairs:
            pairs.append((base, head))
    return pairs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("remote")
    args = parser.parse_args()
    for base, head in plan(args.remote, sys.stdin.read()):
        print(base, head, sep="\t")


if __name__ == "__main__":
    main()

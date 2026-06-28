"""Upstream / competitor watch — report new commits in tracked repos since the last mark.

Tracks, via the `gh` CLI (no clone needed):
  - NousResearch/hermes-agent   (our upstream — feature improvements to port)
  - superagent-ai/grok-cli       (TS coding agent — system design / agent features / TUI)
  - anomalyco/opencode           (flagship TS coding agent — system design / TUI)

State lives in docs/research/upstream-watch-state.json: {repo: {sha, branch}}. On each run it
reports new commits since the stored mark; `--update` advances the marks to current HEAD (do this
after you have triaged / audited the new activity). See docs/research/upstream-watch.md for the
running intelligence report this feeds.

Usage:  python scripts/upstream_watch.py [--state PATH] [--update] [--limit N]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess

REPOS = [
    "NousResearch/hermes-agent",
    "superagent-ai/grok-cli",
    "anomalyco/opencode",
]
STATE_DEFAULT = "docs/research/upstream-watch-state.json"


def _gh(*args: str) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout


def _latest(repo: str) -> tuple[str, str]:
    info = json.loads(_gh("api", f"repos/{repo}"))
    branch = info["default_branch"]
    head = json.loads(_gh("api", f"repos/{repo}/commits/{branch}"))["sha"]
    return branch, head


def _new_commits(repo: str, base: str, head: str) -> tuple[int, list[str]]:
    cmp = json.loads(_gh("api", f"repos/{repo}/compare/{base}...{head}"))
    msgs = [c["commit"]["message"].splitlines()[0] for c in cmp.get("commits", [])]
    return int(cmp.get("ahead_by", 0)), msgs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default=STATE_DEFAULT)
    ap.add_argument("--update", action="store_true", help="advance marks to current HEAD after triage")
    ap.add_argument("--limit", type=int, default=40, help="max commit subjects to print per repo")
    args = ap.parse_args()

    state: dict = {}
    if os.path.exists(args.state):
        with open(args.state, encoding="utf-8") as fh:
            state = json.load(fh)

    any_new = False
    recorded_baseline = False
    for repo in REPOS:
        try:
            branch, head = _latest(repo)
        except subprocess.CalledProcessError as exc:
            print(f"[error] {repo}: gh failed ({exc.stderr.strip()[:80]})")
            continue
        prev = (state.get(repo) or {}).get("sha")
        if not prev:
            print(f"[baseline] {repo}@{branch} {head[:12]} (no prior mark — recording)")
            state[repo] = {"sha": head, "branch": branch}
            recorded_baseline = True
            continue
        if prev == head:
            print(f"[no change] {repo}@{branch} {head[:12]}")
            continue
        ahead, msgs = _new_commits(repo, prev, head)
        any_new = True
        print(f"[+{ahead}] {repo}@{branch}  {prev[:8]}..{head[:8]} — new commits:")
        for m in msgs[: args.limit]:
            print(f"    - {m[:110]}")
        if ahead > args.limit:
            print(f"    … and {ahead - args.limit} more")
        if args.update:
            state[repo] = {"sha": head, "branch": branch}

    if args.update or recorded_baseline:
        with open(args.state, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, sort_keys=True)
        print(f"\nmarks written to {args.state}")
    elif any_new:
        print("\n(run with --update once you have triaged the above to advance the marks)")


if __name__ == "__main__":
    main()

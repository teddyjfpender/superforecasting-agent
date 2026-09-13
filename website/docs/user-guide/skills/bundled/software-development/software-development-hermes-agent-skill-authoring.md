---
title: "Superforecasting Agent Skill Authoring Skill — Author in-repo SKILL"
sidebar_label: "Superforecasting Agent Skill Authoring Skill"
description: "Author in-repo SKILL"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Superforecasting Agent Skill Authoring Skill

Author in-repo SKILL.md: frontmatter, validator, structure.

## Skill metadata

| | |
|---|---|
| Source | Bundled (installed by default) |
| Path | `skills/software-development/superforecasting-agent-skill-authoring` |
| Version | `1.1.0` |
| Author | Superforecasting Agent |
| License | MIT |
| Platforms | linux, macos, windows |
| Tags | `skills`, `authoring`, `superforecasting-agent`, `conventions`, `skill-md` |
| Related skills | [`writing-plans`](/user-guide/skills/bundled/software-development/software-development-writing-plans), [`requesting-code-review`](/user-guide/skills/bundled/software-development/software-development-requesting-code-review) |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Superforecasting Agent loads when this skill is triggered. This is what the agent sees as instructions when the skill is active.
:::

# Superforecasting Agent Skill Authoring Skill

Create and maintain skills shipped in this repository. This guide covers source
files and their checks; user-local skill installation remains a separate workflow.

## When to Use

Use when contributing or modernizing a bundled or optional skill in this checkout.
For user-local skills, use `skill_manage` instead of editing repository files.

## Prerequisites

Read the checkout's AGENTS.md and inspect the target category with `search_files`.
Use `read_file` to check nearby skills and `tools/skill_manager_tool.py` for runtime
validation. Repository authoring policy is stricter than the runtime's import
limits: descriptions must be at most 60 characters, one sentence ending in a period.

## How to Run

Use `read_file`, `write_file` and `patch` for repository source changes. Put bundled
skills under `skills/<category>/<canonical-name>/SKILL.md`; put heavy or niche
skills under `optional-skills/`. Do not use `skill_manage(action='create')` to
create committed source: it targets the active user's profile.

## Quick Reference

| Field or surface | Requirement |
| --- | --- |
| Frontmatter | Starts at byte zero with `---`; valid YAML mapping; closes before the body |
| Name | Canonical lowercase hyphenated name, at most 64 characters |
| Description | At most 60 characters, one sentence ending in a period |
| Attribution | Human contributor first for external contributions; retain license |
| Platforms | Match actual script imports and supported behavior |
| Metadata | Keep the published `metadata.hermes` schema for extension compatibility |
| Aliases | Preserve old commands in `metadata.hermes.aliases` when renaming |
| Supporting files | `scripts/`, `references/`, `templates/` or `assets/` |
| Tests | `tests/skills/test_<skill>_skill.py`; stdlib, pytest and mocks; no live network |

## Procedure

1. Check whether an existing skill already covers the workflow. Extend it before
   adding another skill or category.
2. Follow this section order: title and short introduction, When to Use,
   Prerequisites, How to Run, Quick Reference, Procedure, Pitfalls, Verification.
3. Describe interactions through available agent tools. Put multi-step code in a
   helper script rather than asking the agent to reconstruct it from prose.
4. Audit platform-sensitive imports and paths. Prefer portable behavior where
   possible; accurately narrow `platforms` where a platform is required.
5. Validate frontmatter and behavior, then run focused tests through
   `scripts/run_tests.sh tests/skills/test_<skill>_skill.py`.
6. Update generated references when source names or descriptions change. Keep
   published documentation identifiers stable at the generator's compatibility
   boundary and test old command aliases after directory moves.
7. Review the diff and commit only intended source, tests and generated documents.

## Pitfalls

- Runtime acceptance is not repository policy compliance. A description accepted
  by the runtime's 1024-character limit can still violate the 60-character policy.
- User-local skills are not automatically available in another contributor's
  checkout. Related-skill references should resolve to shipped skills.
- Renaming a directory must not leave duplicate bundled implementations. Preserve
  command compatibility through aliases and test disabled legacy names too.
- Cached skill discovery may require a fresh session. Do not mistake a stale
  loader view for proof that the committed file is missing.
- Do not rewrite unrelated `.env.example` content while adding a skill's settings.

## Verification

Check frontmatter, section order, platform declarations and supporting paths.
Run focused tests using the canonical runner, inspect generated references and
verify both canonical and legacy command resolution when renaming a skill.
The repository's full-suite pre-push gate remains required before publishing.

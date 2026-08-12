"""Link-rewriting contract of website/scripts/generate-skill-docs.py.

`rewrite_relative_links` turns sibling references in a SKILL.md body
(`references/foo.md`) into absolute repo blob URLs. It must NOT treat
`[key](value)`-shaped fragments inside code as links: a fenced
`sam_model_registry["vit_h"](checkpoint="x.pth")` sample and an inline
`` `![alt](url)` `` placeholder previously became genuine-404 blob URLs in
the generated docs. Only targets that really exist beside the SKILL.md may
be rewritten.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "website" / "scripts" / "generate-skill-docs.py"


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location("generate_skill_docs", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def skill_env(gen, tmp_path, monkeypatch):
    """A fake repo with one bundled skill that has real sibling files."""
    skill_dir = tmp_path / "skills" / "media" / "gif-search"
    (skill_dir / "references").mkdir(parents=True)
    (skill_dir / "references" / "foo.md").write_text("ref", encoding="utf-8")
    (skill_dir / "templates").mkdir()
    (skill_dir / "templates" / "bar.md").write_text("tpl", encoding="utf-8")
    monkeypatch.setattr(gen, "REPO", tmp_path)
    meta = {"source_kind": "bundled", "rel_path": "media/gif-search"}
    return meta


BASE = (
    "https://github.com/teddyjfpender/superforecasting-agent/blob/"
    "superforecasting-agent-snapshot/skills/media/gif-search"
)


def test_real_sibling_links_are_rewritten(gen, skill_env):
    body = "See [the guide](references/foo.md) and [tpl](./templates/bar.md)."
    out = gen.rewrite_relative_links(body, skill_env)
    assert f"[the guide]({BASE}/references/foo.md)" in out
    assert f"[tpl]({BASE}/templates/bar.md)" in out


def test_fenced_code_is_never_rewritten(gen, skill_env):
    body = (
        "Load it:\n\n"
        "```python\n"
        'sam = sam_model_registry["vit_h"](checkpoint="sam_vit_h_4b8939.pth")\n'
        "```\n"
    )
    out = gen.rewrite_relative_links(body, skill_env)
    assert 'sam_model_registry["vit_h"](checkpoint="sam_vit_h_4b8939.pth")' in out
    assert "github.com" not in out


def test_inline_code_is_never_rewritten(gen, skill_env):
    body = "GIF URLs can be used directly in markdown: `![alt](url)`"
    out = gen.rewrite_relative_links(body, skill_env)
    assert "`![alt](url)`" in out
    assert "github.com" not in out


def test_nonexistent_target_is_left_alone(gen, skill_env):
    # A prose "link" whose target is not a real sibling must not become a
    # (404) blob URL.
    body = "Insert [description](does-not-exist.png) after the paragraph."
    out = gen.rewrite_relative_links(body, skill_env)
    assert "[description](does-not-exist.png)" in out
    assert "github.com" not in out


def test_absolute_anchor_and_mailto_untouched(gen, skill_env):
    body = (
        "[a](https://example.com/x) [b](#section) [c](mailto:x@y.z) "
        "[d](/rooted/path)"
    )
    assert gen.rewrite_relative_links(body, skill_env) == body


def test_link_with_anchor_on_real_file_is_rewritten(gen, skill_env):
    body = "See [sec](references/foo.md#usage)."
    out = gen.rewrite_relative_links(body, skill_env)
    assert f"[sec]({BASE}/references/foo.md#usage)" in out


def test_mixed_body_only_rewrites_prose_links(gen, skill_env):
    body = (
        "Intro [guide](references/foo.md) and `![alt](url)`.\n\n"
        "```python\n"
        'registry["k"](checkpoint="w.pth")\n'
        "```\n\n"
        "Outro [missing](nope.md).\n"
    )
    out = gen.rewrite_relative_links(body, skill_env)
    assert f"[guide]({BASE}/references/foo.md)" in out
    assert "`![alt](url)`" in out
    assert 'registry["k"](checkpoint="w.pth")' in out
    assert "[missing](nope.md)" in out
    assert out.count("github.com") == 1

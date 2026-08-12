from pathlib import Path
import runpy
import sys
import tomllib
from types import ModuleType
from unittest.mock import Mock, patch


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_faster_whisper_is_not_a_base_dependency():
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]

    assert not any(dep.startswith("faster-whisper") for dep in deps)

    voice_extra = data["project"]["optional-dependencies"]["voice"]
    assert any(dep.startswith("faster-whisper") for dep in voice_extra)


def test_manifest_includes_bundled_skills():
    manifest = (REPO_ROOT / "MANIFEST.in").read_text(encoding="utf-8")

    assert "graft skills" in manifest
    assert "graft optional-skills" in manifest
    assert "global-exclude __pycache__" in manifest
    assert "global-exclude *.py[cod]" in manifest


def test_skill_data_file_tree_excludes_python_caches(tmp_path):
    setuptools = ModuleType("setuptools")
    setuptools.setup = Mock()
    with patch.dict(sys.modules, {"setuptools": setuptools}):
        setup_module = runpy.run_path(str(REPO_ROOT / "setup.py"))
    setup_module["_data_file_tree"].__globals__["REPO_ROOT"] = tmp_path

    skill = tmp_path / "skills" / "research" / "example"
    cache = skill / "scripts" / "__pycache__"
    cache.mkdir(parents=True)
    (skill / "SKILL.md").write_text("skill", encoding="utf-8")
    (cache / "helper.cpython-311.pyc").write_bytes(b"cache")
    (skill / "scripts" / "helper.pyo").write_bytes(b"cache")

    files = {
        path
        for _destination, paths in setup_module["_data_file_tree"]("skills")
        for path in paths
    }
    assert files == {"skills/research/example/SKILL.md"}

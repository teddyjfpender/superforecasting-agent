"""Exercise the real documentation checker against isolated generated output."""

import subprocess

import pytest

from scripts.docgen import registry


def test_stale_reference_rejected_without_rewrite(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(registry, "repo_root", lambda: tmp_path)
    paths = registry.write()
    assert registry.main(["--check"]) == 0
    target = paths[0]
    target.write_text("deliberately stale\n", encoding="utf-8")
    assert registry.main(["--check"]) == 1
    assert target.read_text(encoding="utf-8") == "deliberately stale\n"
    error = capsys.readouterr().err
    assert "STALE" in error
    assert str(target.relative_to(tmp_path)) in error


@pytest.mark.parametrize("arguments,code", [(["--help"], 0), (["--chek"], 2), (["unexpected"], 2)])
def test_help_and_invalid_arguments_cannot_generate_files(monkeypatch, arguments, code):
    def forbidden():
        pytest.fail("argument handling reached generation")
    monkeypatch.setattr(registry, "write", forbidden)
    monkeypatch.setattr(registry, "check", forbidden)
    with pytest.raises(SystemExit) as exc:
        registry.main(arguments)
    assert exc.value.code == code


def test_canonical_gate_propagates_real_staleness(tmp_path, monkeypatch):
    from scripts import dev

    monkeypatch.setattr(registry, "repo_root", lambda: tmp_path)
    registry.write()
    target = registry.reference_dir() / "README.md"
    target.unlink()
    monkeypatch.setattr(dev, "venv_tool", lambda name: name)
    def run(*args, **kwargs):
        if args == ("python", "-m", "scripts.docgen", "--check"):
            code = registry.main(["--check"])
            if code:
                raise subprocess.CalledProcessError(code, args)
    monkeypatch.setattr(dev, "run", run)
    with pytest.raises(subprocess.CalledProcessError) as exc:
        dev.check(python_only=True)
    assert exc.value.returncode == 1
    assert not target.exists()

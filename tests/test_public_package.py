"""The public package remains a lightweight entry to startup and domain APIs."""

import subprocess
import sys

import pytest


@pytest.mark.parametrize("module", ["bootstrap", "environment", "urls"])
def test_lightweight_import_does_not_initialize_forecasting(module):
    result = subprocess.run(
        [sys.executable, "-c", f"""
import sys
import superforecasting_agent.{module}
assert 'forecasting' not in sys.modules
assert 'superforecasting_agent.constants' not in sys.modules
assert 'importlib.metadata' not in sys.modules
assert 'yaml' not in sys.modules
"""],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


def test_public_exports_preserve_domain_identity():
    import forecasting
    import superforecasting_agent as package

    for name in forecasting.__all__:
        assert getattr(package, name) is getattr(forecasting, name)
        assert name in dir(package)
    assert isinstance(package.__version__, str)
    try:
        package.unknown_public_export
    except AttributeError:
        pass
    else:
        raise AssertionError("Unknown exports must raise AttributeError")


@pytest.mark.parametrize("package_root", ["protocol", "superforecasting_agent"])
def test_distribution_includes_runtime_subpackages(package_root):
    """Runtime subpackages must survive installation from a wheel."""
    import tomllib
    from pathlib import Path
    from fnmatch import fnmatchcase

    root = Path(__file__).resolve().parents[1]
    with (root / "pyproject.toml").open("rb") as stream:
        config = tomllib.load(stream)
    discovery = config["tool"]["setuptools"]["packages"]["find"]
    packages = [
        ".".join(path.parent.relative_to(root).parts)
        for path in (root / package_root).rglob("__init__.py")
    ]
    assert packages
    for package in packages:
        assert any(fnmatchcase(package, pattern) for pattern in discovery["include"])
        assert not any(fnmatchcase(package, pattern) for pattern in discovery.get("exclude", []))

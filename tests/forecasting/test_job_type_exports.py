"""Job type export lists must describe names the module actually supplies."""
import importlib

import pytest


@pytest.mark.parametrize("name", ["backup", "quorum", "reforecast", "refresh", "task", "warnings", "wiki_prune"])
def test_job_type_declared_exports_are_importable(name):
    module = importlib.import_module(f"forecasting.jobs.types.{name}")
    namespace = {}
    exec(f"from {module.__name__} import *", namespace)
    assert all(namespace[export] is getattr(module, export) for export in module.__all__)

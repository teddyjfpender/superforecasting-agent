"""Tests for superforecasting_agent.storage.files.atomic_yaml_write — crash-safe YAML file writes."""

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from superforecasting_agent.storage.files import atomic_yaml_write


class TestAtomicYamlWrite:
    def test_writes_valid_yaml(self, tmp_path):
        target = tmp_path / "data.yaml"
        data = {"key": "value", "nested": {"a": 1}}

        atomic_yaml_write(target, data)

        assert yaml.safe_load(target.read_text(encoding="utf-8")) == data

    def test_cleans_up_temp_file_on_baseexception(self, tmp_path):
        class SimulatedAbort(BaseException):
            pass

        target = tmp_path / "data.yaml"
        original = {"preserved": True}
        target.write_text(yaml.safe_dump(original), encoding="utf-8")

        with patch("superforecasting_agent.storage.files.yaml.dump", side_effect=SimulatedAbort):
            with pytest.raises(SimulatedAbort):
                atomic_yaml_write(target, {"new": True})

        tmp_files = [f for f in tmp_path.iterdir() if ".tmp" in f.name]
        assert len(tmp_files) == 0
        assert yaml.safe_load(target.read_text(encoding="utf-8")) == original

    def test_appends_extra_content(self, tmp_path):
        target = tmp_path / "data.yaml"

        atomic_yaml_write(target, {"key": "value"}, extra_content="\n# comment\n")

        text = target.read_text(encoding="utf-8")
        assert "key: value" in text
        assert "# comment" in text


def _set_config_in_process(path, key):
    from superforecasting_agent.storage.files import atomic_roundtrip_yaml_update
    atomic_roundtrip_yaml_update(path, key, key)


def test_parallel_process_updates_preserve_each_others_keys(tmp_path):
    from concurrent.futures import ProcessPoolExecutor
    import multiprocessing
    import yaml
    path = tmp_path / 'config.yaml'
    path.write_text('providers:\n  - name: original\n')
    with ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context('spawn')) as pool:
        futures = [pool.submit(_set_config_in_process, path, f'worker.key{i}') for i in range(8)]
        for future in futures:
            future.result(timeout=15)
    from superforecasting_agent.storage.files import atomic_roundtrip_yaml_update
    atomic_roundtrip_yaml_update(path, 'providers.0.name', 'updated')
    config = yaml.safe_load(path.read_text())
    assert config['worker'] == {f'key{i}': f'worker.key{i}' for i in range(8)}
    assert config['providers'] == [{'name': 'updated'}]


def test_invalid_yaml_is_not_overwritten(tmp_path):
    from superforecasting_agent.storage.files import atomic_roundtrip_yaml_update
    import pytest
    path = tmp_path / 'config.yaml'
    for original in ('providers: [broken', '- not-a-config-mapping\n'):
        path.write_text(original)
        with pytest.raises(Exception):
            atomic_roundtrip_yaml_update(path, 'model.default', 'new')
        assert path.read_text() == original

"""Host configuration preserves profile identity and optimistic concurrency."""
import os

import pytest
import yaml

from superforecasting_agent.hosting.configuration import ProfileConfiguration


def test_profile_snapshots_are_isolated_and_cannot_cross_save(tmp_path):
    owner = ProfileConfiguration()
    first, second = tmp_path / 'first.yaml', tmp_path / 'second.yaml'
    first.write_text('display:\n  skin: mono\n')
    second.write_text('display:\n  skin: ares\n')
    snapshot = owner.load(first)
    snapshot['display']['skin'] = 'forecast'
    assert owner.load(first)['display']['skin'] == 'mono'
    assert owner.load(second)['display']['skin'] == 'ares'
    with pytest.raises(ValueError, match='reload'):
        owner.save(second, snapshot)
    owner.save(first, snapshot)
    assert yaml.safe_load(first.read_text())['display']['skin'] == 'forecast'
    assert yaml.safe_load(second.read_text())['display']['skin'] == 'ares'


def test_same_size_timestamp_change_invalidates_snapshot(tmp_path):
    path = tmp_path / 'config.yaml'
    owner = ProfileConfiguration()
    path.write_text('model: first\n')
    before = path.stat()
    stale = owner.load(path)
    path.write_text('model: other\n')
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert owner.load(path)['model'] == 'other'
    with pytest.raises(ValueError, match='reload'):
        owner.save(path, stale)


def test_malformed_configuration_is_diagnosed_and_not_overwritten(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text('invalid: [')
    owner = ProfileConfiguration()
    config = owner.load(path)
    assert config == {} and owner.last_error
    with pytest.raises(ValueError, match='reload'):
        owner.save(path, config)
    assert path.read_text() == 'invalid: ['
    path.write_text('model: repaired\n')
    assert owner.load(path)['model'] == 'repaired'
    assert owner.last_error is None


def test_independent_owners_preserve_updates_and_reject_stale_save(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text('# retained comment\nmodel: first\n')
    first, second = ProfileConfiguration(), ProfileConfiguration()
    stale = first.load(path)
    second.update(path, 'display.skin', 'mono')
    first.update(path, 'agent.max_turns', 4)
    with pytest.raises(ValueError, match='reload'):
        first.save(path, stale)
    assert first.load(path) == {'model': 'first', 'display': {'skin': 'mono'}, 'agent': {'max_turns': 4}}
    assert '# retained comment' in path.read_text()

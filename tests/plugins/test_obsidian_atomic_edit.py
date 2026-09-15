from concurrent.futures import ThreadPoolExecutor

import pytest

from plugins.obsidian.vault import write_note


def test_stale_editor_never_overwrites_another_writer(tmp_path):
    note = tmp_path / 'note.md'
    write_note(note, 'original')
    write_note(note, 'updated', expected_content='original')
    with pytest.raises(ValueError, match='changed'):
        write_note(note, 'stale edit', expected_content='original')
    assert note.read_text() == 'updated'


def test_concurrent_editors_admit_exactly_one_original_revision(tmp_path):
    note = tmp_path / 'note.md'
    write_note(note, 'original')
    def edit(value):
        try:
            write_note(note, value, expected_content='original')
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(edit, ['one', 'two']))
    assert results.count(True) == 1
    assert note.read_text() in {'one', 'two'}


def test_failed_atomic_replace_keeps_original(tmp_path, monkeypatch):
    import superforecasting_agent.storage.files as files
    note = tmp_path / 'note.md'
    write_note(note, 'original')
    def fail(*args, **kwargs):
        raise OSError('injected failure')
    monkeypatch.setattr(files, 'atomic_replace', fail)
    with pytest.raises(OSError):
        write_note(note, 'replacement', expected_content='original')
    assert note.read_text() == 'original'

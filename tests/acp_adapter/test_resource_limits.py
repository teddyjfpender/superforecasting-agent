"""Attachment limits apply even if a local image grows after its size check."""

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from acp.schema import ResourceContentBlock

from acp_adapter.server import (
    _MAX_ACP_RESOURCE_BYTES,
    _content_blocks_to_openai_user_content,
)


def test_image_growth_cannot_bypass_read_limit(monkeypatch, tmp_path):
    attached = tmp_path / 'growing.png'
    attached.write_bytes(b'x' * (_MAX_ACP_RESOURCE_BYTES + 1024))
    stat = Path.stat
    open_file = Path.open
    bytes_read = []

    def stale_stat(path, *args, **kwargs):
        if path == attached:
            return SimpleNamespace(st_size=1)
        return stat(path, *args, **kwargs)

    @contextmanager
    def observed_open(path, *args, **kwargs):
        with open_file(path, *args, **kwargs) as handle:
            yield handle
            if path == attached:
                bytes_read.append(handle.tell())

    monkeypatch.setattr(Path, 'stat', stale_stat)
    monkeypatch.setattr(Path, 'open', observed_open)
    content = _content_blocks_to_openai_user_content([
        ResourceContentBlock(type='resource_link', name=attached.name, uri=attached.as_uri()),
    ])

    assert bytes_read and max(bytes_read) <= _MAX_ACP_RESOURCE_BYTES + 1
    assert isinstance(content, str)
    assert 'Image too large to inline' in content

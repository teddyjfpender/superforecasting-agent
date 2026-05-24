from agent import file_safety


def test_read_block_error_uses_forecast_native_cache_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(file_safety, "_hermes_home_path", lambda: tmp_path)
    cache_file = tmp_path / "skills" / ".hub" / "index-cache" / "catalog.json"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_text("{}", encoding="utf-8")

    message = file_safety.get_read_block_error(str(cache_file))

    assert message is not None
    assert "internal agent cache file" in message
    assert "internal Hermes cache file" not in message

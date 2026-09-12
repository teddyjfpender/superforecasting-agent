"""Credential reads preserve current contents and never mutate profile state."""

import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from superforecasting_agent.storage import environment


def test_repeat_reads_cache_parsing_but_return_independent_mappings(
    tmp_path, monkeypatch
):
    path = tmp_path / ".env"
    path.write_text("FIRST=oneSECOND=two\n", encoding="utf-8")
    parse = environment.parse_environment
    calls = []

    def record(contents, known_keys):
        calls.append(contents)
        return parse(contents, known_keys)

    environment.clear_environment_cache()
    monkeypatch.setattr(environment, "parse_environment", record)
    first = environment.read_environment(path, known_keys={"FIRST", "SECOND"})
    first["FIRST"] = "changed by caller"
    assert environment.read_environment(path, known_keys={"FIRST", "SECOND"}) == {
        "FIRST": "one",
        "SECOND": "two",
    }
    assert len(calls) == 1
    # Recognition rules are part of the parse, even when the file is unchanged.
    assert environment.read_environment(path, known_keys={"FIRST"}) == {
        "FIRST": "oneSECOND=two"
    }
    assert len(calls) == 2


def test_profiles_are_independent_under_concurrent_reads(tmp_path):
    paths = [tmp_path / "one.env", tmp_path / "two.env"]
    for index, path in enumerate(paths):
        path.write_text(f"TOKEN=profile-{index}\n", encoding="utf-8")
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [
            workers.submit(environment.read_environment, paths[index % 2])
            for index in range(20)
        ]
        assert [f.result()["TOKEN"] for f in futures] == [
            f"profile-{i % 2}" for i in range(20)
        ]


def test_reader_preserves_bytes_and_process_environment(tmp_path, monkeypatch):
    directory = tmp_path / "profile"
    directory.mkdir()
    path = directory / ".env"
    contents = b'\xef\xbb\xbf# comment\nTOKEN="first"\nTOKEN=last\nBAD=\xff\n'
    path.write_bytes(contents)
    monkeypatch.setenv("TOKEN", "process-value")
    assert environment.read_environment(path) == {"TOKEN": "last", "BAD": "\ufffd"}
    assert path.read_bytes() == contents
    assert os.environ["TOKEN"] == "process-value"
    assert list(directory.iterdir()) == [path]
    path.unlink()
    assert environment.read_environment(path) == {}
    assert not path.exists()


def test_read_errors_are_not_reported_as_empty_credentials(tmp_path, monkeypatch):
    path = tmp_path / ".env"

    def denied(*args, **kwargs):
        raise PermissionError("fixture access denied")

    monkeypatch.setattr(type(path), "read_text", denied)
    with pytest.raises(PermissionError, match="fixture access denied"):
        environment.read_environment(path)


@pytest.mark.parametrize("separator", ["\u2028", "\x85", "\v"])
def test_non_newline_characters_inside_values_are_preserved(tmp_path, separator):
    path = tmp_path / ".env"
    value = f"prefix{separator}suffix"
    path.write_text(f"VALUE={value}\r\n", encoding="utf-8")
    assert environment.read_environment(path) == {"VALUE": value}

"""The upgrade verifier permits schema additions, never lost historical data."""
import pytest

from scripts.verify_profiles import assert_preserved


def test_added_fields_preserve_existing_provenance():
    assert_preserved(
        {"history": [{"probability": 0.7, "source": "fixture"}]},
        {"history": [{"probability": 0.7, "source": "fixture", "revision": 1}], "schema": 2},
    )


@pytest.mark.parametrize(
    "after",
    [
        {},
        {"history": []},
        {"history": [{"probability": 0.8, "source": "fixture"}]},
        {"history": [{"probability": 0.7, "source": "different"}]},
        {"history": [{"probability": "0.7", "source": "fixture"}]},
    ],
)
def test_missing_changed_or_retyped_state_fails(after):
    with pytest.raises(AssertionError, match="history"):
        assert_preserved({"history": [{"probability": 0.7, "source": "fixture"}]}, after)


def test_boolean_is_not_accepted_as_numeric_state():
    with pytest.raises(AssertionError):
        assert_preserved({"count": 1}, {"count": True})


def test_upgrade_requires_successor_not_reinstall_or_downgrade():
    from scripts.verify_profiles import require_upgrade
    require_upgrade({"version": "0.9.0"}, {"version": "0.10.0"})
    for version in ("0.9.0", "0.8.0"):
        with pytest.raises(ValueError, match="strictly newer"):
            require_upgrade({"version": "0.9.0"}, {"version": version})


def test_wheel_identity_checks_metadata_not_filename(tmp_path):
    import hashlib
    import zipfile
    from scripts.verify_profiles import wheel_identity
    path = tmp_path / "misleading.whl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("product.dist-info/METADATA", "Name: superforecasting-agent-tui\nVersion: 0.1.0\n")
    identity = wheel_identity(path, "superforecasting-agent-tui")
    assert identity["version"] == "0.1.0"
    assert identity["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="expected superforecasting-agent,"):
        wheel_identity(path, "superforecasting-agent")


def test_failed_qualification_writes_receipt(tmp_path, monkeypatch):
    import json
    from scripts import verify_profiles
    report = tmp_path / "evidence" / "report.json"
    monkeypatch.setattr("sys.argv", ["verify_profiles", str(tmp_path), "--report", str(report)])
    def fail(args, receipt):
        receipt["checks"]["fixture"] = "passed"
        raise RuntimeError("controlled failure")
    monkeypatch.setattr(verify_profiles, "verify", fail)
    with pytest.raises(RuntimeError, match="controlled failure"):
        verify_profiles.main()
    saved = json.loads(report.read_text())
    assert saved["status"] == "failed"
    assert saved["checks"]["fixture"] == "passed"
    assert saved["platform"]["machine"]


def test_upgrade_baseline_rejects_untrusted_download():
    from scripts.prepare_upgrade_baselines import verify_backend

    with pytest.raises(ValueError, match="checksum"):
        verify_backend(b"plausible but incorrect wheel bytes")

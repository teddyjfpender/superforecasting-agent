"""Every support payload identifies installed artifacts before output or upload."""

from importlib import metadata

from superforecasting_agent.application import diagnostics


def test_installed_identity_does_not_use_source_version(monkeypatch):
    monkeypatch.setattr(
        metadata,
        "version",
        lambda name: {
            "superforecasting-agent": "0.22.1",
            "superforecasting-agent-tui": "0.1.1",
        }[name],
    )
    result = diagnostics.diagnostic_payload(
        "secret", sanitize=lambda text: text.replace("secret", "[REDACTED]")
    )
    assert "superforecasting-agent: 0.22.1" in result
    assert "superforecasting-agent-tui: 0.1.1" in result
    assert "secret" not in result


def test_absent_distribution_is_explicit(monkeypatch):
    def absent(name):
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(metadata, "version", absent)
    assert all(
        "not installed" in version
        for version in diagnostics.installed_product_versions().values()
    )

import sys

import pytest


def test_gateway_run_help_is_forecast_native(monkeypatch, capsys):
    import gateway.run as gateway_run

    monkeypatch.setattr(sys, "argv", ["gateway-run", "--help"])

    with pytest.raises(SystemExit) as exc:
        gateway_run.main()

    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "Superforecasting Agent Gateway" in output
    assert "Hermes Gateway" not in output

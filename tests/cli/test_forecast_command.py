import json


def test_forecast_slash_command_delegates_to_forecast_cli(tmp_path, capsys):
    from cli import HermesCLI

    cli = HermesCLI.__new__(HermesCLI)
    db_path = tmp_path / "forecast.sqlite"

    HermesCLI._handle_forecast_command(
        cli,
        f"/forecast --db {db_path} status --json",
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["slug"] == "superforecasting-agent"
    assert payload["ledger_path"] == str(db_path)

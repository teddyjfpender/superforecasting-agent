import sys


def test_bare_top_level_defaults_to_forecast_desk(monkeypatch):
    import hermes_cli.main as main_mod
    import forecasting.cli as forecast_cli

    captured = {}

    def fake_cmd_forecast(args):
        captured["command"] = args.command
        captured["db"] = getattr(args, "db", None)

    monkeypatch.setattr(main_mod, "cmd_chat", lambda _args: (_ for _ in ()).throw(AssertionError("chat should not run")))
    monkeypatch.setattr(forecast_cli, "cmd_forecast", fake_cmd_forecast)
    monkeypatch.setattr(sys, "argv", ["hermes"])

    main_mod.main()

    assert captured == {"command": None, "db": None}


def test_top_level_skills_flag_defaults_to_forecast_desk(monkeypatch):
    import hermes_cli.main as main_mod
    import forecasting.cli as forecast_cli

    captured = {}

    def fake_cmd_forecast(args):
        captured["skills"] = args.skills
        captured["command"] = args.command

    monkeypatch.setattr(main_mod, "cmd_chat", lambda _args: (_ for _ in ()).throw(AssertionError("chat should not run")))
    monkeypatch.setattr(forecast_cli, "cmd_forecast", fake_cmd_forecast)
    monkeypatch.setattr(
        sys,
        "argv",
        ["hermes", "-s", "hermes-agent-dev,github-auth"],
    )

    main_mod.main()

    assert captured == {
        "skills": ["hermes-agent-dev,github-auth"],
        "command": None,
    }


def test_chat_subcommand_accepts_skills_flag(monkeypatch):
    import hermes_cli.main as main_mod

    captured = {}

    def fake_cmd_chat(args):
        captured["skills"] = args.skills
        captured["query"] = args.query

    monkeypatch.setattr(main_mod, "cmd_chat", fake_cmd_chat)
    monkeypatch.setattr(
        sys,
        "argv",
        ["hermes", "chat", "-s", "github-auth", "-q", "hello"],
    )

    main_mod.main()

    assert captured == {
        "skills": ["github-auth"],
        "query": "hello",
    }


def test_chat_subcommand_accepts_image_flag(monkeypatch):
    import hermes_cli.main as main_mod

    captured = {}

    def fake_cmd_chat(args):
        captured["query"] = args.query
        captured["image"] = args.image

    monkeypatch.setattr(main_mod, "cmd_chat", fake_cmd_chat)
    monkeypatch.setattr(
        sys,
        "argv",
        ["hermes", "chat", "-q", "hello", "--image", "~/storage/shared/Pictures/cat.png"],
    )

    main_mod.main()

    assert captured == {
        "query": "hello",
        "image": "~/storage/shared/Pictures/cat.png",
    }


def test_continue_worktree_and_skills_flags_work_together(monkeypatch):
    import hermes_cli.main as main_mod

    captured = {}

    def fake_cmd_chat(args):
        captured["continue_last"] = args.continue_last
        captured["worktree"] = args.worktree
        captured["skills"] = args.skills
        captured["command"] = args.command

    monkeypatch.setattr(main_mod, "cmd_chat", fake_cmd_chat)
    monkeypatch.setattr(
        sys,
        "argv",
        ["hermes", "-c", "-w", "-s", "hermes-agent-dev"],
    )

    main_mod.main()

    assert captured == {
        "continue_last": True,
        "worktree": True,
        "skills": ["hermes-agent-dev"],
        "command": "chat",
    }

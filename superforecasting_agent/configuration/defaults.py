"""Shared product defaults; data only, without profile or runtime initialization."""

from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    "model": "",
    "providers": {},
    "fallback_providers": [],
    "credential_pool_strategies": {},
    "toolsets": ["forecast-desk"],
    # Quorum — model-diverse forecast panel ("Fusion" analogue). When
    # default_enabled is on, a quorum AUTO-RUNS (detached background job) at the
    # update stage wherever a deliberative panel is already indicated (see
    # default_scope), attaching to the just-committed snapshot — so a lazy prompter
    # gets multi-model fusion without passing flags every time. Bounded by
    # default_scope (which updates qualify) and max_calls (the per-run cost cap);
    # an auto-run failure is fail-open (the commit already happened). See
    # forecasting/quorum.py.
    "quorum": {
        # Auto-run a quorum panel when a panel is indicated. ENABLED by default:
        # the north-star is superforecaster-grade process per keystroke, bounded
        # by default_scope + max_calls below.
        "default_enabled": True,
        # Which indicated panels get an auto-run quorum when default_enabled:
        #   "high_impact" — only high-impact / first-forecast (the existing
        #                   panel trigger). Keeps the multi-model spend bounded.
        #   "always"      — every probability-bearing update (expensive).
        #   "first_only"  — only the first forecast for a question.
        "default_scope": "high_impact",
        # Per-run model-call CAP. A resolved preset whose pre-run call estimate
        # ((models+1 judge) × delphi multiplier) exceeds this is DOWNGRADED to the
        # largest fitting preset (dropping the Delphi round first). Applies to the
        # auto-run path AND manual runs that pass no explicit --preset.
        "max_calls": 12,
        # Default panel preset when none is passed: frontier | budget | self.
        "preset": "frontier",
        # Optional explicit model list (OpenRouter ids); overrides the preset.
        "models": [],
        # Judge model for the synthesis pass. Empty = preset default.
        "judge": "",
        # Pooling: trimmed_geomean_odds | log_odds_pool | median.
        "pool_method": "trimmed_geomean_odds",
        "trim": 1,
        # Per-panelist runtime ceiling (seconds) and tool-iteration cap.
        "model_timeout": 300,
        "max_iterations": 30,
        # GATE 2 (AIA P1.1, live) — agentic-supervisor fresh-search loop. When ON
        # and the judge flags an unresolved crux (information_gap +
        # clarifying_queries), the supervisor runs a bounded real web/news search
        # and re-synthesises once on the fresh evidence — the only path to BEATING
        # the market (the closed-book LLM has no intrinsic edge). DEFAULT ON for LIVE
        # quorum runs (the audit's finding #1: it had fired 0/223 times while OFF).
        # It is BOUNDED (max_research_rounds clamped to 3, per-round query/result
        # caps) and LEAK-SAFE: the run_quorum/quorum-jobs path gates it OFF
        # AUTOMATICALLY for a historical evidence_cutoff (backtest/replay), so fresh
        # present-day search can never leak into a past-pinned forecast. Set to False
        # here to disable it fleet-wide, or per-run with
        # `forecast quorum --supervisor-search`/`--no-supervisor-search`.
        "supervisor_search": True,
        # TRACK-RECORD PANELIST WEIGHTING (S7). Weight each panelist by its measured
        # Brier edge over past resolved binaries (shrunk toward 1.0, clipped). DEFAULT
        # ON but HARMLESS-BY-CONSTRUCTION on cold start: a model must clear the
        # resolved-sample gate (track_record_min_sample) before its weight moves off
        # 1.0, so with no history every panelist is equal-weighted and the committed
        # number is byte-identical to the unweighted pool. The applied weights are
        # echoed in the quorum result so the operator sees why. Set False to force
        # equal weights always.
        "track_record_weights": True,
        # Resolved-binary sample a model must clear before its measured weight is
        # trusted (below it: weight 1.0). No model dominates early.
        "track_record_min_sample": 10,
    },
    "forecasting": {
        # Terminal-calibration derivation. EVIDENCE-GATED EXTREMIZATION (item 6):
        # when derive_alpha is ON and a question carries NO explicit per-question
        # alpha_extremize override, the quorum derives its terminal Platt slope from
        # the domain's RESOLVED calibration via the validated extremization gate
        # (sqrt(3) permitted only where the scope is measurably under-confident;
        # 1.0 otherwise). DEFAULT OFF (fail-safe cold start): until a desk has enough
        # resolved binaries per domain, the derived value is 1.0 anyway, and leaving
        # it off keeps every committed number byte-identical to the hand-set/identity
        # slope. An explicit metadata alpha_extremize ALWAYS wins over derivation.
        "calibration": {
            "derive_alpha": False,
        },
        # Forecast saturation + style HOOKS: commit-time checks that block or warn
        # when a forecast is under-saturated (no decomposition, stale evidence, no
        # panel, missing citations, unjustified tail mass) or violates house style.
        # See `forecast hooks ...` to inspect / tune / author rules.
        "hooks": {
            # Master switch. False -> every rule is advisory (nothing blocks).
            "enabled": True,
            # Baseline profile: exploratory-lenient | standard | strict | superforecaster.
            # "standard" is the default enforcement tier; "superforecaster" is the
            # opt-in "10/10 or blocked" tier (every gate ERROR).
            "profile": "standard",
            # Bump a question up/down the strictness ladder by its impact, with no
            # per-question config (ladder: exploratory-lenient < standard < strict).
            # Default 0 = no auto-bump (high-impact already hard-requires a panel via
            # the panel gate). Set high.delta=1 to opt a desk into FULL strictness on
            # high-impact forecasts (also require citations, decision card, tail paths).
            "impact_scaling": {
                "high": {"delta": 0},
                "medium": {"delta": 0},
                "low": {"delta": 0},
            },
            # Non-live origins never block (advisory only); "inherit" keeps the profile.
            "origin_scaling": {
                "exploratory": "off",
                "backtest": "off",
                "imported_baseline": "off",
                "live": "inherit",
            },
            # Per-rule severity overrides (off | warn | error), applied after the
            # profile. Keys are built-in rule ids or user-rule ids.
            "overrides": {},
            # User-defined rules: a workspace file of declarative rule specs (Phase 5).
            "rules_file": "hooks/rules.yaml",
            "rules": [],
        },
        # Recurrence-by-default: committing the first forecast idempotently installs
        # a nightly no-agent self-check cron (auto-score + auto-postmortem + thesis
        # aggregate + lesson synthesis + deterministic refresh) so forecasts stay
        # fresh without the operator remembering to schedule anything. Cheap + silent
        # when the cron is already installed.
        "cron": {
            # False -> never auto-install the nightly cron at commit time (explicit
            # `forecast freshen` / `keep_fresh` still install it on demand).
            "auto_install": True,
            # Install the bounded warning worker with the nightly routine. It owns
            # high-severity alert liveness and uses transactional spend leases.
            "warning_automode_auto_install": True,
        },
        # Gateway DUE-SWEEPER: the Desk shows a review as "due now" the instant its
        # next_run_at passes, but historically only the NIGHTLY self-check cron
        # ACTED on due-ness — a review due at 09:00 sat idle until the next 08:00
        # tick. While the gateway runs, its cron ticker also checks (on this cadence)
        # whether any scheduled review is due and, if so, runs the SAME deterministic
        # sweep the nightly does (refresh + self-check + saturation + free-tier drain;
        # NO agent/LLM). Guarded against concurrent sweeps and against doubling the
        # nightly cron's work.
        "reviews": {
            # Minutes between gateway due-sweeps (0 disables — the nightly cron stays
            # the only executor). Cheap when nothing is due (one indexed COUNT).
            "sweep_interval_minutes": 10,
        },
        # VOI-directed research + the research-adequacy judge (research_audit.py):
        # the research stage plans against the question's OWN levers (update
        # triggers, change_my_mind, outcome paths) and, before finishing, audits
        # whether the evidence set is adequate (reference class present, evidence
        # floor, source independence, disconfirming evidence, recency, trigger
        # coverage). The chain loop re-runs research when the deterministic audit
        # says inadequate, up to `max_audit_rounds` EXTRA passes.
        "research": {
            # A forecast is "research-adequate" when it clears the ERROR-weight
            # checks (reference class + evidence floor) AND scores >= this out of
            # 100. Also the WARN/ERROR threshold for the `research_adequate` hook.
            "adequacy_threshold": 70,
            # Max EXTRA research passes the chain loop runs when the post-research
            # audit reports the evidence set is inadequate (0 = never re-run).
            "max_audit_rounds": 2,
        },
        # Operator practice loop (R2): the desk's goal is to make the OPERATOR a
        # superforecaster, not only to score itself. When estimate_first is ON,
        # the agent ASKS the user for THEIR probability BEFORE revealing its own
        # number on a new-question / update conversation, records it (context
        # 'practice'), then proceeds — so the human builds a scored track record.
        # DEFAULT OFF: strictly opt-in; with it off the chat/update prompts are
        # byte-identical to before (no elicitation sentence is injected).
        "practice": {
            "estimate_first": False,
        },
        # R4 Living Models: Market Models are scored at resolution (Brier for a
        # binary projection; interval coverage + absolute error for a numeric one),
        # a per-model SKILL accrues on-read from those scores, and the deterministic
        # forecast refresh scales each model-sourced ensemble component's weight by
        # its model's skill multiplier before re-pooling.
        "models": {
            # Weight model-sourced components by measured skill in the deterministic
            # re-pool. DEFAULT ON but HARMLESS-BY-CONSTRUCTION on cold start: a model
            # must clear the resolved-binary sample gate before its multiplier moves
            # off 1.0, so with no history the pooled number is byte-identical to the
            # unweighted re-pool. Applied multipliers are echoed in the snapshot
            # metadata (refresh.skill_multipliers). Set False to force identity.
            "skill_weights": True,
        },
        # Free-tier warning DRAIN by default: the nightly self-check ends with a
        # zero-token-spend sweep that RESOLVES the free-tier open-alert backlog
        # through REAL gated work (score / postmortem / watched-source re-check /
        # bookkeeping close-out) — never the paid (LLM reforecast/evidence) or manual
        # (operator-judgment, incl. contested_label) kinds. Free warnings that merely
        # capture changed source data + write it to the ledger drain themselves
        # instead of piling up as operator to-dos. See docs/scheduled-routines.md.
        "warnings": {
            # False -> the nightly free-tier drain never runs (the standalone
            # `forecast warnings automode` command still drains on demand).
            "auto_free_tier": True,
            # Max free-tier alerts drained per nightly sweep. A large backlog drains
            # over a few nights (1,250 at 500/sweep ~= 3 nights), or immediately via
            # `forecast warnings automode`. 0 disables the drain.
            "free_tier_sweep_cap": 500,
        },
        # MarketNightly A/B research arm (forecasting/market_nightly.py): the
        # foreknowledge-proof live benchmark can forecast each OPEN market with the
        # PLAIN agent-protocol packet or the VOI research-disciplined packet (VOI
        # research plan + adequacy source-coverage floor) so the Arc-2 research lift
        # becomes ATTRIBUTABLE on the only scoreboard that can prove it.
        "market_nightly": {
            # Default arm for `forecast market-nightly run` (override per-run with
            # --research-arm):
            #   plain -> the plain packet (the existing accrued record),
            #   voi   -> the research-disciplined packet,
            #   both  -> forecast each market with BOTH arms (2x LLM calls),
            #            recording two pendings so `report` shows the PAIRED
            #            voi-vs-plain Brier delta.
            # DEFAULT 'plain' so the accrued record stays comparable going forward.
            "research_arm": "plain",
        },
    },
    "agent": {
        "max_turns": 90,
        # Inactivity timeout for gateway agent execution (seconds).
        # The agent can run indefinitely as long as it's actively calling
        # tools or receiving API responses.  Only fires when the agent has
        # been completely idle for this duration.  0 = unlimited.
        "gateway_timeout": 1800,
        # Graceful drain timeout for gateway stop/restart (seconds).
        # The gateway stops accepting new work, waits for running agents
        # to finish, then interrupts any remaining runs after the timeout.
        # 0 = no drain, interrupt immediately.
        #
        # 180s is calibrated for realistic in-flight agent turns: a typical
        # coding conversation mid-reasoning runs 60–150s per call, so a 60s
        # budget routinely interrupted legitimate work on /restart. Raise
        # further in config.yaml if you run very-long-reasoning models.
        "restart_drain_timeout": 180,
        # Max app-level retry attempts for API errors (connection drops,
        # provider timeouts, 5xx, etc.) before the agent surfaces the
        # failure.  The OpenAI SDK already does its own low-level retries
        # (max_retries=2 default) for transient network errors; this is
        # the Hermes-level retry loop that wraps the whole call.  Lower
        # this to 1 if you use fallback providers and want fast failover
        # on flaky primaries; raise it if you prefer to tolerate longer
        # provider hiccups on a single provider.
        "api_max_retries": 3,
        "service_tier": "",
        # Codex/OpenAI reasoning summary verbosity for the visible reasoning
        # display (Responses API ``reasoning.summary``). "detailed" (default)
        # returns the FULLER, readable prose summary; "concise" is shorter;
        # "auto" returns the compressed, note-form ("caveman") summary OpenAI
        # picks on its own. Tradeoff: "detailed" summaries are longer, so they
        # consume more reasoning tokens. Only affects codex_responses models
        # (gpt-5.x / ChatGPT-OAuth); grok and other backends ignore it.
        "reasoning_summary": "detailed",
        # Tool-use enforcement: injects system prompt guidance that tells the
        # model to actually call tools instead of describing intended actions.
        # Values: "auto" (default — applies to gpt/codex models), true/false
        # (force on/off for all models), or a list of model-name substrings
        # to match (e.g. ["gpt", "codex", "gemini", "qwen"]).
        "tool_use_enforcement": "auto",
        # Staged inactivity warning: send a warning to the user at this
        # threshold before escalating to a full timeout.  The warning fires
        # once per run and does not interrupt the agent.  0 = disable warning.
        "gateway_timeout_warning": 900,
        # Maximum time (seconds) the gateway will block an agent waiting for
        # a clarify-tool response from the user.  Hit this and the agent
        # unblocks with "[user did not respond within Xm]" so it can adapt
        # rather than pinning the running-agent guard forever.  CLI clarify
        # blocks indefinitely (input() is synchronous) and ignores this.
        "clarify_timeout": 600,
        # Periodic "still working" notification interval (seconds).
        # Sends a status message every N seconds so the user knows the
        # agent hasn't died during long tasks.  0 = disable notifications.
        # Lower values mean faster feedback on slow tasks but more chat
        # noise; 180s is a compromise that catches spinning weak-model runs
        # (60+ tool iterations with tiny output) before users assume the
        # bot is dead and /restart.
        "gateway_notify_interval": 180,
        # Freshness window for the gateway auto-continue note (seconds).
        # After a gateway crash/restart/SIGTERM mid-run, the next user
        # message gets a "[System note: your previous turn was
        # interrupted — process the unfinished tool result(s) first]"
        # prepended so the model picks up where it left off.  That's the
        # right behaviour while the interruption is fresh, but stale
        # markers (transcript last touched hours or days ago) can revive
        # an unrelated old task when the user's next message starts new
        # work.  This window is the max age of the last persisted
        # transcript row for which we still inject the continue note.
        # Default 3600s comfortably covers a long turn (gateway_timeout
        # default is 1800s) plus runtime slack.  Set to 0 to disable the
        # gate and restore pre-fix behaviour (always inject).
        "gateway_auto_continue_freshness": 3600,
        # How user-attached images are presented to the main model on each turn.
        #   "auto"   — attach natively when the active model reports
        #              supports_vision=True AND the user hasn't explicitly
        #              configured auxiliary.vision.provider.  Otherwise fall
        #              back to text (vision_analyze pre-analysis).
        #   "native" — always attach natively; non-vision models will either
        #              error at the provider or get a last-chance text fallback
        #              (see run_agent._prepare_messages_for_api).
        #   "text"   — always pre-analyze with vision_analyze and prepend the
        #              description as text; the main model never sees pixels.
        # Affects gateway platforms, the TUI, and CLI /attach.  vision_analyze
        # remains available as a tool regardless of this setting — the routing
        # only controls how inbound user images are presented.
        "image_input_mode": "auto",
        "disabled_toolsets": [],
    },
    "terminal": {
        "backend": "local",
        "modal_mode": "auto",
        "cwd": ".",  # Use current directory
        "timeout": 180,
        # Environment variables to pass through to sandboxed execution
        # (terminal and execute_code).  Skill-declared required_environment_variables
        # are passed through automatically; this list is for non-skill use cases.
        "env_passthrough": [],
        # Extra files to source in the login shell when building the
        # per-session environment snapshot.  Use this when tools like nvm,
        # pyenv, asdf, or custom PATH entries are registered by files that
        # a bash login shell would skip — most commonly ``~/.bashrc``
        # (bash doesn't source bashrc in non-interactive login mode) or
        # zsh-specific files like ``~/.zshrc`` / ``~/.zprofile``.
        # Paths support ``~`` / ``${VAR}``. Missing files are silently
        # skipped. When empty, Superforecasting Agent auto-sources ``~/.profile``,
        # ``~/.bash_profile``, and ``~/.bashrc`` (in that order) if the
        # snapshot shell is bash (this is the ``auto_source_bashrc``
        # behaviour — disable with that key if you want strict login-only
        # semantics).
        "shell_init_files": [],
        # When true (default), Superforecasting Agent sources the user's shell rc files
        # (``~/.profile``, ``~/.bash_profile``, ``~/.bashrc``) in the
        # login shell used to build the environment snapshot. This
        # captures PATH additions, shell functions, and aliases — which a
        # plain ``bash -l -c`` would otherwise miss because bash skips
        # bashrc in non-interactive login mode, and because a default
        # Debian/Ubuntu ``~/.bashrc`` short-circuits on non-interactive
        # sources. ``~/.profile`` and ``~/.bash_profile`` are tried first
        # because ``n`` / ``nvm`` / ``asdf`` installers typically write
        # their PATH exports there without an interactivity guard. Turn
        # this off if your rc files misbehave when sourced
        # non-interactively (e.g. one that hard-exits on TTY checks).
        "auto_source_bashrc": True,
        "docker_image": "nikolaik/python-nodejs:python3.11-nodejs20",
        "docker_forward_env": [],
        # Explicit environment variables to set inside Docker containers.
        # Unlike docker_forward_env (which reads values from the host process),
        # docker_env lets you specify exact key-value pairs — useful when the
        # agent runs as a systemd service without access to the user's shell
        # environment.
        # Example: {"SSH_AUTH_SOCK": "/run/user/1000/ssh-agent.sock"}
        "docker_env": {},
        "singularity_image": "docker://nikolaik/python-nodejs:python3.11-nodejs20",
        "modal_image": "nikolaik/python-nodejs:python3.11-nodejs20",
        "daytona_image": "nikolaik/python-nodejs:python3.11-nodejs20",
        "vercel_runtime": "node24",
        # Container resource limits (docker, singularity, modal, daytona, vercel_sandbox — ignored for local/ssh)
        "container_cpu": 1,
        "container_memory": 5120,  # MB (default 5GB)
        "container_disk": 51200,  # MB (default 50GB)
        "container_persistent": True,  # Persist filesystem across sessions
        # Docker volume mounts — share host directories with the container.
        # Each entry is "host_path:container_path" (standard Docker -v syntax).
        # Example:
        # ["/home/user/projects:/workspace/projects",
        #  "/home/user/.hermes/cache/documents:/output"]
        # For gateway MEDIA delivery, write inside Docker to /output/... and emit
        # the host-visible path in MEDIA:, not the container path.
        "docker_volumes": [],
        # Explicit opt-in: mount the host cwd into /workspace for Docker sessions.
        # Default off because passing host directories into a sandbox weakens isolation.
        "docker_mount_cwd_to_workspace": False,
        "docker_extra_args": [],  # Extra flags passed verbatim to docker run
        # Explicit opt-in: run the Docker container as the host user's uid:gid
        # (via `--user`).  When enabled, files written into bind-mounted dirs
        # (docker_volumes, the persistent workspace, or the auto-mounted cwd)
        # are owned by your host user instead of root, which avoids needing
        # `sudo chown` after container runs. Default off to preserve behavior
        # for images whose entrypoints expect to start as root (e.g. the
        # bundled Hermes image, which drops to the `hermes` user via gosu).
        # When on, SETUID/SETGID caps are omitted from the container since
        # no privilege drop is needed.
        "docker_run_as_host_user": False,
        # Persistent shell — keep a long-lived bash shell across execute() calls
        # so cwd/env vars/shell variables survive between commands.
        # Enabled by default for non-local backends (SSH); local is always opt-in
        # via TERMINAL_LOCAL_PERSISTENT env var.
        "persistent_shell": True,
    },
    "web": {
        "backend": "",  # shared fallback — applies to both search and extract
        "search_backend": "",  # per-capability override for web_search (e.g. "searxng")
        "extract_backend": "",  # per-capability override for web_extract (e.g. "native")
        "extract_char_limit": 15000,  # per-page char budget for web_extract; larger pages truncate + store full text in cache/web
    },
    "browser": {
        "inactivity_timeout": 120,
        "command_timeout": 30,  # Timeout for browser commands in seconds (screenshot, navigate, etc.)
        "record_sessions": False,  # Auto-record browser sessions as WebM videos
        "allow_private_urls": False,  # Allow navigating to private/internal IPs (localhost, 192.168.x.x, etc.)
        # Browser engine for local mode.  Passed as ``--engine <value>`` to
        # agent-browser v0.25.3+.
        # "auto"       — use Chrome (default, don't pass --engine at all)
        # "lightpanda" — use Lightpanda (1.3-5.8x faster navigation, no screenshots)
        # "chrome"     — explicitly request Chrome
        # Also settable via AGENT_BROWSER_ENGINE env var.
        "engine": "auto",
        "auto_local_for_private_urls": True,  # When a cloud provider is set, auto-spawn local Chromium for LAN/localhost URLs instead of sending them to the cloud
        "cdp_url": "",  # Optional persistent CDP endpoint for attaching to an existing Chromium/Chrome
        # CDP supervisor — dialog + frame detection via a persistent WebSocket.
        # Active only when a CDP-capable backend is attached (Browserbase or
        # local Chrome via /browser connect). See
        # website/docs/developer-guide/browser-supervisor.md.
        "dialog_policy": "must_respond",  # must_respond | auto_dismiss | auto_accept
        "dialog_timeout_s": 300,  # Safety auto-dismiss after N seconds under must_respond
        "camofox": {
            # When true, the agent sends a stable profile-scoped userId to Camofox
            # so the server maps it to a persistent Firefox profile automatically.
            # When false (default), each session gets a random userId (ephemeral).
            "managed_persistence": False,
            # Optional externally managed Camofox identity. Useful when another
            # app owns the visible browser and Superforecasting Agent should operate in it.
            "user_id": "",
            "session_key": "",
            # Rehydrate tab_id from Camofox before creating a new tab.
            "adopt_existing_tab": False,
        },
    },
    # Filesystem checkpoints — automatic snapshots before destructive file ops.
    # When enabled, the agent takes a snapshot of the working directory once
    # per forecast-support turn (on first write_file/patch call).  Use /rollback
    # to restore.
    #
    # Defaults changed in v2 (single shared shadow store, real pruning):
    #   - enabled: True -> False   (opt-in; most users never use /rollback)
    #   - max_snapshots: 50 -> 20  (now actually enforced via ref rewrite)
    #   - auto_prune:   False -> True (orphans/stale pruned automatically)
    # Opt in via ``superforecasting-agent desk --checkpoints`` or set enabled=True here.
    "checkpoints": {
        "enabled": False,
        # Max checkpoints to keep per working directory.  Pre-v2 this only
        # limited the `/rollback` listing; v2 actually rewrites the ref and
        # garbage-collects older commits.
        "max_snapshots": 20,
        # Hard ceiling on total active agent-home ``checkpoints/`` size (MB). When
        # exceeded, the oldest checkpoint per project is dropped in a
        # round-robin pass until total size falls under the cap.
        # 0 disables the size cap.
        "max_total_size_mb": 500,
        # Skip any single file larger than this when staging a checkpoint.
        # Prevents accidental snapshotting of datasets, model weights, and
        # other large generated assets.  0 disables the filter.
        "max_file_size_mb": 10,
        # Auto-maintenance: hermes sweeps the checkpoint base at startup
        # (at most once per ``min_interval_hours``) and:
        #   * deletes project entries whose workdir no longer exists (orphan)
        #   * deletes project entries whose last_touch is older than
        #     ``retention_days``
        #   * GCs the single shared store to reclaim unreachable objects
        #   * enforces ``max_total_size_mb`` across remaining projects
        #   * deletes ``legacy-*`` archives older than ``retention_days``
        "auto_prune": True,
        "retention_days": 7,
        "delete_orphans": True,
        "min_interval_hours": 24,
    },
    # Maximum characters returned by a single read_file call.  Reads that
    # exceed this are rejected with guidance to use offset+limit.
    # 100K chars ≈ 25–35K tokens across typical tokenisers.
    "file_read_max_chars": 100_000,
    # Tool-output truncation thresholds. When terminal output or a
    # single read_file page exceeds these limits, Hermes truncates the
    # payload sent to the model (keeping head + tail for terminal,
    # enforcing pagination for read_file). Tuning these trades context
    # footprint against how much raw output the model can see in one
    # shot. Ported from anomalyco/opencode PR #23770.
    #
    # - max_bytes:       terminal_tool output cap, in chars
    #                    (default 50_000 ≈ 12-15K tokens).
    # - max_lines:       read_file pagination cap — the maximum `limit`
    #                    a single read_file call can request before
    #                    being clamped (default 2000).
    # - max_line_length: per-line cap applied when read_file emits a
    #                    line-numbered view (default 2000 chars).
    "tool_output": {
        "max_bytes": 50_000,
        "max_lines": 2000,
        "max_line_length": 2000,
    },
    # Tool loop guardrails nudge models when they repeat failed or
    # non-progressing tool calls. Soft warnings are always-on by default;
    # hard stops are opt-in so interactive CLI/TUI sessions keep flowing.
    "tool_loop_guardrails": {
        "warnings_enabled": True,
        "hard_stop_enabled": False,
        "warn_after": {
            "exact_failure": 2,
            "same_tool_failure": 3,
            "idempotent_no_progress": 2,
        },
        "hard_stop_after": {
            "exact_failure": 5,
            "same_tool_failure": 8,
            "idempotent_no_progress": 5,
        },
    },
    "compression": {
        "enabled": True,
        "threshold": 0.50,  # compress when context usage exceeds this ratio
        "target_ratio": 0.20,  # fraction of threshold to preserve as recent tail
        "protect_last_n": 20,  # minimum recent messages to keep uncompressed
        "hygiene_hard_message_limit": 400,  # gateway session-hygiene force-compress threshold by message count
        "protect_first_n": 3,  # non-system head messages always preserved
        # verbatim, in ADDITION to the system prompt
        # (which is always implicitly protected). Set to
        # 0 for long-running rolling-compaction sessions
        # where you want nothing pinned except the
        # system prompt + rolling summary + recent tail.
        "abort_on_summary_failure": False,  # When True, auto-compression that fails
        # to generate a summary (aux LLM errored / returned
        # non-JSON / timed out) aborts entirely instead of
        # dropping the middle window with a static
        # "summary unavailable" placeholder.  Messages are
        # preserved unchanged and the session "freezes" at
        # its current size until the user runs /compress
        # (which bypasses the failure cooldown) or /new.
        # Default False matches historical behavior; set to
        # True if you'd rather pause than silently lose
        # context turns when your aux model is flaky.
    },
    # Anthropic prompt caching (Claude via OpenRouter or native Anthropic API).
    # cache_ttl must be "5m" or "1h" (Anthropic-supported tiers); other values are ignored.
    "prompt_caching": {
        "cache_ttl": "5m",
    },
    # OpenRouter-specific settings.
    # response_cache: enable OpenRouter response caching (X-OpenRouter-Cache header).
    #   When enabled, identical requests return cached responses for free (zero billing).
    #   This is separate from Anthropic prompt caching and works alongside it.
    #   See: https://openrouter.ai/docs/guides/features/response-caching
    # response_cache_ttl: how long cached responses remain valid, in seconds (1-86400).
    #   Default 300 (5 minutes). Only used when response_cache is enabled.
    # min_coding_score: knob for the openrouter/pareto-code router (0.0-1.0).
    #   Only applied when model.model is "openrouter/pareto-code". Higher
    #   values route to stronger (more expensive) coders; lower values open
    #   up cheaper, faster options. Default 0.65 lands on the mid-tier
    #   coder on the current Pareto frontier. Empty string = let OpenRouter
    #   pick the strongest available coder (router's documented default
    #   when the plugins block is omitted).
    #   See: https://openrouter.ai/docs/guides/routing/routers/pareto-router
    "openrouter": {
        "response_cache": True,
        "response_cache_ttl": 300,
        "min_coding_score": 0.65,
    },
    # AWS Bedrock provider configuration.
    # Only used when model.provider is "bedrock".
    "bedrock": {
        "region": "",  # AWS region for Bedrock API calls (empty = AWS_REGION env var → us-east-1)
        "discovery": {
            "enabled": True,  # Auto-discover models via ListFoundationModels
            "provider_filter": [],  # Only show models from these providers (e.g. ["anthropic", "amazon"])
            "refresh_interval": 3600,  # Cache discovery results for this many seconds
        },
        "guardrail": {
            # Amazon Bedrock Guardrails — content filtering and safety policies.
            # Create a guardrail in the Bedrock console, then set the ID and version here.
            # See: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html
            "guardrail_identifier": "",  # e.g. "abc123def456"
            "guardrail_version": "",  # e.g. "1" or "DRAFT"
            "stream_processing_mode": "async",  # "sync" or "async"
            "trace": "disabled",  # "enabled", "disabled", or "enabled_full"
        },
    },
    # Auxiliary model config — provider:model for each side task.
    # Format: provider is the provider name, model is the model slug.
    # "auto" for provider = auto-detect best available provider.
    # Empty model = use provider's default auxiliary model.
    # All tasks fall back to openrouter:google/gemini-3-flash-preview if
    # the configured provider is unavailable.
    #
    # extra_body: forwarded verbatim as request body fields on every aux call
    # for that task. Use this to set provider-specific knobs (independent of
    # main-agent settings). On OpenRouter you can set provider routing prefs
    # and the Pareto Code coding-score floor here. Example:
    #
    #   auxiliary:
    #     compression:
    #       provider: openrouter
    #       model: openrouter/pareto-code
    #       extra_body:
    #         provider:           # OpenRouter provider routing
    #           order: [anthropic, google]
    #           sort: throughput  # or price | latency
    #         plugins:            # OpenRouter Pareto Code router
    #           - id: pareto-router
    #             min_coding_score: 0.5
    #
    # Each aux task is independent — main-agent provider_routing and
    # openrouter.min_coding_score do NOT propagate to aux calls by design.
    "auxiliary": {
        "vision": {
            "provider": "auto",  # auto | openrouter | nous | codex | custom
            "model": "",  # e.g. "google/gemini-2.5-flash", "gpt-4o"
            "base_url": "",  # direct OpenAI-compatible endpoint (takes precedence over provider)
            "api_key": "",  # API key for base_url (falls back to OPENAI_API_KEY)
            "timeout": 120,  # seconds — LLM API call timeout; vision payloads need generous timeout
            "extra_body": {},  # OpenAI-compatible provider-specific request fields
            "download_timeout": 30,  # seconds — image HTTP download timeout; increase for slow connections
        },
        "web_extract": {
            "provider": "auto",
            "model": "",
            "base_url": "",
            "api_key": "",
            "timeout": 360,  # seconds (6min) — per-attempt LLM summarization timeout; increase for slow local models
            "extra_body": {},
        },
        "compression": {
            "provider": "auto",
            "model": "",
            "base_url": "",
            "api_key": "",
            "timeout": 120,  # seconds — compression summarises large contexts; increase for local models
            "extra_body": {},
        },
        # Note: session_search no longer uses an auxiliary LLM (PR #27590 —
        # single-shape tool returns DB content directly). The old
        # ``auxiliary.session_search.*`` block was removed here. Existing
        # values in user config.yaml files are harmless leftovers and ignored.
        "skills_hub": {
            "provider": "auto",
            "model": "",
            "base_url": "",
            "api_key": "",
            "timeout": 30,
            "extra_body": {},
        },
        "approval": {
            "provider": "auto",
            "model": "",  # fast/cheap model recommended (e.g. gemini-flash, haiku)
            "base_url": "",
            "api_key": "",
            "timeout": 30,
            "extra_body": {},
        },
        "mcp": {
            "provider": "auto",
            "model": "",
            "base_url": "",
            "api_key": "",
            "timeout": 30,
            "extra_body": {},
        },
        "title_generation": {
            "provider": "auto",
            "model": "",
            "base_url": "",
            "api_key": "",
            "timeout": 30,
            "extra_body": {},
        },
        # Gemini TTS expressive audio-tag rewrite (tts.gemini.audio_tags). Picks the
        # model that inserts [whispers]/[excitedly]/... into the spoken script. "auto"
        # uses the detected default; set a cheap capable model. Absent block => "auto".
        "tts_audio_tags": {
            "provider": "auto",
            "model": "",
            "base_url": "",
            "api_key": "",
            "timeout": 30,
            "extra_body": {},
        },
        # Triage specifier — flesh out a rough one-liner in the Kanban
        # Triage column into a concrete spec, then promote it to ``todo``.
        # Invoked by ``superforecasting-agent kanban specify`` (single id or --all). Set a
        # cheap, capable model here (gemini-flash works well); the main
        # model is overkill for short spec expansion.
        "triage_specifier": {
            "provider": "auto",
            "model": "",
            "base_url": "",
            "api_key": "",
            "timeout": 120,
            "extra_body": {},
        },
        # Kanban decomposer — decomposes a triage task into a graph of
        # child tasks routed to specialist profiles by description.
        # Invoked by ``superforecasting-agent kanban decompose`` and the kanban
        # auto-decompose dispatcher tick. Returns a JSON task graph;
        # uses more tokens than the specifier so allow more headroom.
        "kanban_decomposer": {
            "provider": "auto",
            "model": "",
            "base_url": "",
            "api_key": "",
            "timeout": 180,
            "extra_body": {},
        },
        # Profile describer — auto-generates a 1-2 sentence description
        # of what a profile is good at. Invoked by
        # ``hermes profile describe <name> --auto`` and the dashboard's
        # auto-generate button. Short, cheap call.
        "profile_describer": {
            "provider": "auto",
            "model": "",
            "base_url": "",
            "api_key": "",
            "timeout": 60,
            "extra_body": {},
        },
        # Curator — skill-usage review fork. Timeout is generous because the
        # review pass can take several minutes on reasoning models (umbrella
        # building over hundreds of candidate skills). "auto" = use main chat
        # model; override via `superforecasting-agent model` → auxiliary →
        # Curator to route to a cheaper aux model (e.g. openrouter
        # google/gemini-3-flash-preview).
        "curator": {
            "provider": "auto",
            "model": "",
            "base_url": "",
            "api_key": "",
            "timeout": 600,
            "extra_body": {},
        },
    },
    "display": {
        "compact": False,
        "personality": "neutral",
        "resume_display": "full",
        "busy_input_mode": "interrupt",  # interrupt | queue | steer
        # When true, the TUI auto-resumes the most recent human-facing
        # forecast session on launch instead of forging a fresh one.
        # Mirrors `superforecasting-agent -c` muscle memory.  Default off
        # so existing users aren't surprised. TUI_RESUME env aliases win.
        "tui_auto_resume_recent": False,
        "bell_on_complete": False,
        "show_reasoning": False,
        "streaming": False,
        "timestamps": False,  # Show [HH:MM] on user and assistant labels
        "final_response_markdown": "strip",  # render | strip | raw
        # Preserve recent classic CLI output across Ctrl+L, /redraw, and
        # terminal resize full-screen clears. Disable if a terminal emulator
        # behaves badly with replayed scrollback.
        "persistent_output": True,
        "persistent_output_max_lines": 200,
        "inline_diffs": True,  # Show inline diff previews for write actions (write_file, patch, skill_manage)
        # File-mutation verifier footer.  When true (default), the agent
        # appends a one-line advisory to its final response whenever a
        # write_file / patch call failed during the turn and was never
        # superseded by a successful write to the same path.  This catches
        # the "batch of parallel patches, half fail, model claims success"
        # class of over-claim that otherwise forces users to run
        # `git status` to verify edits landed.  Set false to suppress.
        "file_mutation_verifier": True,
        "show_cost": False,  # Show $ cost in the status bar (off by default)
        "skin": "forecast",
        # UI language for static user-facing messages (approval prompts, a
        # handful of gateway slash-command replies).  Does NOT affect agent
        # responses, log lines, tool outputs, or slash-command descriptions.
        # Supported: en, zh, ja, de, es, fr, tr, uk.  Unknown values fall back to en.
        "language": "en",
        # TUI busy indicator style: unicode (default), markers, emoji, or
        # ascii. Live-swappable via `/indicator <style>`.
        "tui_status_indicator": "unicode",
        "user_message_preview": {  # CLI: how many submitted user-message lines to echo back in scrollback
            "first_lines": 2,
            "last_lines": 2,
        },
        "interim_assistant_messages": True,  # Gateway: show natural mid-turn assistant status messages
        "tool_progress_command": False,  # Enable /verbose command in messaging gateway
        "tool_progress_overrides": {},  # DEPRECATED — use display.platforms instead
        "tool_preview_length": 0,  # Max chars for tool call previews (0 = no limit, show full paths/commands)
        # Auto-delete system-notice replies (e.g. "New forecast session started!",
        # "♻ Restarting gateway…", "⚡ Stopped…") after N seconds on platforms
        # that support message deletion (currently Telegram; other platforms
        # ignore and leave the message in place).  Only affects slash-command
        # replies wrapped with gateway.platforms.base.EphemeralReply — agent
        # responses and content messages are never touched.  Default 0
        # (disabled) preserves prior behavior.
        "ephemeral_system_ttl": 0,
        "platforms": {},  # Per-platform display overrides: {"telegram": {"tool_progress": "all"}, "slack": {"tool_progress": "off"}}
        # Gateway runtime-metadata footer appended to the FINAL message of a turn
        # (disabled by default to keep replies minimal). When enabled, renders
        # e.g. `model · 68% · ~/projects/hermes`. Per-platform overrides go under
        # display.platforms.<platform>.runtime_footer.
        "runtime_footer": {
            "enabled": False,
            "fields": ["model", "context_pct", "cwd"],  # Order shown; drop any to hide
        },
        "copy_shortcut": "auto",  # "auto" (platform default) | "ctrl_c" | "ctrl_shift_c" | "disabled"
    },
    # Web dashboard settings
    "dashboard": {
        "theme": "default",  # Dashboard visual theme: "default", "midnight", "ember", "mono", "cyberpunk", "rose"
        # Hide the token/cost analytics surfaces (Analytics page, token bars and
        # cost figures on the Models page) by default.  The numbers shown there
        # are a local debug estimate: they only count successful main-agent
        # responses with a usable ``response.usage``, and silently exclude every
        # auxiliary call (context compression, title generation, vision,
        # session search, web extract, smart approval, MCP routing, plugin LLM
        # access) plus provider-side retries, fallback attempts, and any call
        # whose usage block didn't come back.  Cache writes are also missing
        # from the API response.  On models with heavy auxiliary traffic
        # (Kimi K2.6, MiniMax M2.7) the local total can be 10x-100x lower than
        # the provider bill, which is worse than hiding the numbers entirely
        # because they look precise enough to compare against the provider.
        # Set this to True to re-enable the surfaces with the understanding
        # that the numbers are a local lower-bound estimate, not billing.
        "show_token_analytics": False,
    },
    # Privacy settings
    "privacy": {
        "redact_pii": False,  # When True, hash user IDs and strip phone numbers from LLM context
    },
    # Text-to-speech configuration
    # Each provider supports an optional `max_text_length:` override for the
    # per-request input-character cap. Omit it to use the provider's documented
    # limit (OpenAI 4096, xAI 15000, MiniMax 10000, ElevenLabs 5k-40k model-aware,
    # Gemini 5000, Edge 5000, Mistral 4000, NeuTTS/KittenTTS 2000).
    "tts": {
        "provider": "kokoro",  # local-first default; falls back to Edge until kokoro-onnx is installed. Options: "edge" (free cloud) | "elevenlabs" | "openai" | "xai" | "minimax" | "mistral" | "gemini" | "kokoro" (local, recommended) | "neutts" (local) | "kittentts" (local) | "piper" (local)
        "edge": {
            "voice": "en-US-AriaNeural",
            # Popular: AriaNeural, JennyNeural, AndrewNeural, BrianNeural, SoniaNeural
        },
        "elevenlabs": {
            "voice_id": "pNInz6obpgDQGcFmaJgB",  # Adam
            "model_id": "eleven_multilingual_v2",
        },
        "openai": {
            "model": "gpt-4o-mini-tts",
            "voice": "alloy",
            # Voices: alloy, echo, fable, onyx, nova, shimmer
        },
        "xai": {
            "voice_id": "eve",  # or custom voice ID — see https://docs.x.ai/developers/model-capabilities/audio/custom-voices
            "language": "en",
            "sample_rate": 24000,
            "bit_rate": 128000,
        },
        "mistral": {
            "model": "voxtral-mini-tts-2603",
            "voice_id": "c69964a6-ab8b-4f8a-9465-ec0925096ec8",  # Paul - Neutral
        },
        "neutts": {
            "ref_audio": "",  # Path to reference voice audio (empty = bundled default)
            "ref_text": "",  # Path to reference voice transcript (empty = bundled default)
            "model": "neuphonic/neutts-air-q4-gguf",  # HuggingFace model repo
            "device": "cpu",  # cpu, cuda, or mps
        },
        "piper": {
            # Voice name (e.g. "en_US-lessac-medium") downloaded on first
            # use, OR an absolute path to a pre-downloaded .onnx file.
            # Full voice list: https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/VOICES.md
            "voice": "en_US-lessac-medium",
            # "voices_dir": "",        # Override voice cache dir; default = active agent-home cache/piper-voices/
            # "use_cuda": False,       # Requires onnxruntime-gpu
            # "length_scale": 1.0,     # 2.0 = twice as slow
            # "noise_scale": 0.667,
            # "noise_w_scale": 0.8,
            # "volume": 1.0,
            # "normalize_audio": True,
        },
        "gemini": {
            "model": "gemini-2.5-flash-preview-tts",
            "voice": "Kore",  # 30 prebuilt voices; e.g. Kore, Puck, Charon, Aoede
            # Optional local markdown file of performance direction (AUDIO PROFILE /
            # SCENE / DIRECTOR'S NOTES) that shapes how the voice performs. A
            # {transcript} placeholder is substituted; otherwise it's appended under a
            # heading. Empty = plain transcript (default, no-op). Needs GEMINI_API_KEY.
            "persona_prompt_file": "",
            # Expressive audio-tag rewrite ([whispers] / [excitedly] / ...). Only effective
            # on gemini-3.1*-tts models and needs an auxiliary model (auxiliary.tts_audio_tags).
            # False = off (default); the visible chat text is never changed.
            "audio_tags": False,
        },
        "kokoro": {
            # Kokoro-82M — high-quality LOCAL/offline TTS (Apache-2.0), far more natural
            # than Piper, CPU-only, no torch + no system espeak-ng. The model + voices
            # auto-download on first use to <agent home>/cache/kokoro/.
            # Install once: pip install kokoro-onnx
            "model": "kokoro-v1.0.int8.onnx",  # ~92MB; "kokoro-v1.0.onnx" (~325MB) = max fidelity
            "voice": "af_heart",  # see hexgrad/Kokoro-82M VOICES.md (af_bella, am_michael, bf_emma, ...)
            "speed": 1.0,
            "lang": "en-us",
            # "model_dir": "",  # override the cache dir for the .onnx + voices.bin
        },
    },
    "stt": {
        "enabled": True,
        "provider": "local",  # "local" (free, faster-whisper) | "groq" | "openai" (Whisper API) | "mistral" (Voxtral Transcribe)
        "local": {
            "model": "base",  # tiny, base, small, medium, large-v3
            "language": "",  # auto-detect by default; set to "en", "es", "fr", etc. to force
        },
        "openai": {
            "model": "whisper-1",  # whisper-1, gpt-4o-mini-transcribe, gpt-4o-transcribe
        },
        "mistral": {
            "model": "voxtral-mini-latest",  # voxtral-mini-latest, voxtral-mini-2602
        },
    },
    "voice": {
        "record_key": "ctrl+b",
        "max_recording_seconds": 120,
        "auto_tts": False,
        "beep_enabled": True,  # Play record start/stop beeps in CLI voice mode
        "silence_threshold": 200,  # RMS below this = silence (0-32767)
        "silence_duration": 3.0,  # Seconds of silence before auto-stop
    },
    "human_delay": {
        "mode": "off",
        "min_ms": 800,
        "max_ms": 2500,
    },
    # Context engine -- controls how the context window is managed when
    # approaching the model's token limit.
    # "compressor" = built-in lossy summarization (default).
    # Set to a plugin name to activate an alternative engine (e.g. "lcm"
    # for Lossless Context Management).  The engine must be installed as
    # a plugin in plugins/context_engine/<name>/ or the active agent-home
    # plugins/ directory.
    "context": {
        "engine": "compressor",
    },
    # Generic assistant memory -- bounded curated memory injected into the
    # system prompt. The forecasting fork learns through the forecast ledger,
    # score records, postmortems, calibration lessons, and domain error
    # profiles by default; enable this only for profiles that need inherited
    # free-form chat recall outside the ledger.
    "memory": {
        "memory_enabled": False,
        "user_profile_enabled": False,
        "memory_char_limit": 2200,  # ~800 tokens at 2.75 chars/token
        "user_char_limit": 1375,  # ~500 tokens at 2.75 chars/token
        # External memory provider plugin (empty = built-in only).
        # Set to a provider name to activate: "openviking", "mem0",
        # "hindsight", "holographic", "retaindb", "byterover".
        # Only ONE external provider is allowed at a time.
        "provider": "",
    },
    # Subagent delegation — override the provider:model used by delegate_task
    # so child agents can run on a different (cheaper/faster) provider and model.
    # Uses the same runtime provider resolution as CLI/gateway startup, so all
    # configured providers (OpenRouter, Nous, Z.ai, Kimi, etc.) are supported.
    "delegation": {
        "model": "",  # e.g. "google/gemini-3-flash-preview" (empty = inherit parent model)
        "provider": "",  # e.g. "openrouter" (empty = inherit parent provider + credentials)
        "base_url": "",  # direct OpenAI-compatible endpoint for subagents
        "api_key": "",  # API key for delegation.base_url (falls back to OPENAI_API_KEY)
        "api_mode": "",  # wire protocol for delegation.base_url: "chat_completions",
        # "codex_responses", or "anthropic_messages". Empty = auto-detect
        # from URL (e.g. /anthropic suffix → anthropic_messages). Set this
        # explicitly for non-standard endpoints the heuristic can't detect.
        # When delegate_task narrows child toolsets explicitly, preserve any
        # MCP toolsets the parent already has enabled. On by default so
        # narrowing (e.g. toolsets=["web","browser"]) expresses "I want these
        # extras" without silently stripping MCP tools the parent already has.
        # Set to false for strict intersection.
        "inherit_mcp_toolsets": True,
        "max_iterations": 50,  # per-subagent iteration cap (each subagent gets its own budget,
        # independent of the parent's max_iterations)
        # Subagent summaries return to the parent's context verbatim. A batch
        # fan-out (N children) returns N summaries at once, which can exceed
        # the parent's context window and trigger a compression/429 death
        # spiral. delegate_task sizes each summary against the parent's
        # remaining context headroom (split across the batch); when it must
        # trim, the full text is spilled to the agent home's cache/delegation/
        # (mounted into remote backends) and the in-context summary becomes a
        # head+tail window plus a footer with the exact read_file offset to
        # page the omitted middle — the same convention web_extract uses for
        # large pages. Nothing is lost. The SAME trim is applied to async
        # (background=true) delegations when their result re-enters the
        # conversation. max_summary_chars is a hard per-summary character
        # ceiling layered on top of that dynamic budget (belt-and-suspenders
        # for models that ignore the "be concise" instruction). 0 disables the
        # hard ceiling; the dynamic headroom budget still applies.
        "max_summary_chars": 24000,
        "child_timeout_seconds": 600,  # wall-clock timeout for each child agent (floor 30s,
        # no ceiling). High-reasoning models on large tasks
        # (e.g. gpt-5.5 xhigh, opus-4.6) need generous budgets;
        # raise if children time out before producing output.
        "reasoning_effort": "",  # reasoning effort for subagents: "xhigh", "high", "medium",
        # "low", "minimal", "none" (empty = inherit parent's level)
        "max_concurrent_children": 3,  # max parallel children per batch; floor of 1 enforced, no ceiling
        "max_async_children": 3,  # max concurrent delegate_task(background=true) subagents; new
        # dispatches are REJECTED at capacity (not queued). Floor of 1,
        # no ceiling. Env override: DELEGATION_MAX_ASYNC_CHILDREN.
        # Orchestrator role controls (see tools/delegate_tool.py:_get_max_spawn_depth
        # and _get_orchestrator_enabled).  Values are clamped to [1, 3] with a
        # warning log if out of range.
        "max_spawn_depth": 1,  # depth cap (1 = flat [default], 2 = orchestrator→leaf, 3 = three-level)
        "orchestrator_enabled": True,  # kill switch for role="orchestrator"
        # When a subagent hits a dangerous-command approval prompt, the parent's
        # prompt_toolkit TUI owns stdin — a thread-local input() call from the
        # subagent worker would deadlock the parent UI. To avoid the deadlock,
        # subagent threads ALWAYS resolve approvals non-interactively:
        #   false (default) → auto-deny with a logger.warning audit line (safe)
        #   true             → auto-approve "once" with a logger.warning audit line
        # Flip to true only if you trust delegated work to run dangerous cmds
        # without human review (cron pipelines, batch automation, etc.).
        "subagent_auto_approve": False,
    },
    # Ephemeral prefill messages file — JSON list of {role, content} dicts
    # injected at the start of every API call for few-shot priming.
    # Never saved to sessions, logs, or trajectories.
    "prefill_messages_file": "",
    # Goals — persistent cross-turn goals (Ralph-style loop).
    # After every turn, a lightweight judge call asks the auxiliary model
    # whether the active /goal is satisfied by the assistant's last
    # response. If not, Superforecasting Agent feeds a continuation prompt back into the
    # same session and keeps working until the goal is done, the turn
    # budget is exhausted, or the user pauses/clears it. Judge failures
    # fail OPEN (continue) so a flaky judge never wedges progress — the
    # turn budget is the real backstop.
    "goals": {
        # Max continuation turns before Superforecasting Agent auto-pauses the goal and
        # asks the user to /goal resume. Protects against judge false
        # negatives (goal actually done but judge says continue) and
        # unbounded model spend on fuzzy / unachievable goals.
        "max_turns": 20,
    },
    # Skills — external skill directories for sharing skills across tools/agents.
    # Each path is expanded (~, ${VAR}) and resolved.  Read-only — skill creation
    # always goes to the active forecast home's skills/ directory.
    "skills": {
        "external_dirs": [],  # e.g. ["~/.agents/skills", "/shared/team-skills"]
        # Substitute ${HERMES_SKILL_DIR} and ${HERMES_SESSION_ID} in SKILL.md
        # content with the absolute skill directory and the active session id
        # before the agent sees it.  Lets skill authors reference bundled
        # scripts without the agent having to join paths.
        "template_vars": True,
        # Pre-execute inline shell snippets written as !`cmd` in SKILL.md
        # body.  Their stdout is inlined into the skill message before the
        # agent reads it, so skills can inject dynamic context (dates, git
        # state, detected tool versions, …).  Off by default because any
        # content from the skill author runs on the host without approval;
        # only enable for skill sources you trust.
        "inline_shell": False,
        # Timeout (seconds) for each !`cmd` snippet when inline_shell is on.
        "inline_shell_timeout": 10,
        # Run the keyword/pattern security scanner on skills the agent
        # writes via skill_manage (create/edit/patch).  Off by default
        # because the agent can already execute the same code paths via
        # terminal() with no gate, so the scan adds friction (blocks
        # skills that mention risky keywords in prose) without meaningful
        # security.  Turn on if you want the belt-and-suspenders — a
        # dangerous verdict will then surface as a tool error to the
        # agent, which can retry with the flagged content removed.
        # External hub installs (trusted/community sources) are always
        # scanned regardless of this setting.
        "guard_agent_created": False,
    },
    # Ordered, revision-locked organization extensions. Each source may expose
    # plugins/, workflows/, skills/, and prompts/ without forking core.
    "extensions": {
        "sources": [],  # [{"repo": "owner/repo", "ref": "<commit-sha>"}]
    },
    # Multiplayer ledger collaboration. Disabled until a canonical GitHub
    # workspace is linked; all credentials stay in .env / the credential store.
    "collaboration": {
        "enabled": False,
        "github": {
            "enabled": False,
            "api_url": "https://api.github.com",
            "upload_url": "https://uploads.github.com",
            "app_id": "",
            "app_slug": "",
            "client_id": "",
            "public_base_url": "",
            "installation_begin_path": "/api/install/github/begin",
            "installation_callback_path": "/api/install/github/callback",
            "installation_state_ttl_seconds": 600,
            "oauth_callback_path": "/api/oauth/github/callback",
            "oauth_state_ttl_seconds": 600,
            "api_version": "2026-03-10",
            "webhook_path": "/api/webhooks/github",
        },
        "repository": {
            "slug": "",  # owner/repository
            "workspace_id": "",
            "default_branch": "main",
        },
        "review": {
            "materiality_threshold": 0.10,
            "medium_required_humans": 1,
            "high_required_humans": 2,
            "high_requires_owner_or_steward": True,
            "risk_overrides": {},  # {"operation.kind": "low|medium|high"}
        },
        "discussion": {
            "max_comments": 12,
            "max_rounds": 6,
            "max_tokens": 16000,
            "max_elapsed_seconds": 1800,
            "max_concurrent_tasks": 2,
            "agent_loop_threshold": 4,
            "max_comment_bytes": 32768,
        },
        "transcripts": {
            "raw_retention_days": 90,
            "require_publish_consent": True,
            "max_publish_bytes": 262144,
        },
    },
    # Curator — background skill maintenance.
    #
    # Periodically reviews AGENT-CREATED skills (never bundled or
    # hub-installed) and keeps the collection tidy: marks long-unused skills
    # as stale, archives genuinely obsolete ones (archive only, never
    # deletes), and spawns a forked aux-model agent to consolidate overlaps
    # and patch drift. Runs inactivity-triggered from session start — no
    # cron daemon.
    #
    # See `superforecasting-agent curator status` for the last run summary.
    "curator": {
        "enabled": True,
        # How long to wait between curator runs (hours).  Default: 7 days.
        "interval_hours": 24 * 7,
        # Only run when the agent has been idle at least this long (hours).
        "min_idle_hours": 2,
        # Mark a skill as "stale" after this many days without use.
        "stale_after_days": 30,
        # Archive a skill (move to skills/.archive/) after this many days
        # without use. Archived skills are recoverable — no auto-deletion.
        "archive_after_days": 90,
        # Pre-run backup: before every real curator pass (dry-run is
        # skipped), snapshot active agent-home skills/ into
        # skills/.curator_backups/<utc-iso>/skills.tar.gz so the user can roll
        # back with `superforecasting-agent curator rollback`.
        "backup": {
            "enabled": True,
            "keep": 5,  # retain last N regular snapshots
        },
    },
    # Honcho AI-native memory -- reads ~/.honcho/config.json as single source of truth.
    # This section is only needed for hermes-specific overrides; everything else
    # (apiKey, workspace, peerName, sessions, enabled) comes from the global config.
    "honcho": {},
    # IANA timezone (e.g. "Asia/Kolkata", "America/New_York").
    # Empty string means use server-local time.
    "timezone": "",
    # Slack platform settings (gateway mode)
    "slack": {
        "transport": "socket",  # socket | webhook (one ingress per workspace)
        "require_mention": True,  # Require @mention to respond in channels
        "free_response_channels": "",  # Comma-separated channel IDs where bot responds without mention
        "allowed_channels": "",  # If set, bot ONLY responds in these channel IDs (whitelist)
        "channel_prompts": {},  # Per-channel ephemeral system prompts
    },
    # Hosted execution. The gateway/API remains the durable control plane;
    # Kubernetes pods are disposable, conversation-scoped workers.
    "hosted_execution": {
        "runtime": "local",  # local | kubernetes
        "run_store_path": "",  # empty = active forecast home / execution_store.db
        "kubernetes": {
            "namespace": "superforecasting-agent",
            "image": "",  # use a pinned tag or digest in hosted deployments
            "service_account": "superforecasting-agent-sandbox",
            "idle_ttl_seconds": 1800,
            "workspace_size": "8Gi",
            "cpu_request": "250m",
            "cpu_limit": "2",
            "memory_request": "512Mi",
            "memory_limit": "4Gi",
        },
    },
    # Discord platform settings (gateway mode)
    "discord": {
        "require_mention": True,  # Require @mention to respond in server channels
        "free_response_channels": "",  # Comma-separated channel IDs where bot responds without mention
        "allowed_channels": "",  # If set, bot ONLY responds in these channel IDs (whitelist)
        "auto_thread": True,  # Auto-create threads on @mention in channels (like Slack)
        "thread_require_mention": False,  # If True, require @mention in threads too (multi-bot threads)
        "history_backfill": True,  # If True, prepend recent channel scrollback when bot is triggered (recovers messages missed while require_mention gated them out)
        "history_backfill_limit": 50,  # Max number of recent messages to scan when assembling the backfill block
        "reactions": True,  # Add 👀/✅/❌ reactions to messages during processing
        "channel_prompts": {},  # Per-channel ephemeral system prompts (forum parents apply to child threads)
        # Opt-in DM role-based auth (#12136). By default, DISCORD_ALLOWED_ROLES
        # authorizes only guild messages in the role's own guild — DMs require
        # DISCORD_ALLOWED_USERS. Set dm_role_auth_guild to a guild ID to also
        # authorize DMs from members of that one trusted guild holding the
        # allowed role. Unset / empty / 0 = secure default (DM role-auth off).
        "dm_role_auth_guild": "",
        # discord / discord_admin tools: restrict which actions the agent may call.
        # Default (empty) = all actions allowed (subject to bot privileged intents).
        # Accepts comma-separated string ("list_guilds,list_channels,fetch_messages")
        # or YAML list. Unknown names are dropped with a warning at load time.
        # Actions: list_guilds, server_info, list_channels, channel_info,
        # list_roles, member_info, search_members, fetch_messages, list_pins,
        # pin_message, unpin_message, create_thread, add_role, remove_role.
        "server_actions": "",
        # Accept arbitrary attachment file types (not just SUPPORTED_DOCUMENT_TYPES).
        # When True, any uploaded file is cached to disk with mime
        # application/octet-stream and the path is surfaced to the agent so it
        # can use terminal/read_file/etc. against it. Default False preserves
        # the historical allowlist behaviour.
        # Env override: DISCORD_ALLOW_ANY_ATTACHMENT.
        "allow_any_attachment": False,
        # Maximum bytes per attachment the gateway will cache. The whole file
        # is held in memory while being written, so unlimited uploads carry a
        # real memory cost. Default 32 MiB matches the historical hardcoded
        # cap. Set to 0 for no cap. Env override: DISCORD_MAX_ATTACHMENT_BYTES.
        "max_attachment_bytes": 33554432,
    },
    # WhatsApp platform settings (gateway mode)
    "whatsapp": {
        # Reply prefix prepended to every outgoing WhatsApp message.
        # Default (None) uses the built-in Superforecasting Agent header.
        # Set to "" (empty string) to disable the header entirely.
        # Supports \n for newlines, e.g. "🤖 *My Bot*\n──────\n"
    },
    # Telegram platform settings (gateway mode)
    "telegram": {
        "reactions": False,  # Add 👀/✅/❌ reactions to messages during processing
        "channel_prompts": {},  # Per-chat/topic ephemeral system prompts (topics inherit from parent group)
        "allowed_chats": "",  # If set, bot ONLY responds in these group/supergroup chat IDs (whitelist)
    },
    # Mattermost platform settings (gateway mode)
    "mattermost": {
        "require_mention": True,  # Require @mention to respond in channels
        "free_response_channels": "",  # Comma-separated channel IDs where bot responds without mention
        "allowed_channels": "",  # If set, bot ONLY responds in these channel IDs (whitelist)
        "channel_prompts": {},  # Per-channel ephemeral system prompts
    },
    # Matrix platform settings (gateway mode)
    "matrix": {
        "require_mention": True,  # Require @mention to respond in rooms
        "free_response_rooms": "",  # Comma-separated room IDs where bot responds without mention
        "allowed_rooms": "",  # If set, bot ONLY responds in these room IDs (whitelist)
    },
    # Approval mode for dangerous commands:
    #   manual — always prompt the user (default)
    #   smart  — use auxiliary LLM to auto-approve low-risk commands, prompt for high-risk
    #   off    — skip all approval prompts (equivalent to --yolo)
    #
    # cron_mode — what to do when a cron job hits a dangerous command:
    #   deny    — block the command and let the agent find another way (default, safe)
    #   approve — auto-approve all dangerous commands in cron jobs
    "approvals": {
        "mode": "manual",
        "timeout": 60,
        "cron_mode": "deny",
        # When true, /reload-mcp asks the user to confirm before rebuilding
        # the MCP tool set for the active session.  Reloading invalidates
        # the provider prompt cache (tool schemas are baked into the system
        # prompt), so the next message re-sends full input tokens — this can
        # be expensive on long-context or high-reasoning models.  Users click
        # "Always Approve" to silence the prompt permanently; that flips
        # this key to false.
        "mcp_reload_confirm": True,
        # When true, destructive session slash commands (/clear, /new, /reset,
        # /undo) ask the user to confirm before discarding forecast-session state.
        # Three-option prompt (Approve Once / Always Approve / Cancel) routed
        # through tools.slash_confirm — native yes/no buttons on Telegram,
        # Discord, and Slack; text fallback elsewhere.  Users click "Always
        # Approve" to silence the prompt permanently; that flips this key to
        # false.  TUI has its own modal overlay (HERMES_TUI_NO_CONFIRM=1 to
        # opt out there).
        "destructive_slash_confirm": True,
    },
    # Permanently allowed dangerous command patterns (added via "always" approval)
    "command_allowlist": [],
    # User-defined quick commands that bypass the agent loop (type: exec only)
    "quick_commands": {},
    # Shell-script hooks — declarative bridge that invokes shell scripts
    # on plugin-hook events (pre_tool_call, post_tool_call, pre_llm_call,
    # subagent_stop, etc.).  Each entry maps an event name to a list of
    # {matcher, command, timeout} dicts.  First registration of a new
    # command prompts the user for consent; subsequent runs reuse the
    # stored approval from active agent-home shell-hooks-allowlist.json.
    # See `website/docs/user-guide/features/hooks.md` for schema + examples.
    "hooks": {},
    # Auto-accept shell-hook registrations without a TTY prompt.  Also
    # toggleable per-invocation via --accept-hooks or SUPERFORECASTING_AGENT_ACCEPT_HOOKS=1.
    # Gateway / cron / non-interactive runs need this (or one of the other
    # channels) to pick up newly-added hooks.
    "hooks_auto_accept": False,
    # Custom personalities — add your own entries here
    # Supports string format: {"name": "system prompt"}
    # Or dict format: {"name": {"description": "...", "system_prompt": "...", "tone": "...", "style": "..."}}
    "personalities": {},
    # Pre-exec security scanning via tirith
    "security": {
        "allow_private_urls": False,  # Allow requests to private/internal IPs (for OpenWrt, proxies, VPNs)
        "redact_secrets": True,
        "tirith_enabled": True,
        "tirith_path": "tirith",
        "tirith_timeout": 5,
        "tirith_fail_open": True,
        "website_blocklist": {
            "enabled": False,
            "domains": [],
            "shared_files": [],
        },
        # Acknowledged supply-chain security advisories. Each entry is the
        # ID of an advisory the user has read and acted on (uninstalled the
        # compromised package, rotated credentials). Acked advisories no
        # longer trigger the startup banner. Add via
        # `superforecasting-agent doctor --ack <id>`; remove by editing the
        # list directly. See
        # ``superforecasting_agent/runtime/security_advisories.py`` for the catalog.
        "acked_advisories": [],
        # Allow Hermes to lazy-install opt-in backend packages from PyPI
        # the first time the user enables a backend that needs them
        # (e.g. installing ``elevenlabs`` when the user picks ElevenLabs as
        # their TTS provider). Set to false to require explicit
        # ``pip install`` for everything beyond the base set — appropriate
        # for restricted networks, audited environments, or air-gapped
        # systems where any runtime install is unacceptable.
        "allow_lazy_installs": True,
    },
    "cron": {
        # Wrap delivered cron responses with a header (task name) and footer
        # ("The agent cannot see this message").  Set to false for clean output.
        "wrap_response": True,
        # Maximum number of due jobs to run in parallel per tick.
        # null/0 = unbounded (limited only by thread count).
        # 1 = serial (pre-v0.9 behaviour).
        # Also overridable via SUPERFORECASTING_AGENT_CRON_MAX_PARALLEL
        # / FORECAST_CRON_MAX_PARALLEL / HERMES_CRON_MAX_PARALLEL env vars.
        "max_parallel_jobs": None,
        # Forecast maintenance scripts can contain several bounded agent calls.
        # Two minutes was short enough to kill healthy estimator batches midway.
        "script_timeout_seconds": 900,
        "warning_automode": {
            # One action every half-hour gives 48/day of throughput while keeping
            # each no-agent cron tick comfortably inside its wall-clock limit.
            "paid_budget": 1,
            "paid_min_interval_hours": 0.5,
            "learned_error_review_budget": 1,
            "learned_error_review_min_interval_hours": 0.5,
        },
        "source_estimator": {
            # A dedicated worker may burst when arrivals outrun completions, but
            # its daily model-task ceiling makes the spend boundary explicit.
            "enabled": True,
            "interval_minutes": 15,
            "max_tasks_per_cycle": 8,
            "daily_task_budget": 48,
            "max_iterations": 12,
            "target_oldest_hours": 2,
            "target_p90_hours": 4,
            "alert_after_bad_cycles": 2,
        },
    },
    # Kanban multi-agent coordination — controls the dispatcher loop that
    # spawns workers for ready tasks. The dispatcher ticks every N seconds
    # (default 60), reclaims stale claims, promotes dependency-satisfied
    # todos to ready, and fires `superforecasting-agent -p <assignee> desk -q ...` for
    # each claimable ready task. One dispatcher per profile is sufficient;
    # running more than one on the same kanban.db will race for claims.
    "kanban": {
        # Run the dispatcher inside the gateway process. On by default —
        # the cost is ~300µs every `dispatch_interval_seconds` when idle,
        # and gateway is the supervisor users already have. Set to false
        # only if you run the dispatcher as a separate systemd unit or
        # don't want the gateway to spawn workers.
        "dispatch_in_gateway": True,
        # Seconds between dispatcher ticks (idle or not). Lower = snappier
        # pickup of newly-ready tasks; higher = less SQL pressure.
        "dispatch_interval_seconds": 60,
        # Auto-block after this many consecutive non-success attempts for the
        # same task/profile (spawn_failed, timed_out, or crashed). Reassignment
        # resets the streak for the new profile.
        "failure_limit": 2,
        # Worker stdout/stderr logs rotate at spawn time. Defaults preserve
        # the historical 2 MiB + one-backup behavior; long-running workers can
        # raise these to keep more early failure evidence.
        "worker_log_rotate_bytes": 2 * 1024 * 1024,
        "worker_log_backup_count": 1,
        # Profile that decomposes tasks in the Triage column. When unset,
        # falls back to the default profile (the one `hermes` launches with
        # no -p flag). Set this to a dedicated 'orchestrator' profile if you
        # want decomposition to use a different model/skills from your main
        # working profile.
        "orchestrator_profile": "",
        # Where a child task lands if the orchestrator can't match an
        # assignee to any installed profile. When unset, falls back to the
        # default profile. A task never ends up with assignee=None.
        "default_assignee": "",
        # When true, the kanban dispatcher auto-runs the decomposer on
        # tasks that land in Triage (every dispatcher tick). When false,
        # decomposition is manual via `superforecasting-agent kanban decompose <id>` or
        # the dashboard's Decompose button.
        "auto_decompose": True,
        # Max triage tasks to decompose per dispatcher tick. Prevents a
        # large bulk-load of triage tasks from spending a burst of aux
        # LLM calls in one tick. Excess tasks defer to the next tick.
        "auto_decompose_per_tick": 3,
        # Stale detection: running tasks that have exceeded this many
        # seconds without a heartbeat (since ``last_heartbeat_at``) are
        # auto-reclaimed to ``ready`` on the next dispatcher tick. The
        # worker process (if still running host-locally) is terminated
        # before the reclaim.  0 disables stale detection entirely.
        "dispatch_stale_timeout_seconds": 14400,
    },
    # execute_code settings — controls the tool used for programmatic tool calls.
    "code_execution": {
        # Execution mode:
        #   project (default) — scripts run in the session's working directory
        #     with the active virtualenv/conda env's python, so project deps
        #     (pandas, torch, project packages) and relative paths resolve.
        #   strict            — scripts run in an isolated temp directory with
        #     hermes-agent's own python (sys.executable). Maximum isolation
        #     and reproducibility; project deps and relative paths won't work.
        # Env scrubbing (strips *_API_KEY, *_TOKEN, *_SECRET, ...) and the
        # tool whitelist apply identically in both modes.
        "mode": "project",
    },
    # Logging — controls file logging to active agent-home logs/.
    # agent.log captures INFO+ (all agent activity); errors.log captures WARNING+.
    "logging": {
        "level": "INFO",  # Minimum level for agent.log: DEBUG, INFO, WARNING
        "max_size_mb": 5,  # Max size per log file before rotation
        "backup_count": 3,  # Number of rotated backup files to keep
        # Periodic process memory usage logging (gateway only). Emits a
        # grep-friendly "[MEMORY] rss=...MB ..." line at the configured
        # interval so slow leaks in the long-lived gateway are visible
        # in agent.log / gateway.log as a time series. Ported from
        # cline/cline#10343.
        "memory_monitor": {
            "enabled": True,  # Flip to false to silence the periodic line
            "interval_seconds": 300,  # Default: every 5 minutes
        },
    },
    # Remotely-hosted model catalog manifest.  When enabled, the CLI fetches
    # curated model lists for OpenRouter and Nous Portal from this URL,
    # falling back to the in-repo snapshot on network failure.  Lets us
    # update model picker lists without shipping a Superforecasting Agent release.
    # The default URL is served from the fork's raw GitHub catalog snapshot.
    "model_catalog": {
        "enabled": True,
        "url": "https://raw.githubusercontent.com/teddyjfpender/superforecasting-agent/superforecasting-agent-snapshot/website/static/api/model-catalog.json",
        # Disk cache TTL in hours.  Beyond this, the CLI refetches on the
        # next /model or `superforecasting-agent model` invocation; network failures
        # silently fall back to the stale cache.
        "ttl_hours": 24,
        # Optional per-provider override URLs for third parties that want
        # to self-host their own curation list using the same schema.
        # Example:
        #   providers:
        #     openrouter:
        #       url: https://example.com/my-curation.json
        "providers": {},
    },
    # Network settings — workarounds for connectivity issues.
    "network": {
        # Force IPv4 connections.  On servers with broken or unreachable IPv6,
        # Python tries AAAA records first and hangs for the full TCP timeout
        # before falling back to IPv4.  Set to true to skip IPv6 entirely.
        "force_ipv4": False,
    },
    # Session storage — controls automatic cleanup of active agent-home state.db.
    # state.db accumulates every session, message, tool call, and FTS5 index
    # entry forever.  Without auto-pruning, a heavy user (gateway + cron)
    # reports 384MB+ databases with 68K+ messages, which slows down FTS5
    # inserts, /resume listing, and insights queries.
    "sessions": {
        # When true, prune ended sessions older than retention_days once
        # per (roughly) min_interval_hours at CLI/gateway/cron startup.
        # Only touches ended sessions — active sessions are always preserved.
        # Default false: session history is valuable for search recall, and
        # silently deleting it could surprise users.  Opt in explicitly.
        "auto_prune": False,
        # How many days of ended-session history to keep.  Matches the
        # default of ``hermes sessions prune``.
        "retention_days": 90,
        # VACUUM after a prune that actually deleted rows.  SQLite does not
        # reclaim disk space on DELETE — freed pages are just reused on
        # subsequent INSERTs — so without VACUUM the file stays bloated
        # even after pruning.  VACUUM blocks writes for a few seconds per
        # 100MB, so it only runs at startup, and only when prune deleted
        # ≥1 session.
        "vacuum_after_prune": True,
        # Minimum hours between auto-maintenance runs (avoids repeating
        # the sweep on every CLI invocation).  Tracked via state_meta in
        # state.db itself, so it's shared across all processes.
        "min_interval_hours": 24,
    },
    # Contextual first-touch onboarding hints (see agent/onboarding.py).
    # Each hint is shown once per install and then latched here so it
    # never fires again.  Users can wipe the section to re-see all hints.
    "onboarding": {
        "seen": {},
    },
    # ``superforecasting-agent update`` behaviour.
    "updates": {
        # Run a full ``superforecasting-agent backup``-style zip of
        # HERMES_HOME before every ``superforecasting-agent update``. Backups
        # land in ``<HERMES_HOME>/backups/`` and can be restored with
        # ``superforecasting-agent import <path>``. Off by default —
        # on large HERMES_HOME directories the zip can add minutes to every
        # update.  Set to true to re-enable, or pass ``--backup`` to opt in
        # for a single update run.
        "pre_update_backup": False,
        # How many pre-update backup zips to retain.  Older ones are pruned
        # automatically after each successful backup.  Values below 1 are
        # floored to 1 — the backup just created is always preserved.  To
        # disable backups entirely, set ``pre_update_backup: false`` above
        # rather than ``backup_keep: 0``.
        "backup_keep": 5,
    },
    # Language Server Protocol — semantic diagnostics from real
    # language servers (pyright, gopls, rust-analyzer, etc.) wired
    # into the post-write lint check used by ``write_file`` and
    # ``patch``.
    #
    # LSP is gated on git-workspace detection: when the agent's
    # cwd (or the file being edited) is inside a git worktree, LSP
    # runs against that workspace.  When neither is in a git repo,
    # LSP stays dormant and the in-process syntax check is the only
    # tier — handy for Telegram/Discord chats where the cwd is the
    # user's home directory.
    "lsp": {
        # Master toggle.  Setting this to false disables the entire
        # subsystem — no servers spawn, no background event loop, no
        # cost.
        "enabled": True,
        # Diagnostic-wait mode for the post-write check.
        # ``"document"`` waits up to ``wait_timeout`` seconds for the
        # current file's diagnostics; ``"full"`` additionally requests
        # workspace-wide diagnostics (slower).
        "wait_mode": "document",
        "wait_timeout": 5.0,
        # How to handle missing server binaries.
        # ``"auto"`` — try to install via npm/go/pip into
        #              ``<HERMES_HOME>/lsp/bin/`` on first use.
        # ``"manual"`` — only use binaries already on PATH.
        # ``"off"`` — alias for ``manual``.
        "install_strategy": "auto",
        # Per-server overrides.  Each key is a server_id from the
        # registry (``pyright``, ``typescript``, ``gopls``,
        # ``rust-analyzer``, etc.) and accepts:
        #   disabled: true
        #     — skip this server even when its extensions match
        #   command: ["full/path/to/server", "--stdio"]
        #     — pin a custom binary path; bypasses auto-install
        #   env: {"KEY": "value"}
        #     — extra env vars passed to the spawned process
        #   initialization_options: {...}
        #     — merged into the LSP ``initializationOptions``
        # Empty by default; the registry defaults work for typical
        # setups.
        "servers": {},
    },
    # X (Twitter) Search via xAI's built-in x_search Responses tool.
    # The tool registers when xAI credentials are available (SuperGrok
    # OAuth or XAI_API_KEY) AND the x_search toolset is enabled in
    # `superforecasting-agent tools`. These settings tune the backing Responses
    # API call.
    "x_search": {
        # xAI model used for the Responses call. grok-4.20-reasoning is
        # the recommended default; any Grok model with x_search tool
        # access works.
        "model": "grok-4.20-reasoning",
        # Request timeout in seconds (minimum 30). x_search can take
        # 60-120s for complex queries — the default is generous.
        "timeout_seconds": 180,
        # Number of automatic retries on 5xx / ReadTimeout / ConnectionError.
        # Each retry backs off (1.5x attempt seconds, capped at 5s).
        "retries": 2,
    },
    # Config schema version - bump this when adding new required fields
    "_config_version": 23,
}

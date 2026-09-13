"""Shared scheduled-task command behavior for terminal clients."""

import json
from collections.abc import Callable

from cron import get_job

def _execute_cron_command(cmd: str, emit: Callable[[str], None]) -> None:
    """Handle the /cron command to manage scheduled tasks."""
    import shlex
    from tools.cronjob_tools import cronjob as cronjob_tool

    def _cron_api(**kwargs):
        return json.loads(cronjob_tool(**kwargs))

    def _normalize_skills(values):
        normalized = []
        for value in values:
            text = str(value or "").strip()
            if text and text not in normalized:
                normalized.append(text)
        return normalized

    def _parse_flags(tokens):
        opts = {
            "name": None,
            "deliver": None,
            "repeat": None,
            "skills": [],
            "add_skills": [],
            "remove_skills": [],
            "clear_skills": False,
            "all": False,
            "prompt": None,
            "schedule": None,
            "positionals": [],
        }
        i = 0
        while i < len(tokens):
            token = tokens[i]
            value_flags = {"--name", "--deliver", "--repeat", "--skill", "--add-skill", "--remove-skill", "--prompt", "--schedule"}
            if token in value_flags and (i + 1 == len(tokens) or tokens[i + 1].startswith("--")):
                emit(f"Missing value for {token}")
                return None
            if token == "--name" and i + 1 < len(tokens):
                opts["name"] = tokens[i + 1]
                i += 2
            elif token == "--deliver" and i + 1 < len(tokens):
                opts["deliver"] = tokens[i + 1]
                i += 2
            elif token == "--repeat" and i + 1 < len(tokens):
                try:
                    opts["repeat"] = int(tokens[i + 1])
                except ValueError:
                    emit("--repeat must be an integer")
                    return None
                i += 2
            elif token == "--skill" and i + 1 < len(tokens):
                opts["skills"].append(tokens[i + 1])
                i += 2
            elif token == "--add-skill" and i + 1 < len(tokens):
                opts["add_skills"].append(tokens[i + 1])
                i += 2
            elif token == "--remove-skill" and i + 1 < len(tokens):
                opts["remove_skills"].append(tokens[i + 1])
                i += 2
            elif token == "--clear-skills":
                opts["clear_skills"] = True
                i += 1
            elif token == "--all":
                opts["all"] = True
                i += 1
            elif token == "--prompt" and i + 1 < len(tokens):
                opts["prompt"] = tokens[i + 1]
                i += 2
            elif token == "--schedule" and i + 1 < len(tokens):
                opts["schedule"] = tokens[i + 1]
                i += 2
            elif token.startswith("--"):
                emit(f"Unknown option or missing value: {token}")
                return None
            else:
                opts["positionals"].append(token)
                i += 1
        return opts

    try:
        tokens = shlex.split(cmd)
    except ValueError as exc:
        emit(f"Invalid cron arguments: {exc}")
        return

    if len(tokens) == 1:
        emit("")
        emit("+" + "-" * 68 + "+")
        emit("|" + " " * 26 + "Scheduled Tasks" + " " * 27 + "|")
        emit("+" + "-" * 68 + "+")
        emit("")
        emit("  Commands:")
        emit("    /cron list")
        emit('    /cron add "every 2h" "Check server status" [--skill blogwatcher]')
        emit('    /cron edit <job_id> --schedule "every 4h" --prompt "New task"')
        emit("    /cron edit <job_id> --skill blogwatcher --skill maps")
        emit("    /cron edit <job_id> --remove-skill blogwatcher")
        emit("    /cron edit <job_id> --clear-skills")
        emit("    /cron pause <job_id>")
        emit("    /cron resume <job_id>")
        emit("    /cron run <job_id>")
        emit("    /cron remove <job_id>")
        emit("")
        result = _cron_api(action="list")
        if not result.get("success"):
            emit(f"Failed to list jobs: {result.get('error')}")
            return
        jobs = result.get("jobs", [])
        if jobs:
            emit("  Current Jobs:")
            emit("  " + "-" * 63)
            for job in jobs:
                repeat_str = job.get("repeat", "?")
                emit(f"    {job['job_id'][:12]:<12} | {job['schedule']:<15} | {repeat_str:<8}")
                if job.get("skills"):
                    emit(f"      Skills: {', '.join(job['skills'])}")
                emit(f"      {job.get('prompt_preview', '')}")
                if job.get("next_run_at"):
                    emit(f"      Next: {job['next_run_at']}")
                emit("")
        else:
            emit("  No scheduled jobs. Use '/cron add' to create one.")
        emit("")
        return

    subcommand = tokens[1].lower()
    opts = _parse_flags(tokens[2:])
    if opts is None:
        return

    if subcommand == "list":
        result = _cron_api(action="list", include_disabled=opts["all"])
        if not result.get("success"):
            emit(f"Failed to list jobs: {result.get('error')}")
            return
        jobs = result.get("jobs", [])
        if not jobs:
            emit("No scheduled jobs.")
            return

        emit("")
        emit("Scheduled Jobs:")
        emit("-" * 80)
        for job in jobs:
            emit(f"  ID: {job['job_id']}")
            emit(f"  Name: {job['name']}")
            emit(f"  State: {job.get('state', '?')}")
            emit(f"  Schedule: {job['schedule']} ({job.get('repeat', '?')})")
            emit(f"  Next run: {job.get('next_run_at', 'N/A')}")
            if job.get("skills"):
                emit(f"  Skills: {', '.join(job['skills'])}")
            emit(f"  Prompt: {job.get('prompt_preview', '')}")
            if job.get("last_run_at"):
                emit(f"  Last run: {job['last_run_at']} ({job.get('last_status', '?')})")
            emit("")
        return

    if subcommand in {"add", "create"}:
        positionals = opts["positionals"]
        if not positionals:
            emit("Usage: /cron add <schedule> <prompt>")
            return
        schedule = opts["schedule"] or positionals[0]
        prompt = opts["prompt"] or " ".join(positionals[1:])
        skills = _normalize_skills(opts["skills"])
        if not prompt and not skills:
            emit("Please provide a prompt or at least one skill")
            return
        result = _cron_api(
            action="create",
            schedule=schedule,
            prompt=prompt or None,
            name=opts["name"],
            deliver=opts["deliver"],
            repeat=opts["repeat"],
            skills=skills or None,
        )
        if result.get("success"):
            emit(f"Created job: {result['job_id']}")
            emit(f"  Schedule: {result['schedule']}")
            if result.get("skills"):
                emit(f"  Skills: {', '.join(result['skills'])}")
            emit(f"  Next run: {result['next_run_at']}")
        else:
            emit(f"Failed to create job: {result.get('error')}")
        return

    if subcommand == "edit":
        positionals = opts["positionals"]
        if not positionals:
            emit("Usage: /cron edit <job_id> [--schedule ...] [--prompt ...] [--skill ...]")
            return
        job_id = positionals[0]
        existing = get_job(job_id)
        if not existing:
            emit(f"Job not found: {job_id}")
            return

        final_skills = None
        replacement_skills = _normalize_skills(opts["skills"])
        add_skills = _normalize_skills(opts["add_skills"])
        remove_skills = set(_normalize_skills(opts["remove_skills"]))
        existing_skills = list(existing.get("skills") or ([] if not existing.get("skill") else [existing.get("skill")]))
        if opts["clear_skills"]:
            final_skills = []
        elif replacement_skills:
            final_skills = replacement_skills
        elif add_skills or remove_skills:
            final_skills = [skill for skill in existing_skills if skill not in remove_skills]
            for skill in add_skills:
                if skill not in final_skills:
                    final_skills.append(skill)

        result = _cron_api(
            action="update",
            job_id=job_id,
            schedule=opts["schedule"],
            prompt=opts["prompt"],
            name=opts["name"],
            deliver=opts["deliver"],
            repeat=opts["repeat"],
            skills=final_skills,
        )
        if result.get("success"):
            job = result["job"]
            emit(f"Updated job: {job['job_id']}")
            emit(f"  Schedule: {job['schedule']}")
            if job.get("skills"):
                emit(f"  Skills: {', '.join(job['skills'])}")
            else:
                emit("  Skills: none")
        else:
            emit(f"Failed to update job: {result.get('error')}")
        return

    if subcommand in {"pause", "resume", "run", "remove", "rm", "delete"}:
        positionals = opts["positionals"]
        if not positionals:
            emit(f"Usage: /cron {subcommand} <job_id>")
            return
        job_id = positionals[0]
        action = "remove" if subcommand in {"remove", "rm", "delete"} else subcommand
        result = _cron_api(action=action, job_id=job_id, reason="paused from /cron" if action == "pause" else None)
        if not result.get("success"):
            emit(f"Failed to {action} job: {result.get('error')}")
            return
        if action == "pause":
            emit(f"Paused job: {result['job']['name']} ({job_id})")
        elif action == "resume":
            emit(f"Resumed job: {result['job']['name']} ({job_id})")
            emit(f"  Next run: {result['job'].get('next_run_at')}")
        elif action == "run":
            emit(f"Triggered job: {result['job']['name']} ({job_id})")
            emit("  It will run on the next scheduler tick.")
        else:
            removed = result.get("removed_job", {})
            emit(f"Removed job: {removed.get('name', job_id)} ({job_id})")
        return

    emit(f"Unknown cron command: {subcommand}")
    emit("  Available: list, add, edit, pause, resume, run, remove")


def cron_command_output(argument: str = "") -> str:
    """Execute once and return output without redirecting process-wide stdout."""
    lines: list[str] = []
    _execute_cron_command("/cron " + argument, lines.append)
    return "\n".join(lines)


def _handle_cron_command(self, cmd: str) -> None:
    """Compatibility method used by the classic CLI."""
    parts = cmd.split(maxsplit=1)
    print(cron_command_output(parts[1] if len(parts) > 1 else ""))

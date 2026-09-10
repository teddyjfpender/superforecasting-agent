#!/usr/bin/env python3
"""Rehearse wheel installation/upgrade and the public CLI in disposable profiles.

Requires uv on PATH. No model calls or real user configuration. Optional captured
USGS/NWS feeds exercise real-source parsers offline with immutable input bytes.
All outcomes are operational fixtures, never prospective skill evidence.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@contextmanager
def feeds(directory):
    if directory is None:
        yield None
        return
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            name = self.path.split("?", 1)[0].strip("/")
            if name not in {"usgs", "nws"}:
                self.send_error(404)
                return
            data = (directory / f"{name}.json").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--previous-wheel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New directory; never reuses a profile")
    parser.add_argument("--source-dir", type=Path)
    args = parser.parse_args()
    args.wheel = args.wheel.resolve()
    args.previous_wheel = args.previous_wheel.resolve()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    report = {"kind": "operational-release-rehearsal", "prospective_skill_evidence": False,
              "wheel_sha256": digest(args.wheel), "previous_wheel_sha256": digest(args.previous_wheel), "commands": []}
    if args.source_dir:
        source_dir = args.output / "sources"
        shutil.copytree(args.source_dir, source_dir)
        args.source_dir = source_dir
        report["sources"] = json.loads((source_dir / "manifest.json").read_text(encoding="utf-8"))
        for source in report["sources"]:
            assert digest(source_dir / f"{source['source']}.json") == source["sha256"]
    (args.output / "README.txt").write_text("Disposable release fixtures. No prospective forecasting claim.\n", encoding="utf-8")
    uv = shutil.which("uv")
    if not uv:
        raise SystemExit("uv is required")

    def run(argv, env, *, ok=True):
        result = subprocess.run([str(x) for x in argv], cwd=args.output, env=env,
                                capture_output=True, text=True, timeout=180)
        report["commands"].append({"argv": [str(x) for x in argv], "returncode": result.returncode,
                                   "stdout": result.stdout, "stderr": result.stderr})
        (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        if ok and result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        return result

    def environment(home, venv):
        home.mkdir(parents=True)
        agent_home = home / ".superforecasting-agent"
        agent_home.mkdir()
        return {"PATH": f"{venv / 'bin'}:{Path(uv).parent}:/usr/bin:/bin", "HOME": str(home),
                "SUPERFORECASTING_AGENT_HOME": str(agent_home), "FORECAST_HOME": str(agent_home),
                "HERMES_HOME": str(agent_home), "PYTHONNOUSERSITE": "1", "AWS_EC2_METADATA_DISABLED": "true"}

    def cli(exe, env, *words, ok=True):
        return run([exe, "forecast", *words], env, ok=ok).stdout

    def question(exe, env, label):
        output = cli(exe, env, "new", f"Will the {label} release rehearsal capture its local observation?",
                     "--resolution-criteria", "Yes if this isolated rehearsal records the fixture observation; no if it completes without it.",
                     "--domain", "release-rehearsal", "--tag", "operational-fixture")
        return re.search(r"fq_[a-f0-9]+", output).group()

    def lifecycle(exe, python, env, endpoint):
        invalid = run([exe, "forecast", "new", "Unscoreable fixture", "--resolution-criteria", ""], env, ok=False)
        assert invalid.returncode != 0 and "resolution" in (invalid.stdout + invalid.stderr).lower()
        qid = question(exe, env, "installed wheel")
        note = args.output / "observation.txt"
        note.write_text("Operational fixture observation captured. Not a prospective outcome.\n", encoding="utf-8")
        output = cli(exe, env, "research", qid, str(note), "--claim", "The fixture observation exists.")
        evidence = re.search(r"ev_[a-f0-9]+", output).group()
        if endpoint:
            for adapter in ("usgs", "nws"):
                first = cli(exe, env, "import", adapter, f"{endpoint}/{adapter}", "--question", qid, "--limit", "3")
                assert "captured 3" in first, first
                repeat = cli(exe, env, "import", adapter, f"{endpoint}/{adapter}", "--question", qid, "--limit", "3")
                assert f"captured 0 {adapter}" in repeat, repeat
        cli(exe, env, "update", qid, "--probability", "0.6", "--confidence", "0.5", "--method", "release-rehearsal",
            "--rationale", "Fixed operational fixture probability; not a skill estimate.",
            "--reason-up", "Fixture observation was captured.", "--reason-down", "The release could fail to preserve it.",
            "--change-my-mind", "Missing persisted evidence after upgrade.", "--evidence-ref", evidence,
            "--calibration-ineligible")
        invalid = run([exe, "forecast", "resolve", qid, "--outcome", "unknown", "--source", str(note)], env, ok=False)
        assert invalid.returncode != 0, "unsupported binary outcomes must not resolve a question"
        cli(exe, env, "resolve", qid, "--outcome", "yes", "--source", str(note), "--notes", "Operational fixture only.")
        scored = cli(exe, env, "score", qid)
        assert "brier_score:" in scored, scored
        postmortem = cli(exe, env, "postmortem", qid, "--summary", "The installed CLI preserved the full fixture lifecycle.",
                         "--what-happened", "Create, research, update, resolve and score succeeded.",
                         "--what-was-expected", "Durable ledger records survive installed CLI execution.",
                         "--lesson", "Separate release rehearsals from prospective calibration claims.")
        assert "calibration_lesson: created" in postmortem, postmortem
        cli(exe, env, "show", qid)
        # Independent read verifies durable relations, adapter revision times and source diversity.
        inspection = '''import json
from forecasting.ledger import ForecastLedger
from forecasting.models import ValidationError
from datetime import timedelta
from forecasting.models import timestamp_to_datetime
from superforecasting_agent.constants import get_agent_home
ledger=ForecastLedger(get_agent_home()/"forecasting"/"forecasting.db")
q=ledger.get_question(QID)
items=ledger.list_evidence(QID)
assert q.status == "resolved"
assert ledger.get_current_score(QID) is not None
assert len(ledger.list_postmortems(QID)) == 1
for item in items:
 if item.source_type == "adapter:usgs":
  assert item.available_at == item.metadata["updated_at"]
  assert item.metadata["observed_at"] <= item.available_at
  if item.metadata["observed_at"] < item.available_at:
   try:
    ledger._validate_evidence_refs(QID, [item.id], item.metadata["observed_at"])
   except ValidationError:
    pass
   else:
    raise AssertionError("revised observation leaked before its publication")
 if item.source_type == "adapter:nws":
  assert item.available_at == item.metadata["sent_at"]
latest=max(timestamp_to_datetime(item.available_at) for item in items)
stale=ledger.find_stale_evidence_refs(QID, [item.id for item in items], as_of=(latest+timedelta(days=31)).isoformat(), stale_days=30)
assert len(stale) == len(items)
print(json.dumps({"question_id":q.id,"status":q.status,"evidence_count":len(items),"diversity":ledger.question_source_diversity(QID)}))
'''.replace("QID", repr(qid))
        run([python, "-I", "-c", inspection], env)
        return qid

    try:
        with feeds(args.source_dir) as endpoint:
            for mode in ("upgrade", "fresh"):
                venv = args.output / f"{mode}-venv"
                env = environment(args.output / f"{mode}-home", venv)
                run([uv, "venv", venv], env)
                python = venv / "bin/python"
                exe = venv / "bin/superforecasting-agent"
                initial = args.previous_wheel if mode == "upgrade" else args.wheel
                run([uv, "pip", "install", "--python", python, initial], env)
                if mode == "upgrade":
                    seed = question(exe, env, "pre-upgrade")
                    cli(exe, env, "research", seed, "Pre-upgrade observation retained for release verification.")
                    config = Path(env["SUPERFORECASTING_AGENT_HOME"]) / "config.yaml"
                    config.write_text("display:\n  skin: mono\n", encoding="utf-8")
                    before = cli(exe, env, "show", seed)
                    run([uv, "pip", "install", "--python", python, "--reinstall-package", "superforecasting-agent", args.wheel], env)
                    assert cli(exe, env, "show", seed) == before
                    assert config.read_text(encoding="utf-8") == "display:\n  skin: mono\n"
                run([python, "-I", "-c", "import forecasting, sys; from pathlib import Path; assert Path(forecasting.__file__).is_relative_to(sys.prefix); print(forecasting.__file__)"], env)
                report[mode] = {"question_id": lifecycle(exe, python, env, endpoint), "passed": True}
        report["passed"] = True
    finally:
        (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "commands"}, indent=2))


if __name__ == "__main__":
    main()

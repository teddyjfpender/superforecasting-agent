"""Batch command failures must be visible to shell automation."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    ('arguments', 'message', 'status'),
    [
        ([], '--dataset_file is required', 2),
        (['--dataset_file=prompts.jsonl'], '--batch_size must be a positive integer', 2),
        (['--dataset_file=prompts.jsonl', '--batch_size=1'], '--run_name is required', 2),
        (['--reasoning_effort=invalid'], '--reasoning_effort must be one of', 2),
        (['--prefill_messages_file=missing.json'], 'Error loading prefill messages', 2),
        (['--prefill_messages_file=object.json'], 'must contain a JSON array', 2),
        (['--prefill_messages_file=malformed.json'], 'Error loading prefill messages', 2),
        (['--dataset_file=missing.jsonl'], 'Fatal error:', 1),
    ],
)
def test_errors_exit_nonzero(tmp_path, arguments, message, status):
    (tmp_path / 'prompts.jsonl').write_text('{"prompt":"fixture"}\n')
    (tmp_path / 'object.json').write_text('{}')
    (tmp_path / 'malformed.json').write_text('{')
    if message not in {
        '--dataset_file is required', '--batch_size must be a positive integer',
        '--run_name is required',
    }:
        arguments = [
            '--dataset_file=prompts.jsonl', '--batch_size=1', '--run_name=fixture',
            *arguments,
        ]
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, '-m', 'superforecasting_agent.trajectories.batch', *arguments],
        cwd=tmp_path, env={**os.environ, 'PYTHONPATH': str(root)},
        capture_output=True, text=True, timeout=30,
    )
    assert message in result.stdout
    assert result.returncode == status, result.stdout + result.stderr

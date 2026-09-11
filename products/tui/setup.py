"""Never produce an installable client missing its compiled product."""
from pathlib import Path

from setuptools import setup

if not (Path(__file__).parent / 'superforecasting_agent_tui/dist/entry.js').is_file():
    raise RuntimeError('Missing Ink bundle. Run python3 scripts/build_profiles.py from the repository root.')
setup()

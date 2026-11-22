"""Vercel entry point: Vercel looks for an `app` object in `app.py` at the project root.

The package lives under `src/`, which Vercel does not put on the import path by itself, so it is
added here. Everything else (settings, database, providers) comes from environment variables, see
`.env.example` and docs/DEPLOY_VERCEL_NEON.md.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from pharmavique.bootstrap.api import create_app

app = create_app()

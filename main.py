"""Module entry point for python -m main or uvicorn.

This file exists at the project root for Docker compatibility.
The actual application is in backend/app/main.py.
"""

import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from app.main import cli  # noqa: E402

if __name__ == "__main__":
    cli()

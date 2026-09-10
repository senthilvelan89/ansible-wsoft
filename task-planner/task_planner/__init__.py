"""A local-first task planner backed by SQLite.

The package ships a command line interface and a small web UI. Everything is
built on the Python standard library so it runs on a stock macOS install.
"""

from __future__ import annotations

__version__ = "1.0.0"

APP_NAME = "task-planner"
DEFAULT_WEB_PORT = 8766

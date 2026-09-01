"""A local-first expense tracker backed by SQLite.

The package ships a command line interface and a small web UI. Everything is
built on the Python standard library so it runs on a stock macOS install.
"""

from __future__ import annotations

__version__ = "1.0.0"

APP_NAME = "expense-tracker"
DEFAULT_RETENTION_MONTHS = 12

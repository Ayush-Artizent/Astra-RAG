"""Persistent registry (SQLite): repos and their tracked branch, project bindings, ingestion runs."""
from .db import migrate, use_db
from .runs import sweep_interrupted


def startup() -> None:
    """Run at app start: bring the schema up to date, then fail runs a previous process left behind."""
    migrate()
    sweep_interrupted()

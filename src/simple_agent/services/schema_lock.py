"""Coordinate autocommit LangGraph setup and transactional Runtime migrations."""

from time import sleep


def acquire_bootstrap_lock(db) -> None:
    if not db.autocommit:
        raise ValueError("bootstrap_lock_requires_autocommit")
    # A blocking advisory-lock query retains a snapshot and deadlocks CREATE INDEX CONCURRENTLY.
    while not db.execute(
        "SELECT 1 WHERE pg_try_advisory_lock(hashtextextended('oss-runtime-bootstrap', 1))"
    ).fetchone():
        sleep(0.25)

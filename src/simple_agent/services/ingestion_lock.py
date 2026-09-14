"""One writer per volume; replays reuse the persisted plan/draft."""

import fcntl
from functools import wraps


def serialized(method):
    @wraps(method)
    def run(self, *args, **kwargs):
        with (self.raw_root / ".ingestion.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return method(self, *args, **kwargs)

    return run

"""File locking for concurrent access to shared state files."""
import fcntl
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def file_lock(path: Path):
    """Advisory lock on a sidecar .lock file for read-modify-write operations."""
    lock_path = path.parent / f".{path.name}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, 'w') as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)

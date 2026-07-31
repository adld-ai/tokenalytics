"""Atomic persistence for the generated status payload."""
from __future__ import annotations
import json, os
from pathlib import Path


def write_status(path: Path, payload: dict) -> None:
    """Atomically write one payload as private JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(payload, indent=2))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    print(f"Wrote {path} ({payload['account_count']} accounts)")

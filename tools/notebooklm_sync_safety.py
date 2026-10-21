"""Durable, verify-before-retire NotebookLM file replacement."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="." + path.name + "-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def save_json(path, data):
    atomic_write(path, (json.dumps(data, indent=2) + "\n").encode())


@contextmanager
def sync_lock(state_dir):
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    with (state_dir / ".notebooklm-sync.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Another NotebookLM refresh is running for this vault/member; no changes made") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def replace(rf, path, old_source_id):
    """Keep a durable candidate ID/snapshot across interruption and failed verification.

    The caller's old receipt is unchanged on failure. This journal is the recovery
    receipt until the caller has saved the verified candidate in its regular state.
    An uncertain registration is inspected once on resume, never blindly repeated.
    """
    path = Path(path)
    try:
        identity = path.relative_to(rf.VAULT).as_posix()
    except ValueError:
        identity = "external/" + path.name
    notebook = rf._ACTIVE_NOTEBOOK
    if not notebook:
        raise rf.SyncVerificationError("Cannot replace a source without an explicit notebook")
    key = hashlib.sha256((notebook + ":" + identity).encode()).hexdigest()
    folder = rf.STATE_DIR / ".notebooklm-pending" / key
    record = folder / "operation.json"
    snapshot = folder / path.name
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()

    def listing():
        result = rf.run_nb(["source", "list", "--json"])
        if result.returncode:
            raise rf.SyncVerificationError("Cannot list sources; prior source and receipt retained")
        try:
            obj = json.loads(result.stdout)
            rows = obj if isinstance(obj, list) else obj["sources"]
            if not isinstance(rows, list):
                raise ValueError("sources is not a list")
            return rows
        except (ValueError, KeyError, TypeError) as exc:
            raise rf.SyncVerificationError("Cannot parse source listing; prior source retained") from exc

    if record.exists():
        op = json.loads(record.read_text())
        if op["sha256"] != digest:
            raise rf.SyncVerificationError(
                f"Pending replacement for {identity} has a different input. Recover {record} before another upload; prior source retained")
        if snapshot.read_bytes() != data:
            raise rf.SyncVerificationError("Pending snapshot differs from its input; no source retired")
    else:
        rows = listing()
        folder.mkdir(parents=True, exist_ok=True)
        atomic_write(snapshot, data)
        op = {"notebook": notebook, "identity": identity, "title": path.name,
              "sha256": digest, "old_source_id": old_source_id,
              "before_ids": [r.get("id") or r.get("source_id") for r in rows],
              "phase": "prepared"}
        save_json(record, op)

    if op["phase"] == "prepared":
        op["phase"] = "registering"
        save_json(record, op)
        sid = rf.cmd_add(snapshot.resolve())
        if not sid:
            raise rf.SyncVerificationError("Upload returned no candidate ID; prior source retained")
        op.update(source_id=sid, phase="added")
        save_json(record, op)
    elif op["phase"] == "registering":
        candidates = [r.get("id") or r.get("source_id") for r in listing()
                      if r.get("title") == path.name
                      and (r.get("id") or r.get("source_id")) not in op["before_ids"]]
        if len(candidates) != 1:
            raise rf.SyncVerificationError(
                f"Uncertain registration for {identity}: {len(candidates)} new same-title candidates. No re-upload or deletion; inspect {record}")
        op.update(source_id=candidates[0], phase="added")
        save_json(record, op)

    sid = op["source_id"]
    if not rf.cmd_verify_content(sid, snapshot):
        raise rf.SyncVerificationError(
            f"Candidate {sid} failed indexed-content verification. Prior source/receipt retained; no automatic re-upload")
    op["phase"] = "verified"
    save_json(record, op)
    old = op.get("old_source_id")
    if old and old != sid and rf.source_present(old):
        if not rf.cmd_delete(old) and rf.source_present(old):
            raise rf.SyncVerificationError(f"Verified candidate {sid}; could not retire prior {old}. Recovery receipt retained")
    # No title-wide deletion: only the exact recorded predecessor belongs to
    # this transaction. Other copies may belong to another route or an older
    # interrupted operation and require their own verified ownership decision.
    op["phase"] = "completed"
    save_json(record, op)
    return sid, True, bool(old and old != sid)


def finish_receipts(state_dir):
    """Remove completed journals only once their candidate is durably tracked."""
    state_dir = Path(state_dir)
    verified = set()
    for path in state_dir.glob(".notebooklm-*-state.json"):
        data = json.loads(path.read_text())
        for row in data.values():
            if isinstance(row, dict) and row.get("verified_at") and row.get("source_id"):
                verified.add(row["source_id"])
    for path in (state_dir / ".notebooklm-pending").glob("*/operation.json"):
        op = json.loads(path.read_text())
        if op.get("phase") == "completed" and op.get("source_id") in verified:
            # Receipt first, journal last: interruption can leave redundant
            # recovery data, never an untracked verified replacement.
            path.unlink()
            snapshot = path.parent / op["title"]
            snapshot.unlink(missing_ok=True)
            path.parent.rmdir()

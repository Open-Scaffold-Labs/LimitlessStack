"""Lossless append-oriented NotebookLM log exports. No import/planning side effects.

The wiki log remains the source of truth. Sealed older ranges never move; only
log-recent.md changes on an append. A changed sealed prefix is an explicit error,
not permission to silently rewrite the history already represented remotely.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

DEFAULT_MAX_WORDS = 300_000
RECENT_NAME = "log-recent.md"
_HEADING = re.compile(rb"^## \[\d{4}-\d{2}-\d{2}\](?:[ \t]|\r?$)")
_FENCE = re.compile(rb"^ {0,3}(`{3,}|~{3,})")


class LogExportError(ValueError):
    """The log cannot be represented safely without explicit intervention."""


@dataclass(frozen=True)
class ExportPlan:
    # In source order; concatenating these values reconstructs the input bytes.
    files: dict[str, bytes]
    metadata: dict


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _words(data: bytes) -> int:
    return len(data.decode("utf-8").split())


def _entry_starts(data: bytes) -> list[int]:
    """Dated level-two headings outside Markdown fenced code blocks."""
    result = []
    offset = 0
    fence_char = None
    fence_length = 0
    for line in data.splitlines(keepends=True):
        fence = _FENCE.match(line)
        if fence:
            token = fence.group(1)
            if fence_char is None:
                fence_char, fence_length = token[:1], len(token)
            elif (token[:1] == fence_char and len(token) >= fence_length
                  and not line[fence.end():].strip()):
                fence_char = None
                fence_length = 0
        elif fence_char is None and _HEADING.match(line):
            result.append(offset)
        offset += len(line)
    return result


def _part(name: str, start: int, end: int, data: bytes) -> dict:
    content = data[start:end]
    return {"name": name, "start": start, "end": end,
            "sha256": _sha(content), "words": _words(content)}


def plan(data: bytes, prior: dict | None = None,
         max_words: int = DEFAULT_MAX_WORDS) -> ExportPlan:
    """Plan stable older ranges and one recent tail without reading/writing files.

    `prior` is the last published metadata, not a remote verification receipt.
    Planning rejects changes to sealed bytes and rejects entries too large to fit
    in a part; it never cuts an entry, normalizes newlines, or reorders history.
    Whitespace word counts deliberately leave headroom under Google's limit;
    READY and indexed-content checks remain the uploader's responsibility.
    """
    if not isinstance(data, bytes):
        raise TypeError("log input must be bytes")
    if isinstance(max_words, bool) or not isinstance(max_words, int) or max_words < 1:
        raise LogExportError("max_words must be a positive integer")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LogExportError("log must be valid UTF-8") from exc

    headings = _entry_starts(data)
    # Include any preamble in the first entry; the first physical heading is not
    # itself a split point when this would create a separate preamble source.
    boundaries = [n for n in headings[1:] if n > 0] + [len(data)]
    starts = [0] + boundaries[:-1]
    entry_words = [_words(data[a:b]) for a, b in zip(starts, boundaries)]
    for start, count in zip(starts, entry_words):
        if count > max_words:
            raise LogExportError(
                f"log entry at byte {start} has {count} whitespace words; "
                f"maximum per export is {max_words}; entry was not split")

    sealed = []
    start = 0
    if prior is not None:
        if not isinstance(prior, dict) or prior.get("version") != 1:
            raise LogExportError("unsupported or malformed log export metadata")
        if prior.get("max_words") != max_words:
            raise LogExportError("max_words changed; existing sealed ranges need explicit review")
        archives = prior.get("archives")
        if not isinstance(archives, list):
            raise LogExportError("log export metadata has no archive list")
        for i, old in enumerate(archives, 1):
            expected_name = f"log-older-{i:03d}.md"
            if not isinstance(old, dict):
                raise LogExportError("malformed sealed log range")
            end = old.get("end")
            if (old.get("name") != expected_name or old.get("start") != start
                    or isinstance(end, bool) or not isinstance(end, int)
                    or end <= start or end > len(data) or end not in boundaries):
                raise LogExportError(f"invalid sealed boundary for {expected_name}")
            current = _part(expected_name, start, end, data)
            if old != current:
                raise LogExportError(
                    f"sealed history changed in {expected_name}; "
                    "original and existing remote source must be preserved")
            sealed.append(current)
            start = end

    # Prefix counts make selection linear in entry count even for large logs.
    prefix_words = {0: 0}
    running = 0
    for end, count in zip(boundaries, entry_words):
        running += count
        prefix_words[end] = running
    total_words = running
    while total_words - prefix_words[start] > max_words:
        candidates = [end for end in boundaries if start < end < len(data)
                      and prefix_words[end] - prefix_words[start] <= max_words]
        if not candidates:
            raise LogExportError(f"no complete-entry split fits after byte {start}")
        end = candidates[-1]
        name = f"log-older-{len(sealed) + 1:03d}.md"
        sealed.append(_part(name, start, end, data))
        start = end

    recent = _part(RECENT_NAME, start, len(data), data)
    parts = [*sealed, recent]
    files = {part["name"]: data[part["start"]:part["end"]] for part in parts}
    metadata = {"version": 1, "max_words": max_words,
                "source_bytes": len(data), "source_sha256": _sha(data),
                "archives": sealed, "recent": recent}
    return ExportPlan(files, metadata)


def _atomic_write_if_changed(path: Path, data: bytes) -> None:
    if path.exists() and path.read_bytes() == data:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        # Persist the directory rename where the platform supports directory fsync.
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def publish(outdir: Path, metadata_path: Path,
            export_plan: ExportPlan) -> dict[str, Path]:
    """Atomically publish exports, metadata last; unchanged bytes keep mtimes.

    Call under the refresh tool's process lock. This is not a multi-file atomic
    transaction: after interruption, replay plan+publish from the original log
    and last metadata before uploading. No old export is removed here.
    """
    outdir, metadata_path = Path(outdir), Path(metadata_path)
    parts = [*export_plan.metadata["archives"], export_plan.metadata["recent"]]
    expected = {part["name"]: part for part in parts}
    if set(export_plan.files) != set(expected):
        raise LogExportError("export plan files do not match its metadata")
    # Validate everything before the first write, including directory traversal.
    for name, content in export_plan.files.items():
        if Path(name).name != name or name not in expected:
            raise LogExportError("unsafe export filename")
        part = expected[name]
        if len(content) != part["end"] - part["start"] or _sha(content) != part["sha256"]:
            raise LogExportError(f"export bytes do not match metadata for {name}")
    reconstructed = b"".join(export_plan.files[part["name"]] for part in parts)
    if (len(reconstructed) != export_plan.metadata["source_bytes"]
            or _sha(reconstructed) != export_plan.metadata["source_sha256"]):
        raise LogExportError("exports do not reconstruct the planned source")
    paths = {}
    for name, content in export_plan.files.items():
        path = outdir / name
        _atomic_write_if_changed(path, content)
        paths[name] = path
    payload = (json.dumps(export_plan.metadata, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    _atomic_write_if_changed(metadata_path, payload)
    return paths

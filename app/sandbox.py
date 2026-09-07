"""Application-level sandbox for tool file access and execution timeouts.

This is the always-on control plane. Claude Agent SDK sandbox (bubblewrap) is
an optional second layer and may be unavailable on Fargate; path checks here
must not depend on it.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from pathlib import Path
from typing import Awaitable, TypeVar

from app.config import MAX_FILE_BYTES, SANDBOX_ROOT, TOOL_TIMEOUT_SEC

T = TypeVar("T")

BLOCKED_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "credentials",
    "credentials.json",
    "id_rsa",
    "id_ed25519",
    ".aws",
    ".ssh",
    ".git",
}

BLOCKED_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
DEFAULT_READ_SUFFIXES = {".mp3", ".wav", ".png", ".jpg", ".jpeg", ".md", ".txt", ".json", ".csv"}


class SandboxError(ValueError):
    """Raised when a tool attempts to leave the sandbox or read a secret."""


def sandbox_root() -> Path:
    root = SANDBOX_ROOT
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def create_job_dir() -> Path:
    path = sandbox_root() / "jobs" / uuid.uuid4().hex[:12]
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_filename(name: str | None, fallback: str = "upload.bin") -> str:
    raw = (name or fallback).replace("\\", "/")
    base = Path(raw).name
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base).strip("._") or fallback
    if cleaned.startswith("."):
        raise SandboxError("hidden files are not allowed in the sandbox")
    return cleaned


def _is_blocked(path: Path) -> bool:
    for part in path.parts:
        lowered = part.lower()
        if part in BLOCKED_NAMES or lowered in BLOCKED_NAMES:
            return True
        if lowered.startswith(".env"):
            return True
    if path.suffix.lower() in BLOCKED_SUFFIXES:
        return True
    return False


def resolve_sandbox_path(
    user_path: str,
    *,
    must_exist: bool = False,
    allowed_suffixes: set[str] | None = DEFAULT_READ_SUFFIXES,
    allow_create: bool = False,
) -> Path:
    """Resolve a user-supplied path and reject traversal, secrets, and oversize files."""
    if not user_path or not str(user_path).strip():
        raise SandboxError("path is empty")
    if "\x00" in user_path:
        raise SandboxError("path contains a null byte")

    root = sandbox_root()
    raw = Path(user_path)
    candidate = raw.resolve() if raw.is_absolute() else (root / user_path).resolve()

    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise SandboxError(f"path escapes sandbox: {user_path}") from exc

    if _is_blocked(candidate):
        raise SandboxError(f"blocked path: {user_path}")

    suffix = candidate.suffix.lower()
    if allowed_suffixes is not None and suffix and suffix not in allowed_suffixes:
        raise SandboxError(f"file type not allowed: {suffix}")

    if must_exist and not candidate.exists():
        raise SandboxError(f"file not found in sandbox: {user_path}")

    if candidate.exists() and candidate.is_file():
        size = candidate.stat().st_size
        if size > MAX_FILE_BYTES:
            raise SandboxError(
                f"file exceeds size limit ({size} > {MAX_FILE_BYTES} bytes)"
            )
        if candidate.is_symlink():
            # resolve() already followed it; double-check the link target stays inside.
            try:
                candidate.resolve().relative_to(root)
            except ValueError as exc:
                raise SandboxError("symlink escapes sandbox") from exc
    elif must_exist:
        raise SandboxError(f"not a file: {user_path}")
    elif not allow_create and not candidate.exists():
        raise SandboxError(f"file not found in sandbox: {user_path}")

    return candidate


def write_bytes(job_dir: Path, filename: str, data: bytes) -> Path:
    if len(data) > MAX_FILE_BYTES:
        raise SandboxError(f"upload exceeds size limit ({len(data)} > {MAX_FILE_BYTES} bytes)")
    target = resolve_sandbox_path(
        str(job_dir / safe_filename(filename)),
        must_exist=False,
        allow_create=True,
        allowed_suffixes=DEFAULT_READ_SUFFIXES | {".bin"},
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


async def run_with_timeout(awaitable: Awaitable[T], *, name: str = "tool") -> T:
    timeout = TOOL_TIMEOUT_SEC
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise SandboxError(f"tool {name} timed out after {timeout}s") from exc


def relative_to_sandbox(path: Path) -> str:
    return path.resolve().relative_to(sandbox_root()).as_posix()

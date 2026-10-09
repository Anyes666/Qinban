"""Shared primitives for the local-only Luna score harness."""
from __future__ import annotations

import ctypes
import hashlib
import json
import math
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from jsonschema import Draft202012Validator


class HarnessError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


INVALID = -1
FILE_ATTRIBUTE_REPARSE_POINT = 0x0400
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$")
SHA256 = re.compile(r"^[A-Fa-f0-9]{64}$")


def now_local_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="milliseconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise HarnessError("DUPLICATE_JSON_KEY", f"duplicate JSON property: {key}")
        result[key] = value
    return result


def _reject_constant(token: str) -> None:
    raise HarnessError("NON_FINITE_JSON", f"non-finite JSON number: {token}")


def _check_json_depth(value: Any, max_depth: int = 32) -> None:
    pending: list[tuple[Any, int]] = [(value, 0)]
    while pending:
        current, depth = pending.pop()
        if depth > max_depth:
            raise HarnessError("JSON_DEPTH", f"JSON exceeds depth {max_depth}")
        if isinstance(current, dict):
            pending.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            pending.extend((item, depth + 1) for item in current)
        elif type(current) is float and not math.isfinite(current):
            raise HarnessError("NON_FINITE_JSON", "non-finite JSON number")


def loads_strict(text: str, *, max_depth: int = 32) -> Any:
    try:
        value = json.loads(text, object_pairs_hook=_reject_duplicate_pairs, parse_constant=_reject_constant)
    except HarnessError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise HarnessError("INVALID_JSON", str(exc)) from exc
    _check_json_depth(value, max_depth=max_depth)
    return value


def load_json_strict(path: Path, *, max_depth: int = 32) -> Any:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise HarnessError("READ_FAILED", f"cannot read {path}: {exc}") from exc
    return loads_strict(text, max_depth=max_depth)


def json_for_file(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def write_json_once(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json_for_file(value))
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise HarnessError("EVIDENCE_EXISTS", f"refusing to overwrite evidence: {path}") from exc


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(json_for_file(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def write_text_once(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise HarnessError("EVIDENCE_EXISTS", f"refusing to overwrite evidence: {path}") from exc


def validate_schema(value: Any, schema_path: Path) -> list[str]:
    schema = load_json_strict(schema_path)
    try:
        validator = Draft202012Validator(schema)
        validator.check_schema(schema)
    except Exception as exc:
        raise HarnessError("SCHEMA_INVALID", f"invalid schema {schema_path}: {exc}") from exc
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.absolute_path))
    return [f"{'/'.join(str(part) for part in error.absolute_path) or '$'}: {error.message}" for error in errors]


def assert_schema(value: Any, schema_path: Path, code: str) -> None:
    errors = validate_schema(value, schema_path)
    if errors:
        raise HarnessError(code, "; ".join(errors[:8]))


def ensure_safe_relative(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HarnessError("BAD_RELATIVE_PATH", f"{label} must be non-empty")
    if value.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", value):
        raise HarnessError("BAD_RELATIVE_PATH", f"{label} must not be absolute")
    if "\\" in value or "\x00" in value or "\r" in value or "\n" in value:
        raise HarnessError("BAD_RELATIVE_PATH", f"{label} contains a forbidden character")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise HarnessError("BAD_RELATIVE_PATH", f"{label} contains traversal or empty components")
    return "/".join(parts)


def is_reparse_point(path: Path) -> bool:
    try:
        if os.name == "nt":
            attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))  # type: ignore[attr-defined]
            return attrs != INVALID and bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT)
        return path.is_symlink()
    except (AttributeError, OSError):
        return True


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def resolve_contained(base: Path, relative: str | Path, *, label: str, must_exist: bool, allow_absolute: bool = False, reject_reparse: bool = True) -> Path:
    base = base.resolve(strict=True)
    if reject_reparse and is_reparse_point(base):
        raise HarnessError("REPARSE_BASE", f"base path is a symlink/junction: {base}")
    candidate_input = Path(relative)
    if candidate_input.is_absolute():
        if not allow_absolute:
            raise HarnessError("BAD_RELATIVE_PATH", f"{label} must be relative")
        candidate = candidate_input
    else:
        candidate = base / candidate_input
    try:
        resolved = candidate.resolve(strict=must_exist)
    except OSError as exc:
        raise HarnessError("PATH_RESOLVE_FAILED", f"cannot resolve {label}: {exc}") from exc
    if not _is_relative_to(resolved, base) or resolved == base:
        raise HarnessError("PATH_OUTSIDE_ROOT", f"{label} escapes {base}: {relative}")
    if reject_reparse:
        current = base
        for part in resolved.relative_to(base).parts:
            current = current / part
            if current.exists() or current.is_symlink():
                if is_reparse_point(current):
                    raise HarnessError("REPARSE_COMPONENT", f"{label} crosses symlink/junction: {current}")
    if must_exist and not resolved.is_file():
        raise HarnessError("NOT_A_FILE", f"{label} is not a regular file: {resolved}")
    return resolved


def relative_posix(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError as exc:
        raise HarnessError("PATH_OUTSIDE_ROOT", f"cannot make relative path {path} under {base}") from exc


def pid_is_alive(pid: Any) -> bool:
    if type(pid) is not int or pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def canonical_input_snapshot(task: Mapping[str, Any], actual_artifacts: Iterable[Mapping[str, str]]) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "taskId": task["taskId"],
        "batchId": task["batchId"],
        "action": task["action"],
        "dataKind": task["dataKind"],
        "metadata": task["metadata"],
        "inputArtifacts": [{"kind": x["kind"], "path": x["path"], "sha256": x["sha256"].upper()} for x in actual_artifacts],
        "policySha256": task["policySha256"].upper(),
        "mayWriteLiveCatalog": False,
    }


def contract_hashes(contract_root: Path) -> dict[str, str]:
    return {
        "policySha256": sha256_file(contract_root / "policy.json"),
        "taskSchemaSha256": sha256_file(contract_root / "task.schema.json"),
        "resultSchemaSha256": sha256_file(contract_root / "result.schema.json"),
    }

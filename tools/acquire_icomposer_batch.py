"""\u9694\u79bb\u7684 iComposer \u4e2d\u6587\u6d41\u884c\u7ed3\u6784\u5316\u8c31\u5019\u9009\u91c7\u96c6\u5668\u3002

\u9ed8\u8ba4\u53ea\u505a dry-run\u3002\u7f51\u7edc\u6a21\u5f0f\u901a\u8fc7 GitHub API \u56fa\u5b9a commit/tree\uff0c\u518d\u7528 Contents API
\u8bfb\u53d6\u786e\u5b9a\u6027\u6392\u5e8f\u7684 lyrics_note/lyrics_duration \u6587\u672c\uff1b\u4e0d\u4e0b\u8f7d\u97f3\u9891\uff0c\u4e0d\u89e6\u78b0 Songs\u3001UserData\u3001EXE\u3001C# \u6216\u6e38\u620f\u8f93\u5165\u3002\u4ea7\u7269\u6c38\u8fdc\u662f research candidate\uff0c\u4e0d\u662f\u751f\u4ea7\u5185\u7f6e\u6b4c\u66f2\u3002"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

REPO = "hhpslily/iComposer"
API_ROOT = f"https://api.github.com/repos/{REPO}"
NOTE_DIR = "dataset/lyrics_note"
DURATION_DIR = "dataset/lyrics_duration"
VERSION_LABEL = "iComposer\u7814\u7a76\u6570\u636e\u8f6c\u5f55\u5019\u9009"
LICENSE = "dataset-license-not-stated"
RIGHTS_STATUS = "candidate-unverified"
BATCH_KIND = "icomposer-structured-candidate-intake"
HEX40_RE = re.compile(r"^[0-9a-fA-F]{40}$")
NOTE_TOKEN_RE = re.compile(r"^[0-9]+(?:,[0-9]+)*$")


class IntakeError(RuntimeError):
    """\u53ef\u5411\u7528\u6237\u62a5\u544a\u7684\u91c7\u96c6/\u89e3\u6790\u9519\u8bef\u3002"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def git_blob_sha1(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def _slug(value: str) -> str:
    text = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", value.strip()).strip("-")
    return text[:80] or "untitled"


def _http_json(url: str) -> Any:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Codex-iComposer-research-candidate",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise IntakeError(f"GitHub API HTTP {exc.code} for {url}: {body}") from exc
    except URLError as exc:
        raise IntakeError(f"GitHub API network error for {url}: {exc.reason}") from exc
    except (TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise IntakeError(f"GitHub API read failure for {url}: {exc}") from exc


def _contents_url(path: str, commit_sha: str) -> str:
    return f"{API_ROOT}/contents/{quote(path, safe='/')}?{urlencode({'ref': commit_sha})}"


def _parse_content_response(payload: dict[str, Any], api_url: str) -> tuple[bytes, dict[str, Any]]:
    if payload.get("type") != "file":
        raise IntakeError(f"Contents API did not return a file: {api_url}")
    content = payload.get("content")
    if not isinstance(content, str) or payload.get("encoding") != "base64":
        raise IntakeError(f"Contents API returned unsupported encoding: {api_url}")
    try:
        data = base64.b64decode(content, validate=False)
    except (ValueError, TypeError) as exc:
        raise IntakeError(f"invalid base64 content: {api_url}") from exc
    return data, payload


def _clean_lines(data: bytes) -> list[str]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise IntakeError(f"file is not valid UTF-8: {exc}") from exc
    return [line.strip() for line in text.splitlines() if line.strip()]


def _decimal(value: str, field: str) -> Decimal:
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise IntakeError(f"{field} is not numeric: {value!r}") from exc
    if not result.is_finite() or result <= 0:
        raise IntakeError(f"{field} must be a finite positive number: {value!r}")
    return result


def _number(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def _parse_rows(data: bytes, *, kind: str) -> list[tuple[str, list[str]]]:
    lines = _clean_lines(data)
    if not lines:
        raise IntakeError(f"{kind} file is empty")
    if len(lines) % 2:
        raise IntakeError(f"{kind} file has an incomplete lyric/value pair")
    rows: list[tuple[str, list[str]]] = []
    for index in range(0, len(lines), 2):
        lyric = lines[index]
        values = lines[index + 1].split()
        if not lyric or not values:
            raise IntakeError(f"{kind} file has an empty row at line {index + 1}")
        rows.append((lyric, values))
    return rows


def _parse_note_values(values: Iterable[str], row_number: int) -> list[list[int]]:
    parsed: list[list[int]] = []
    for token in values:
        if not NOTE_TOKEN_RE.fullmatch(token):
            raise IntakeError(f"note format rejected at row {row_number}: {token!r}")
        pitches = [int(part) for part in token.split(",")]
        if any(pitch < 0 or pitch > 127 for pitch in pitches):
            raise IntakeError(f"note pitch out of MIDI range at row {row_number}: {token!r}")
        parsed.append(pitches)
    return parsed


def parse_song_payload(
    title: str,
    note_bytes: bytes,
    duration_bytes: bytes,
    *,
    source_sha256: str,
    note_sha256: str,
    note_url: str,
    duration_url: str,
    source_commit: str,
    source_tree: str,
    provider: str = "iComposer",
    retrieved_at: str,
    git_note_sha: str = "",
    git_duration_sha: str = "",
) -> dict[str, Any]:
    """\u4e25\u683c\u89e3\u6790\u4e00\u5bf9 iComposer \u6587\u672c\uff1b\u4efb\u4f55\u6b67\u4e49\u90fd\u62d2\u7edd\u800c\u4e0d\u4f2a\u9020\u97f3\u7b26\u3002"""
    note_rows = _parse_rows(note_bytes, kind="lyrics_note")
    duration_rows = _parse_rows(duration_bytes, kind="lyrics_duration")
    if len(note_rows) != len(duration_rows):
        raise IntakeError("note/duration lyric-row count mismatch")

    events: list[dict[str, Any]] = []
    cursor = Decimal("0")
    for row_number, ((note_lyric, note_values), (duration_lyric, duration_values)) in enumerate(
        zip(note_rows, duration_rows), start=1
    ):
        if note_lyric != duration_lyric:
            raise IntakeError(f"lyrics mismatch at row {row_number}")
        pitches = _parse_note_values(note_values, row_number)
        if len(pitches) != len(duration_values):
            raise IntakeError(f"note/duration token count mismatch at row {row_number}")
        lyric_tokens = note_lyric.split()
        if len(lyric_tokens) != len(pitches):
            raise IntakeError(
                f"lyric/note token count mismatch at row {row_number}; refusing unaligned candidate"
            )
        for lyric_token, pitch_group, duration_token in zip(lyric_tokens, pitches, duration_values):
            duration = _decimal(duration_token, f"duration row {row_number}")
            events.append(
                {
                    "lyric": lyric_token,
                    "pitches": pitch_group,
                    "start": _number(cursor),
                    "duration": _number(duration),
                }
            )
            cursor += duration

    if not events:
        raise IntakeError("structured candidate contains no note events")
    work_id = f"icomposer-{_slug(title)}"
    edition_id = f"{work_id}-{source_sha256[:12].lower()}"
    return {
        "WorkId": work_id,
        "EditionId": edition_id,
        "VersionLabel": VERSION_LABEL,
        "Provider": provider,
        "Title": title,
        "LanguageStatus": "unknown",
        "RegionStatus": "unknown",
        "SourceSha256": source_sha256,
        "NotationSha256": canonical_sha256(events),
        "SourceUrl": note_url,
        "DurationSourceUrl": duration_url,
        "License": LICENSE,
        "RightsStatus": RIGHTS_STATUS,
        "redistributionVerified": False,
        "MusicReview": "research-candidate-unreviewed",
        "GameReview": "not-tested-in-game",
        "ResearchCandidate": True,
        "ProductionBuiltin": False,
        "notes": events,
        "totalDuration": _number(cursor),
        "source": {
            "sourceCommit": source_commit,
            "sourceTree": source_tree,
            "retrievedAt": retrieved_at,
            "noteApiUrl": note_url,
            "durationApiUrl": duration_url,
            "noteGitBlobSha": git_note_sha,
            "durationGitBlobSha": git_duration_sha,
            "noteDownloadSha256": note_sha256,
            "durationDownloadSha256": sha256_bytes(duration_bytes),
            "noteDownloadBytes": len(note_bytes),
            "durationDownloadBytes": len(duration_bytes),
        },
    }


def _resolve_network_source(source_commit: str | None) -> dict[str, Any]:
    ref = source_commit or "master"
    commit_url = f"{API_ROOT}/commits/{quote(ref, safe='')}"
    commit_payload = _http_json(commit_url)
    commit_sha = str(commit_payload.get("sha", ""))
    tree_sha = str(((commit_payload.get("commit") or {}).get("tree") or {}).get("sha", ""))
    if not HEX40_RE.fullmatch(commit_sha) or not HEX40_RE.fullmatch(tree_sha):
        raise IntakeError(f"GitHub commit response lacks valid commit/tree SHA: {commit_url}")
    tree_url = f"{API_ROOT}/git/trees/{tree_sha}?recursive=1"
    tree_payload = _http_json(tree_url)
    if tree_payload.get("sha") != tree_sha:
        raise IntakeError("GitHub tree SHA changed between commit and tree API responses")
    tree_paths = [str(item.get("path", "")) for item in tree_payload.get("tree", [])]
    license_files = sorted(
        path for path in tree_paths if Path(path).name.casefold().startswith("license")
    )
    return {
        "mode": "network",
        "commit": commit_sha,
        "tree": tree_sha,
        "commitApiUrl": commit_url,
        "treeApiUrl": tree_url,
        "licenseFiles": license_files,
        "readmePresent": "README.md" in tree_paths,
        "noteDirectoryUrl": f"{API_ROOT}/contents/{NOTE_DIR}?{urlencode({'ref': commit_sha})}",
        "durationDirectoryUrl": f"{API_ROOT}/contents/{DURATION_DIR}?{urlencode({'ref': commit_sha})}",
    }


def _fixture_source(fixture_dir: Path, source_commit: str | None) -> dict[str, Any]:
    note_dir = fixture_dir / NOTE_DIR
    duration_dir = fixture_dir / DURATION_DIR
    if not note_dir.is_dir() or not duration_dir.is_dir():
        raise IntakeError(f"fixture must contain {NOTE_DIR} and {DURATION_DIR}: {fixture_dir}")
    commit = source_commit or "fixture-commit"
    tree = "fixture-tree-" + sha256_bytes(
        "\n".join(
            sorted(
                str(path.relative_to(fixture_dir)).replace("\\", "/")
                for path in fixture_dir.rglob("*")
                if path.is_file()
            )
        ).encode("utf-8")
    )[:40]
    license_files = sorted(
        str(path.relative_to(fixture_dir)).replace("\\", "/")
        for path in fixture_dir.rglob("*")
        if path.is_file() and path.name.casefold().startswith("license")
    )
    return {
        "mode": "fixture",
        "commit": commit,
        "tree": tree,
        "commitApiUrl": f"fixture://{fixture_dir.as_posix()}/commit",
        "treeApiUrl": f"fixture://{fixture_dir.as_posix()}/tree",
        "licenseFiles": license_files,
        "readmePresent": (fixture_dir / "README.md").is_file(),
        "noteDirectoryUrl": f"fixture://{fixture_dir.as_posix()}/{NOTE_DIR}",
        "durationDirectoryUrl": f"fixture://{fixture_dir.as_posix()}/{DURATION_DIR}",
    }


def _network_files(source: dict[str, Any], count: int) -> list[dict[str, Any]]:
    commit = source["commit"]
    note_listing_url = source["noteDirectoryUrl"]
    duration_listing_url = source["durationDirectoryUrl"]
    note_listing = _http_json(note_listing_url)
    duration_listing = _http_json(duration_listing_url)
    if not isinstance(note_listing, list) or not isinstance(duration_listing, list):
        raise IntakeError("GitHub Contents API directory response is not a list")
    duration_by_name = {str(item.get("name")): item for item in duration_listing}
    selected = sorted(
        (item for item in note_listing if item.get("type") == "file" and str(item.get("name", "")).endswith(".txt")),
        key=lambda item: (str(item.get("name", "")).casefold(), str(item.get("name", ""))),
    )[:count]
    rows: list[dict[str, Any]] = []
    for note_item in selected:
        name = str(note_item.get("name"))
        duration_item = duration_by_name.get(name)
        if duration_item is None:
            rows.append({"name": name, "rejection": "missing matching lyrics_duration file"})
            continue
        note_url = str(note_item.get("url") or _contents_url(f"{NOTE_DIR}/{name}", commit))
        duration_url = str(duration_item.get("url") or _contents_url(f"{DURATION_DIR}/{name}", commit))
        note_bytes, note_meta = _parse_content_response(_http_json(note_url), note_url)
        duration_bytes, duration_meta = _parse_content_response(_http_json(duration_url), duration_url)
        rows.append(
            {
                "name": name,
                "title": Path(name).stem,
                "noteBytes": note_bytes,
                "durationBytes": duration_bytes,
                "noteMeta": note_meta,
                "durationMeta": duration_meta,
                "noteUrl": note_url,
                "durationUrl": duration_url,
            }
        )
    return rows


def _fixture_files(source: dict[str, Any], fixture_dir: Path, count: int) -> list[dict[str, Any]]:
    note_dir = fixture_dir / NOTE_DIR
    duration_dir = fixture_dir / DURATION_DIR
    selected = sorted(
        (path for path in note_dir.glob("*.txt") if path.is_file()),
        key=lambda path: (path.name.casefold(), path.name),
    )[:count]
    rows: list[dict[str, Any]] = []
    for note_path in selected:
        duration_path = duration_dir / note_path.name
        if not duration_path.is_file():
            rows.append({"name": note_path.name, "rejection": "missing matching lyrics_duration file"})
            continue
        note_bytes = note_path.read_bytes()
        duration_bytes = duration_path.read_bytes()
        rows.append(
            {
                "name": note_path.name,
                "title": note_path.stem,
                "noteBytes": note_bytes,
                "durationBytes": duration_bytes,
                "noteMeta": {"sha": git_blob_sha1(note_bytes)},
                "durationMeta": {"sha": git_blob_sha1(duration_bytes)},
                "noteUrl": f"fixture://{fixture_dir.as_posix()}/{NOTE_DIR}/{quote(note_path.name)}",
                "durationUrl": f"fixture://{fixture_dir.as_posix()}/{DURATION_DIR}/{quote(duration_path.name)}",
            }
        )
    return rows


def _write_new(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise IntakeError(f"refusing to overwrite existing output: {path}")
    path.write_text(data, encoding="utf-8", newline="\n")


def _build_readme(source: dict[str, Any], accepted: int, rejected: int) -> str:
    return f"""# iComposer \u7ed3\u6784\u5316\u8c31\u5019\u9009\u6279\u6b21\n\n\u8fd9\u662f\u4e00\u4e2a\u9694\u79bb\u7684 **research candidate** \u6279\u6b21\uff0c\u4e0d\u662f\u751f\u4ea7\u5185\u7f6e\u6b4c\u66f2\uff0c\u4e0d\u662f\u539f\u5531\u7248\u672c\uff0c\u4e5f\u672a\u5b89\u88c5\u5230 `Songs`\u3002\n\n- Provider\uff1aiComposer\n- VersionLabel\uff1a{VERSION_LABEL}\n- Source commit\uff1a`{source['commit']}`\n- Source tree\uff1a`{source['tree']}`\n- License\uff1a`{LICENSE}`\n- RightsStatus\uff1a`{RIGHTS_STATUS}`\n- redistributionVerified\uff1afalse\n- LanguageStatus / RegionStatus\uff1a\u672a\u7531\u6765\u6e90\u9010\u66f2\u58f0\u660e\u65f6\u4fdd\u6301 `unknown`\n- accepted\uff1a{accepted}\n- rejected\uff1a{rejected}\n\n## \u8fb9\u754c\n\n\u672c\u6279\u6b21\u53ea\u8bfb\u53d6 GitHub Contents API \u4e2d\u786e\u5b9a\u6027\u6392\u5e8f\u7684 `dataset/lyrics_note` \u4e0e\n`dataset/lyrics_duration` \u6587\u672c\uff0c\u672a\u4e0b\u8f7d\u97f3\u9891\u6216\u5f55\u97f3\u3002\u683c\u5f0f\u4e0d\u4e00\u81f4\u3001\u65e0\u6cd5\u9010\u97f3\u7b26\u5bf9\u9f50\u3001\u53ea\u6709\u6b4c\u8bcd\u6587\u672c\u6216\u7f3a\u5c11\u5bf9\u5e94 duration \u7684\u6761\u76ee\u5747\u62d2\u7edd\uff0c\u4e0d\u4f2a\u9020\u97f3\u7b26\u3002\n\n\u8bf7\u5148\u4eba\u5de5\u97f3\u4e50\u5ba1\u9605\u3001\u6743\u5229\u6838\u67e5\u548c\u6e38\u620f\u5916\u9a8c\u8bc1\uff1b`MusicReview` \u4e0e `GameReview` \u5b57\u6bb5\u4e0d\u4f1a\u628a\u7814\u7a76\u5019\u9009\u5ba3\u79f0\u4e3a\u53ef\u64ad\u653e\u3001\u53ef\u5206\u53d1\u6216\u751f\u4ea7\u5c31\u7eea\u3002\n"""


def run_acquisition(
    *,
    output_dir: Path | None = None,
    count: int = 10,
    seed: int = 0,
    provider: str = "iComposer",
    source_commit: str | None = None,
    no_network: bool = False,
    fixture_dir: Path | None = None,
    write: bool = False,
    retrieval_time: str | None = None,
) -> dict[str, Any]:
    if count <= 0:
        raise IntakeError("count must be positive; empty batch is rejected")
    if seed != 0:
        # ????????????seed ??????????????????
        pass
    if no_network:
        if fixture_dir is None:
            raise IntakeError("--no-network requires --fixture-dir")
        source = _fixture_source(Path(fixture_dir), source_commit)
        rows = _fixture_files(source, Path(fixture_dir), count)
        retrieved_at = retrieval_time or "1970-01-01T00:00:00+00:00"
    else:
        source = _resolve_network_source(source_commit)
        rows = _network_files(source, count)
        retrieved_at = retrieval_time or utc_now()

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    for row in rows:
        if row.get("rejection"):
            rejected.append({"name": row["name"], "reason": row["rejection"]})
            continue
        try:
            note_bytes = row["noteBytes"]
            duration_bytes = row["durationBytes"]
            accepted.append(
                parse_song_payload(
                    row["title"],
                    note_bytes,
                    duration_bytes,
                    source_sha256=sha256_bytes(note_bytes),
                    note_sha256=sha256_bytes(note_bytes),
                    note_url=row["noteUrl"],
                    duration_url=row["durationUrl"],
                    source_commit=source["commit"],
                    source_tree=source["tree"],
                    provider=provider,
                    retrieved_at=retrieved_at,
                    git_note_sha=str(row["noteMeta"].get("sha", "")),
                    git_duration_sha=str(row["durationMeta"].get("sha", "")),
                )
            )
        except IntakeError as exc:
            rejected.append({"name": row["name"], "reason": str(exc)})

    if not accepted:
        raise IntakeError(
            "empty batch rejected: no structurally valid candidates; "
            + json.dumps(rejected, ensure_ascii=False, sort_keys=True)
        )

    manifest_entries = []
    references_entries = []
    for entry in accepted:
        manifest_entries.append({key: entry[key] for key in (
            "WorkId", "EditionId", "VersionLabel", "Provider", "Title", "LanguageStatus",
            "RegionStatus", "SourceSha256", "NotationSha256", "SourceUrl", "License",
            "RightsStatus", "redistributionVerified", "MusicReview", "GameReview",
            "ResearchCandidate", "ProductionBuiltin",
        )})
        references_entries.append({
            "WorkId": entry["WorkId"],
            "EditionId": entry["EditionId"],
            "SourceUrl": entry["SourceUrl"],
            "DurationSourceUrl": entry["DurationSourceUrl"],
            "Source": entry["source"],
            "Notes": entry["notes"],
            "TotalDuration": entry["totalDuration"],
        })

    source_audit = {
        "schemaVersion": "icomposer-source-audit/v1",
        "batchKind": BATCH_KIND,
        "retrievalTime": retrieved_at,
        "seed": seed,
        "countRequested": count,
        "countAccepted": len(accepted),
        "countRejected": len(rejected),
        "source": source,
        "license": LICENSE,
        "rightsStatus": RIGHTS_STATUS,
        "redistributionVerified": False,
        "rejections": rejected,
        "networkErrorsAreFatal": True,
        "audioDownloaded": False,
        "productionBuiltin": False,
    }
    manifest = {
        "schemaVersion": "icomposer-intake-manifest/v1",
        "batchKind": BATCH_KIND,
        "VersionLabel": VERSION_LABEL,
        "Provider": provider,
        "sourceCommit": source["commit"],
        "sourceTree": source["tree"],
        "entries": manifest_entries,
    }
    references = {
        "schemaVersion": "icomposer-references/v1",
        "entries": references_entries,
    }
    result = {
        "manifest": manifest,
        "references": references,
        "sourceAudit": source_audit,
        "readme": _build_readme(source, len(accepted), len(rejected)),
        "accepted": accepted,
        "rejected": rejected,
        "reportSha256": canonical_sha256({"manifest": manifest, "references": references, "sourceAudit": source_audit}),
    }
    if write:
        if output_dir is None:
            raise IntakeError("--write requires --output-dir")
        target = Path(output_dir)
        _write_new(target / "manifest.json", canonical_json(manifest))
        _write_new(target / "references.json", canonical_json(references))
        _write_new(target / "source-audit.json", canonical_json(source_audit))
        _write_new(target / "README.md", result["readme"])
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="\u9694\u79bb\u91c7\u96c6 iComposer \u7ed3\u6784\u5316\u8c31\u7814\u7a76\u5019\u9009")
    parser.add_argument("--output-dir", type=Path, help="\u5199\u5165 manifest/references/source-audit/README \u7684\u76ee\u5f55")
    parser.add_argument("--count", type=int, default=10, help="\u786e\u5b9a\u6027\u6392\u5e8f\u540e\u6700\u591a\u8bfb\u53d6\u7684 note \u6587\u4ef6\u6570")
    parser.add_argument("--seed", type=int, default=0, help="\u4ec5\u8bb0\u5f55\uff1b\u91c7\u96c6\u987a\u5e8f\u4e0d\u4f7f\u7528\u968f\u673a\u62bd\u6837")
    parser.add_argument("--provider", default="iComposer")
    parser.add_argument("--source-commit", help="GitHub ref \u6216 commit SHA\uff1b\u7f51\u7edc\u6a21\u5f0f\u4f1a\u7531 API \u89e3\u6790\u4e3a\u56fa\u5b9a commit/tree")
    parser.add_argument("--no-network", action="store_true", help="\u4f7f\u7528 --fixture-dir \u7684\u672c\u5730\u5939\u5177\uff0c\u4e0d\u8bbf\u95ee\u7f51\u7edc")
    parser.add_argument("--fixture-dir", type=Path, help="no-network \u5939\u5177\u6839\u76ee\u5f55")
    parser.add_argument("--write", action="store_true", help="\u660e\u786e\u5141\u8bb8\u5199\u5165 output-dir\uff1b\u9ed8\u8ba4 dry-run")
    parser.add_argument("--dry-run", action="store_true", help="\u9ed8\u8ba4\u884c\u4e3a\uff1a\u53ea\u91c7\u96c6/\u89e3\u6790/\u62a5\u544a\uff0c\u4e0d\u5199\u6587\u4ef6")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = run_acquisition(
            output_dir=args.output_dir,
            count=args.count,
            seed=args.seed,
            provider=args.provider,
            source_commit=args.source_commit,
            no_network=args.no_network,
            fixture_dir=args.fixture_dir,
            write=args.write and not args.dry_run,
        )
    except IntakeError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "mode": "dry-run" if not (args.write and not args.dry_run) else "write",
        "accepted": len(result["accepted"]),
        "rejected": len(result["rejected"]),
        "reportSha256": result["reportSha256"],
        "sourceCommit": result["sourceAudit"]["source"]["commit"],
        "sourceTree": result["sourceAudit"]["source"]["tree"],
        "productionBuiltin": False,
        "researchCandidate": True,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


"""审计并生成 midi_lyric_corpus 中文 MIDI+歌词候选 intake。

本工具只读本地来源目录，确定性配对 ``*.MID`` 与 ``*.txt``，输出审计清单和
候选元数据。它不会复制或改写 ``Songs``、``UserData``、EXE，也不会进入生产
曲库，更不会向真实游戏窗口发送输入。

输入目录由命令行参数提供。例如：

    python tools/acquire_midi_lyric_corpus_batch.py `
        D:\path\midi_lyric_corpus\data `
        --limit 100 `
        --output catalog-intake\midi-lyric-corpus-2026-10-07

输出是一个新的目录；已有目录一律拒绝覆盖。输出文件和控制台均使用 UTF-8。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
PROVIDER = "midi_lyric_corpus"
SCHEMA_VERSION = "midi-lyric-corpus-intake-v1"
BATCH_KIND = "midi-lyric-corpus-zh-candidate-intake"
RIGHTS_STATUS = "candidate-unverified"
REDISTRIBUTION_VERIFIED = False

_HEADER_TITLE_KEYS = {
    "title",
    "song",
    "songname",
    "name",
    "tracktitle",
    "歌名",
    "歌曲",
    "标题",
    "曲名",
}
_HEADER_ARTIST_KEYS = {
    "artist",
    "singer",
    "performer",
    "vocal",
    "演唱",
    "歌手",
    "艺人",
}
_HEADER_LANGUAGE_KEYS = {
    "lang",
    "language",
    "langualer",  # midi_lyric_corpus 原始字段的拼写
    "语言",
    "语种",
}
_PREAMBLE_RE = re.compile(r"^(?:OKPLAY\b|MIDI\b)", re.IGNORECASE)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_CANTONESE_RE = re.compile(r"粤语|粵語|广东话|廣東話|cantonese|cantopop|\byue\b", re.IGNORECASE)
_CHINESE_DECL_RE = re.compile(r"中文|汉语|漢語|普通话|普通話|国语|國語|mandarin|chinese|中国|中國|\bchina\b", re.IGNORECASE)
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


class IntakeError(RuntimeError):
    """可向用户报告的 intake 错误。"""


@dataclass(frozen=True)
class Pair:
    key: str
    midi: Path
    lyrics: Path
    midi_relative: str
    lyrics_relative: str


@dataclass(frozen=True)
class SourceContext:
    root: Path
    git_root: Path | None
    source_url: str
    source_commit: str
    remote_url: str | None
    source_declaration: dict[str, Any]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", value.strip()))


def _normalize_key(value: str) -> str:
    return re.sub(r"[\s_\-]+", "", unicodedata.normalize("NFC", value.strip())).casefold()


def _slug(value: str) -> str:
    text = unicodedata.normalize("NFC", value).strip()
    text = re.sub(r"[^0-9A-Za-z\u3400-\u9fff]+", "-", text).strip("-")
    return text[:96] or "untitled"


def _ensure_within(path: Path, root: Path) -> Path:
    """解析路径并确保真实路径仍在 root 内，拒绝符号链接越界。"""
    root_resolved = root.resolve(strict=True)
    candidate = path.resolve(strict=False)
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise IntakeError(f"source path escapes source root: {path}") from exc
    return candidate


def _ensure_source_root(source: Path) -> Path:
    root = Path(source).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise IntakeError(f"source must be a directory: {root}")
    return root


def _ensure_output_is_safe(output: Path, source_root: Path) -> Path:
    target = Path(output).expanduser().resolve(strict=False)
    if target == source_root or source_root in target.parents:
        raise IntakeError(f"output must not be inside source root: {target}")
    for protected_name in ("Songs", "UserData"):
        protected = ROOT / protected_name
        if target == protected or protected in target.parents:
            raise IntakeError(f"output path is protected and cannot be written: {target}")
    if target.exists():
        raise IntakeError(f"refusing to overwrite existing output: {target}")
    return target


def _read_utf8(path: Path) -> tuple[str, str]:
    data = path.read_bytes()
    try:
        return data.decode("utf-8-sig"), "utf-8-sig"
    except UnicodeDecodeError as exc:
        raise IntakeError(f"not valid UTF-8: {path}: {exc}") from exc


def _run_git(source_root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(source_root), *args],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, UnicodeError):
        return None
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value or None


def _find_git_root(source_root: Path) -> Path | None:
    raw = _run_git(source_root, "rev-parse", "--show-toplevel")
    if not raw:
        return None
    candidate = Path(raw).resolve(strict=False)
    return candidate if candidate.is_dir() else None


def _normalize_remote_url(remote: str | None) -> str | None:
    if not remote:
        return None
    value = remote.strip()
    if value.startswith("git@") and ":" in value:
        host_path = value[4:]
        value = "https://" + host_path
    elif value.startswith("ssh://git@"):
        value = "https://" + value[len("ssh://git@") :]
    if value.endswith(".git"):
        value = value[:-4]
    return value.rstrip("/")


def _relative_to_git(path: Path, source_root: Path, git_root: Path | None) -> str:
    resolved = path.resolve(strict=True)
    base = git_root if git_root and _is_within(resolved, git_root) else source_root
    return resolved.relative_to(base.resolve(strict=True)).as_posix()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True


def _file_url(repo_url: str, commit: str, relative_path: str) -> str:
    encoded = quote(relative_path.replace("\\", "/"), safe="/")
    return f"{repo_url.rstrip('/')}/blob/{quote(commit, safe='')}/{encoded}"


def _candidate_readmes(source_root: Path, git_root: Path | None) -> list[Path]:
    candidates: list[Path] = []
    for candidate in (
        source_root / "README.md",
        source_root.parent / "README.md",
        git_root / "README.md" if git_root else None,
    ):
        if candidate is None:
            continue
        resolved = candidate.resolve(strict=False)
        if resolved.is_file() and resolved not in candidates:
            candidates.append(resolved)
    return candidates


def _source_declaration(source_root: Path, git_root: Path | None) -> dict[str, Any]:
    files: list[dict[str, str]] = []
    text_parts: list[str] = []
    for readme in _candidate_readmes(source_root, git_root):
        try:
            text, encoding = _read_utf8(readme)
        except IntakeError:
            continue
        relative = _relative_to_git(readme, source_root, git_root)
        files.append({"path": relative, "encoding": encoding})
        text_parts.append(text)
    text = "\n".join(text_parts)
    tags: list[str] = []
    if _CANTONESE_RE.search(text):
        tags.append("yue")
    elif _CHINESE_DECL_RE.search(text):
        tags.append("zh")
    basis = [f"source-readme:{item['path']}" for item in files] if tags else []
    return {"languageTags": tags, "basis": basis, "readmeFiles": files}


def _source_context(source_root: Path, source_url: str | None, source_commit: str | None) -> SourceContext:
    git_root = _find_git_root(source_root)
    remote = _normalize_remote_url(_run_git(source_root, "config", "--get", "remote.origin.url"))
    resolved_url = _normalize_remote_url(source_url) or remote or f"local://{source_root.name}"
    resolved_commit = (source_commit or _run_git(source_root, "rev-parse", "HEAD") or "local-unpinned").strip()
    return SourceContext(
        root=source_root,
        git_root=git_root,
        source_url=resolved_url,
        source_commit=resolved_commit,
        remote_url=remote,
        source_declaration=_source_declaration(source_root, git_root),
    )


def _parse_lyric_document(text: str) -> dict[str, Any]:
    """解析 OKPLAY 风格头部；artist 的最后一个斜杠段作为歌手。"""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    header_fields: dict[str, str] = {}
    header_raw: list[str] = []
    header_indexes: set[int] = set()
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped:
            header_indexes.add(index)
            index += 1
            continue
        if _PREAMBLE_RE.match(stripped) and "=" not in stripped:
            header_raw.append(stripped)
            header_indexes.add(index)
            index += 1
            continue
        if "=" in stripped:
            key, value = stripped.split("=", 1)
            key = key.strip()
            if key and not _CONTROL_RE.search(key):
                normalized_key = _normalize_key(key)
                header_fields[normalized_key] = value.strip()
                header_raw.append(stripped)
                header_indexes.add(index)
                index += 1
                continue
        break

    plain = [(i, lines[i].strip()) for i in range(len(lines)) if i not in header_indexes and lines[i].strip()]
    explicit_title = next((v for k, v in header_fields.items() if k in _HEADER_TITLE_KEYS and v.strip()), None)
    explicit_artist = next((v for k, v in header_fields.items() if k in _HEADER_ARTIST_KEYS and v.strip()), None)

    consumed: set[int] = set()
    if explicit_title:
        title = _normalize_space(explicit_title)
        for line_index, value in plain:
            if _normalize_space(value) == title:
                consumed.add(line_index)
                break
    else:
        if not plain:
            raise IntakeError("lyrics text has no title/artist header")
        title_index, title_value = plain[0]
        title = _normalize_space(title_value)
        consumed.add(title_index)

    if not title:
        raise IntakeError("title is empty")
    if _CONTROL_RE.search(title):
        raise IntakeError("title contains a control character")

    remaining_plain = [(i, value) for i, value in plain if i not in consumed]
    if explicit_artist:
        artist_raw = explicit_artist.strip()
        for line_index, value in remaining_plain:
            if _normalize_space(value) == _normalize_space(artist_raw):
                consumed.add(line_index)
                break
        artist_index = max(consumed) if consumed else 0
    else:
        if not remaining_plain:
            raise IntakeError("lyrics text has no artist field")
        artist_index, artist_raw = remaining_plain[0]
        consumed.add(artist_index)
        artist_raw = artist_raw.strip()

    artist_raw = artist_raw.strip()
    if not artist_raw:
        raise IntakeError("artist field is empty")
    if _CONTROL_RE.search(artist_raw):
        raise IntakeError("artist contains a control character")
    artist_segments = [segment.strip() for segment in artist_raw.split("/")]
    non_empty_segments = [segment for segment in artist_segments if segment]
    artist = _normalize_space(non_empty_segments[-1] if non_empty_segments else artist_raw)
    if not artist:
        raise IntakeError("artist field has no usable final segment")

    lyric_lines = lines[artist_index + 1 :]
    lyrics_text = "\n".join(lyric_lines).strip()
    header_language_fields = {
        key: value
        for key, value in header_fields.items()
        if key in _HEADER_LANGUAGE_KEYS
    }
    return {
        "title": title,
        "artist": artist,
        "artistRaw": artist_raw,
        "artistSegments": artist_segments,
        "headerFields": header_fields,
        "headerRaw": header_raw,
        "languageFields": header_language_fields,
        "lyricsText": lyrics_text,
        "lyricsLineCount": len([line for line in lyric_lines if line.strip()]),
    }


def _language_tags(parsed: dict[str, Any], source_declaration: dict[str, Any]) -> tuple[list[str], list[str]]:
    header_text = " ".join(
        [f"{key}={value}" for key, value in parsed.get("languageFields", {}).items()]
    )
    lyrics_text = str(parsed.get("lyricsText", ""))
    if _CANTONESE_RE.search(header_text):
        return ["yue"], ["txt-header:explicit-cantonese-declaration"]
    if "yue" in source_declaration.get("languageTags", []):
        return ["yue"], list(source_declaration.get("basis", []))
    if _CHINESE_DECL_RE.search(header_text):
        return ["zh"], ["txt-header:explicit-chinese-declaration"]
    if "zh" in source_declaration.get("languageTags", []):
        return ["zh"], list(source_declaration.get("basis", []))
    if len(_CJK_RE.findall(lyrics_text)) >= 4:
        return ["zh"], ["lyrics:cjk-script"]
    return [], ["not-stated-by-lyrics-or-source"]


def _discover_pairs(source_root: Path) -> tuple[list[Pair], list[dict[str, Any]], dict[str, int]]:
    by_key: dict[str, dict[str, list[tuple[Path, str]]]] = defaultdict(lambda: {"midi": [], "lyrics": []})
    failures: list[dict[str, Any]] = []
    midi_count = 0
    lyrics_count = 0
    all_paths = sorted(
        (path for path in source_root.rglob("*") if path.is_file()),
        key=lambda path: path.as_posix().casefold(),
    )
    for path in all_paths:
        suffix = path.suffix.casefold()
        if suffix not in {".mid", ".txt"}:
            continue
        try:
            _ensure_within(path, source_root)
        except IntakeError as exc:
            failures.append(
                {
                    "kind": "source-path-outside-root",
                    "path": str(path),
                    "reason": str(exc),
                }
            )
            continue
        relative = path.relative_to(source_root).as_posix()
        key = relative[: -len(path.suffix)].casefold()
        kind = "midi" if suffix == ".mid" else "lyrics"
        by_key[key][kind].append((path, relative))
        if kind == "midi":
            midi_count += 1
        else:
            lyrics_count += 1

    pairs: list[Pair] = []
    duplicate_stem_count = 0
    for key in sorted(by_key):
        midi_items = sorted(by_key[key]["midi"], key=lambda item: item[1].casefold())
        lyrics_items = sorted(by_key[key]["lyrics"], key=lambda item: item[1].casefold())
        if len(midi_items) != 1 or len(lyrics_items) != 1:
            if len(midi_items) > 1:
                duplicate_stem_count += len(midi_items) - 1
                failures.append(
                    {
                        "kind": "duplicate-midi-stem",
                        "pairKey": key,
                        "paths": [item[1] for item in midi_items],
                    }
                )
            if len(lyrics_items) > 1:
                duplicate_stem_count += len(lyrics_items) - 1
                failures.append(
                    {
                        "kind": "duplicate-lyrics-stem",
                        "pairKey": key,
                        "paths": [item[1] for item in lyrics_items],
                    }
                )
            if len(midi_items) == 0 and lyrics_items:
                failures.append(
                    {
                        "kind": "missing-midi",
                        "pairKey": key,
                        "paths": [item[1] for item in lyrics_items],
                    }
                )
            if len(lyrics_items) == 0 and midi_items:
                failures.append(
                    {
                        "kind": "missing-lyrics",
                        "pairKey": key,
                        "paths": [item[1] for item in midi_items],
                    }
                )
            continue
        midi, midi_relative = midi_items[0]
        lyrics, lyrics_relative = lyrics_items[0]
        pairs.append(Pair(key, midi, lyrics, midi_relative, lyrics_relative))
    stats = {
        "midiFileCount": midi_count,
        "lyricsFileCount": lyrics_count,
        "pairedFileCount": len(pairs),
        "duplicateStemCount": duplicate_stem_count,
    }
    return pairs, failures, stats


def _work_id(title: str, artist: str) -> str:
    identity = f"{_normalize_space(title)}\n{_normalize_space(artist)}".encode("utf-8")
    return f"{PROVIDER}:work:{sha256_bytes(identity)[:20].lower()}"


def _build_entry(pair: Pair, context: SourceContext) -> dict[str, Any]:
    midi_resolved = _ensure_within(pair.midi, context.root)
    lyrics_resolved = _ensure_within(pair.lyrics, context.root)
    midi_bytes = midi_resolved.read_bytes()
    lyrics_bytes = lyrics_resolved.read_bytes()
    lyrics_text, lyrics_encoding = _read_utf8(lyrics_resolved)
    parsed = _parse_lyric_document(lyrics_text)
    language_tags, language_basis = _language_tags(parsed, context.source_declaration)
    source_sha = sha256_bytes(midi_bytes)
    lyrics_sha = sha256_bytes(lyrics_bytes)
    pair_sha = sha256_bytes(midi_bytes + b"\0" + lyrics_bytes)
    stem = pair.midi_relative[: -len(pair.midi.suffix)]
    work_id = _work_id(parsed["title"], parsed["artist"])
    edition_id = f"{PROVIDER}:edition:{source_sha[:24].lower()}"
    entry_id = f"{PROVIDER}:{_slug(stem)}:{source_sha[:12].lower()}"
    git_relative_midi = _relative_to_git(midi_resolved, context.root, context.git_root)
    git_relative_lyrics = _relative_to_git(lyrics_resolved, context.root, context.git_root)
    return {
        "id": entry_id,
        "provider": PROVIDER,
        "title": parsed["title"],
        "artist": parsed["artist"],
        "artistRaw": parsed["artistRaw"],
        "artistSegments": parsed["artistSegments"],
        "languageTags": language_tags,
        "languageBasis": language_basis,
        "workId": work_id,
        "editionId": edition_id,
        "versionLabel": f"原始 MIDI+歌词版 · {stem}",
        "sourceSha256": source_sha,
        "lyricsSha256": lyrics_sha,
        "sourcePairSha256": pair_sha,
        "sourceUrl": _file_url(context.source_url, context.source_commit, git_relative_midi),
        "lyricsSourceUrl": _file_url(context.source_url, context.source_commit, git_relative_lyrics),
        "sourceCommit": context.source_commit,
        "sourceRelativePath": pair.midi_relative,
        "lyricsRelativePath": pair.lyrics_relative,
        "sourcePath": str(midi_resolved),
        "lyricsPath": str(lyrics_resolved),
        "lyricsEncoding": lyrics_encoding,
        "lyricsLineCount": parsed["lyricsLineCount"],
        "sourceHeader": parsed["headerFields"],
        "sourceHeaderRaw": parsed["headerRaw"],
        "license": "not-stated-by-source",
        "rightsStatus": RIGHTS_STATUS,
        "redistributionVerified": REDISTRIBUTION_VERIFIED,
        "rightsNote": "本工具未核验逐曲版权、改编权或再分发权；仅保留为 research candidate，不进入生产曲库。",
        "productionStatus": "research-candidate",
        "productionBuiltin": False,
        "sourceFilesCopied": False,
    }


def audit_batch(
    source: Path | str,
    *,
    limit: int = 0,
    source_url: str | None = None,
    source_commit: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    if limit < 0:
        raise IntakeError("--limit must be >= 0; 0 means no limit")
    source_root = _ensure_source_root(Path(source))
    context = _source_context(source_root, source_url, source_commit)
    pairs, failures, discovery_stats = _discover_pairs(source_root)
    candidates: list[dict[str, Any]] = []
    seen_source_sha: dict[str, str] = {}
    duplicate_source_count = 0
    for pair in pairs:
        try:
            entry = _build_entry(pair, context)
        except (IntakeError, OSError) as exc:
            failures.append(
                {
                    "kind": "invalid-pair",
                    "pairKey": pair.key,
                    "midiPath": pair.midi_relative,
                    "lyricsPath": pair.lyrics_relative,
                    "reason": str(exc),
                }
            )
            continue
        source_sha = entry["sourceSha256"]
        if source_sha in seen_source_sha:
            duplicate_source_count += 1
            failures.append(
                {
                    "kind": "duplicate-source-sha256",
                    "pairKey": pair.key,
                    "midiPath": pair.midi_relative,
                    "duplicateOf": seen_source_sha[source_sha],
                    "sourceSha256": source_sha,
                }
            )
            continue
        seen_source_sha[source_sha] = pair.midi_relative
        candidates.append(entry)

    candidates.sort(key=lambda item: (item["sourceRelativePath"].casefold(), item["id"]))
    selected = candidates if limit == 0 else candidates[:limit]
    not_selected = [
        {
            "id": item["id"],
            "sourceRelativePath": item["sourceRelativePath"],
            "reason": "excluded-by-limit",
        }
        for item in candidates[len(selected) :]
    ]
    timestamp = generated_at or utc_now()
    source_audit = {
        "provider": PROVIDER,
        "sourceRoot": str(context.root),
        "gitRoot": str(context.git_root) if context.git_root else None,
        "sourceUrl": context.source_url,
        "sourceCommit": context.source_commit,
        "remoteUrlDetected": context.remote_url,
        "sourceDeclaration": context.source_declaration,
        "rightsStatus": RIGHTS_STATUS,
        "redistributionVerified": REDISTRIBUTION_VERIFIED,
    }
    status = "PASS" if not failures else "PARTIAL"
    if not candidates:
        status = "PARTIAL"
    report = {
        "schemaVersion": SCHEMA_VERSION,
        "status": status,
        "generatedAtUtc": timestamp,
        "provider": PROVIDER,
        "source": source_audit,
        "statistics": {
            **discovery_stats,
            "candidateCountBeforeLimit": len(candidates),
            "selectedCount": len(selected),
            "excludedByLimitCount": len(not_selected),
            "invalidPairCount": sum(1 for item in failures if item.get("kind") == "invalid-pair"),
            "duplicateSourceSha256Count": duplicate_source_count,
            "failureCount": len(failures),
        },
        "failedItems": sorted(failures, key=lambda item: canonical_json(item)),
        "excludedByLimit": not_selected,
        "productionSongsWritten": 0,
        "sourceFilesCopied": 0,
        "songsDirectoryTouched": False,
        "userDataTouched": False,
        "nativeKeySendAttempts": 0,
    }
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "provider": PROVIDER,
        "batchKind": BATCH_KIND,
        "generatedAtUtc": timestamp,
        "sourceRoot": str(context.root),
        "sourceUrl": context.source_url,
        "sourceCommit": context.source_commit,
        "rightsStatus": RIGHTS_STATUS,
        "redistributionVerified": REDISTRIBUTION_VERIFIED,
        "license": "not-stated-by-source",
        "productionBuiltin": False,
        "entries": selected,
    }
    readme = _build_readme(manifest, report)
    return {
        "manifest": manifest,
        "report": report,
        "sourceAudit": source_audit,
        "readme": readme,
        "selected": selected,
    }


def _build_readme(manifest: dict[str, Any], report: dict[str, Any]) -> str:
    stats = report["statistics"]
    return (
        "# midi_lyric_corpus 中文 MIDI+歌词候选 intake\n\n"
        "本目录是只读来源审计结果和 research candidate 元数据，不是生产曲库。\n\n"
        f"- provider：`{manifest['provider']}`\n"
        f"- sourceUrl：`{manifest['sourceUrl']}`\n"
        f"- sourceCommit：`{manifest['sourceCommit']}`\n"
        f"- rightsStatus：`{manifest['rightsStatus']}`\n"
        "- redistributionVerified：`false`\n"
        f"- 选中条目：`{stats['selectedCount']}`\n"
        f"- 配对文件：`{stats['pairedFileCount']}`\n"
        f"- 失败项：`{stats['failureCount']}`\n\n"
        "工具只保存来源文件路径、哈希和解析后的元数据，不复制 MIDI/歌词二进制，不写入 `Songs`、"
        "`UserData` 或 EXE，也不发送游戏按键。语言标签只能来自歌词文本或来源声明，不从标题猜测。\n"
    )


def _write_new_text(path: Path, text: str) -> None:
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
    except FileExistsError as exc:
        raise IntakeError(f"refusing to overwrite existing output: {path}") from exc


def write_intake(result: dict[str, Any], output: Path | str) -> dict[str, Any]:
    source_root = Path(result["manifest"]["sourceRoot"]).resolve(strict=True)
    target = _ensure_output_is_safe(Path(output), source_root)
    try:
        target.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise IntakeError(f"refusing to overwrite existing output: {target}") from exc
    _write_new_text(target / "manifest.json", canonical_json(result["manifest"]))
    _write_new_text(target / "acquisition-report.json", canonical_json(result["report"]))
    _write_new_text(target / "source-audit.json", canonical_json(result["sourceAudit"]))
    _write_new_text(target / "README.md", result["readme"])
    return {**result, "output": str(target)}


def acquire_batch(
    source: Path | str,
    output: Path | str,
    *,
    limit: int = 0,
    source_url: str | None = None,
    source_commit: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    result = audit_batch(
        source,
        limit=limit,
        source_url=source_url,
        source_commit=source_commit,
        generated_at=generated_at,
    )
    return write_intake(result, output)


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def main(argv: Iterable[str] | None = None) -> int:
    _configure_stdio()
    parser = argparse.ArgumentParser(description="审计 midi_lyric_corpus 并生成中文 MIDI+歌词候选 intake")
    parser.add_argument("source", type=Path, help="本地来源目录，例如 corpus\\data")
    parser.add_argument("--limit", type=int, default=0, help="最多写入多少个候选；0 表示不限制")
    parser.add_argument("--output", type=Path, required=True, help="新建的 intake 输出目录；已有目录拒绝覆盖")
    parser.add_argument("--source-url", help="覆盖自动检测到的来源仓库 URL")
    parser.add_argument("--source-commit", help="覆盖自动检测到的 Git commit")
    parser.add_argument("--generated-at", help="固定生成时间，便于回归测试；默认当前 UTC 时间")
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        result = acquire_batch(
            args.source,
            args.output,
            limit=args.limit,
            source_url=args.source_url,
            source_commit=args.source_commit,
            generated_at=args.generated_at,
        )
    except (IntakeError, OSError) as exc:
        print(f"失败：{exc}", file=sys.stderr)
        return 2
    report = result["report"]
    print(
        json.dumps(
            {
                "status": report["status"],
                "output": result["output"],
                "selected": report["statistics"]["selectedCount"],
                "failed": report["statistics"]["failureCount"],
                "sourceCommit": result["manifest"]["sourceCommit"],
                "rightsStatus": result["manifest"]["rightsStatus"],
                "redistributionVerified": result["manifest"]["redistributionVerified"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
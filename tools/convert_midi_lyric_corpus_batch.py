"""将 midi_lyric_corpus intake 转换为隔离的 PopBatch 结构化候选批次。

本工具只生成 reference JSON 和 manifest，不复制 MIDI/TXT，不写入 Songs、UserData、EXE，
也不声明版权、人工听辨、游戏验收或平台实时热度。来源 MIDI 由 manifest 中的绝对路径引用，
时序由项目内独立 smf_reference.py 解析器生成。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
from smf_reference import parse_smf  # noqa: E402

PROVIDER = "midi_lyric_corpus"
REPOSITORY = "https://github.com/andy-yangz/midi_lyric_corpus"
BATCH_KIND = "midi-lyric-corpus-structured-midi-candidate"
LICENSE = "not-stated-by-source"
RIGHTS_STATUS = "candidate-unverified"
VERSION_LABEL_FALLBACK = "原始 MIDI+歌词版"
HEX64 = re.compile(r"^[0-9A-Fa-f]{64}$")

# 透明的编辑优先集合：只用于 UI 分层，不等于任何平台当前榜单认证。
POPULAR_ARTISTS = {
    "周华健", "王杰", "刘德华", "张学友", "邓丽君", "那英", "童安格", "齐秦",
    "孟庭苇", "郭富城", "林志颖", "王靖雯", "林忆莲", "张国荣", "梅艳芳", "黎明",
    "谭咏麟", "潘越云", "苏芮", "韦唯", "潘美辰", "张宇", "毛阿敏", "陈淑桦",
    "周慧敏", "张雨生", "孙悦", "郑钧", "郑智化", "蔡国庆", "赵传", "刘欢",
    "成龙", "许冠杰", "张信哲", "李翊君", "温兆伦", "陈少华", "李娜", "黄安",
}
POPULAR_TITLES = {
    "花心", "同桌的你", "回到拉萨", "雾里看花", "我想有个家", "我很丑 可是我很温柔",
    "爱的奉献", "真爱是谁", "一路上有你", "爱拼才会赢", "天意", "滚滚长江东逝水",
    "一天一点爱恋", "有一点动心", "爱与哀愁", "一剪梅", "风中有朵雨做的云",
    "用心良苦", "九月九的酒", "白天不懂夜的黑", "亲亲我的宝贝", "饿狼传说",
    "李香兰", "红旗下的蛋", "白天不懂夜的黑", "你在他乡还好吗", "今生无悔",
}


class ConversionError(ValueError):
    """候选转换输入或结构不合法。"""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _write_new(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(data)


def _safe_source_path(raw: str, source_root: Path) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ConversionError("sourcePath is empty")
    path = Path(raw).expanduser().resolve(strict=True)
    root = source_root.resolve(strict=True)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ConversionError(f"source path escapes source root: {path}") from exc
    if path.suffix.casefold() not in {".mid", ".midi"}:
        raise ConversionError(f"source path is not MIDI: {path}")
    return path


def _intake_entries(manifest_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or not isinstance(payload.get("entries"), list):
        raise ConversionError("intake manifest must contain entries list")
    return payload, [item for item in payload["entries"] if isinstance(item, dict)]


def _stable_id(raw_id: str, source_hash: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", raw_id).strip("-._")
    safe = safe[:180] or "candidate"
    return f"{safe}-{source_hash[:12].lower()}"


def _popularity(title: str, artist: str) -> tuple[list[str], str, str]:
    tags = ["中文歌曲", "中文流行候选", "metadata-language-editorial"]
    matched = artist.strip() in POPULAR_ARTISTS or title.strip() in POPULAR_TITLES
    if matched:
        tags.extend(["中文流行", "大众优先"])
        return tags, "P0", "editorial-mainstream-set; not a real-time Douyin/Kugou/NetEase chart claim"
    return tags, "P1", "source-level Chinese corpus candidate; popularity not platform-verified"


def _normalize_datetime(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "2026-10-07T00:00:00+00:00"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConversionError(f"invalid generatedAtUtc: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat()


def convert_batch(manifest_path: Path | str, output: Path | str, *, limit: int = 0, write: bool = True) -> dict[str, Any]:
    manifest_path = Path(manifest_path).resolve(strict=True)
    output = Path(output).resolve()
    if limit < 0:
        raise ConversionError("limit must be >= 0; 0 means no limit")
    if output.exists() and write:
        raise FileExistsError(output)
    intake, entries = _intake_entries(manifest_path)
    source_root = Path(str(intake.get("sourceRoot") or "")).resolve(strict=True)
    source_commit = str(intake.get("sourceCommit") or "local-unpinned")
    source_url = str(intake.get("sourceUrl") or REPOSITORY)
    retrieved = _normalize_datetime(str(intake.get("generatedAtUtc") or ""))
    if not source_url.startswith("http://") and not source_url.startswith("https://"):
        raise ConversionError("sourceUrl must be HTTP(S)")

    candidates: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    seen_ids: set[str] = set()
    seen_editions: set[str] = set()
    for raw in sorted(entries, key=lambda item: (str(item.get("id", "")).casefold(), str(item.get("sourcePath", "")).casefold())):
        identifier = str(raw.get("id") or "")
        try:
            source_path = _safe_source_path(str(raw.get("sourcePath") or ""), source_root)
            actual_hash = sha256_file(source_path)
            declared_hash = str(raw.get("sourceSha256") or "").upper()
            if not HEX64.fullmatch(declared_hash) or declared_hash != actual_hash:
                raise ConversionError("sourceSha256 does not match source MIDI")
            source_ref = parse_smf(source_path.read_bytes())
            notes = source_ref.get("notes")
            if not isinstance(notes, list) or not notes:
                raise ConversionError("MIDI contains no usable notes")
            if any(not isinstance(note, dict) for note in notes):
                raise ConversionError("reference note is not an object")
            title = str(raw.get("title") or "").strip()
            artist = str(raw.get("artist") or "").strip()
            if not title or not artist:
                raise ConversionError("title/artist is empty")
            language_tags = [str(value) for value in raw.get("languageTags", []) if str(value).strip()]
            if not language_tags:
                raise ConversionError("languageTags is empty; unknown language is not promoted")
            work_id = str(raw.get("workId") or "").strip()
            edition_id = str(raw.get("editionId") or "").strip()
            if not work_id or not edition_id:
                raise ConversionError("workId/editionId is empty")
            stable_id = _stable_id(identifier, actual_hash)
            if stable_id in seen_ids or edition_id in seen_editions or actual_hash in seen_hashes:
                raise ConversionError("duplicate id, editionId or source hash")
            seen_ids.add(stable_id)
            seen_editions.add(edition_id)
            seen_hashes.add(actual_hash)
            tags, tier, basis = _popularity(title, artist)
            source_name = source_path.name
            reference = {
                "notes": notes,
                "lengthMs": source_ref["lengthMs"],
                "bpm": source_ref["bpm"],
                "tempoChanges": source_ref["tempoChanges"],
                "reference": "independent smf_reference.py parser; source MIDI unchanged",
                "sourceSha256": actual_hash,
                "synthetic": False,
            }
            reference_name = f"{stable_id}.reference.json"
            reference_path = (output / "references" / reference_name).resolve()
            source_page = str(raw.get("sourceUrl") or f"{source_url}/blob/{source_commit}/{source_name}")
            version = str(raw.get("versionLabel") or f"{VERSION_LABEL_FALLBACK} · {raw.get('sourceRelativePath', source_name)}")
            song = {
                "Id": stable_id,
                "Title": title,
                "Artist": artist,
                "Artists": [artist],
                "MidiPath": str(source_path),
                "ReferencePath": str(reference_path),
                "SourceUrl": source_page,
                "SourceSha256": actual_hash,
                "NotationSha256": actual_hash,
                "LanguageTags": language_tags,
                "Provider": PROVIDER,
                "SourceCommit": source_commit,
                "SourceRecord": source_url,
                "BatchKind": BATCH_KIND,
                "Author": "midi_lyric_corpus source MIDI (arranger not individually labeled)",
                "Category": "中文流行候选 · " + tier + " · 待音乐审核",
                "Description": "保留来源 MIDI 的音高、轨道、力度和完整 tempo map；当前仅完成结构化时序校验，未完成人工听辨、游戏验收或权利核验。",
                "IdPattern": "midi_lyric_corpus:<source-id>",
                "SmartInterludes": True,
                "WorkId": work_id,
                "EditionId": edition_id,
                "VersionLabel": version,
                "License": LICENSE,
                "LicenseUrl": "",
                "RightsStatus": RIGHTS_STATUS,
                "RightsNote": "来源仓库未见逐曲再分发授权声明；仅研究候选，不作为已获授权的内置曲谱。",
                "Album": "",
                "Aliases": [title, identifier],
                "Tags": tags,
                "Completeness": "source-relative-full-midi",
                "MusicReview": "not-reviewed",
                "GameReview": "not-tested",
                "RedistributionVerified": False,
            }
            candidates.append({"song": song, "reference": reference, "title": title, "artist": artist, "id": stable_id, "sourceId": identifier, "priorityTier": tier, "priorityBasis": basis})
        except Exception as exc:
            failures.append({"id": identifier, "title": str(raw.get("title") or ""), "sourcePath": str(raw.get("sourcePath") or ""), "reason": str(exc)})

    candidates.sort(key=lambda item: (0 if item["priorityTier"] == "P0" else 1, str(item["id"]).casefold()))
    selected = candidates if limit == 0 else candidates[:limit]
    excluded = [{"id": item["id"], "title": item["title"], "reason": "excluded-by-limit"} for item in candidates[len(selected):]]
    if not selected:
        raise ConversionError("no valid structured candidates")
    batch_manifest = {
        "Songs": [item["song"] for item in selected],
        "SourceCommit": source_commit,
        "SourceRecord": source_url,
        "RetrievedAtUtc": retrieved,
        "Provider": PROVIDER,
        "BatchKind": BATCH_KIND,
        "SourceUrl": source_url,
        "License": LICENSE,
        "LicenseUrl": "",
        "RightsStatus": RIGHTS_STATUS,
        "RightsNote": "Research candidate only; source license and underlying song rights are not independently verified.",
        "RedistributionVerified": False,
        "Author": "midi_lyric_corpus source MIDI",
        "Category": "中文流行候选",
        "Description": "中文 MIDI 结构化候选批次；P0/P1 仅为编辑分层，不是抖音、酷狗或网易云实时榜单证明。",
        "IdPattern": "midi_lyric_corpus:<source-id>",
        "SmartInterludesDefault": True,
    }
    audit = {
        "schemaVersion": "midi-lyric-corpus-popbatch-adapter/v1",
        "manifestPath": str(manifest_path),
        "sourceRoot": str(source_root),
        "sourceCommit": source_commit,
        "sourceRecord": source_url,
        "retrievedAtUtc": retrieved,
        "candidateCountBeforeLimit": len(candidates),
        "selectedCount": len(selected),
        "excludedByLimitCount": len(excluded),
        "failureCount": len(failures),
        "failures": sorted(failures, key=lambda item: canonical_json(item)),
        "excludedByLimit": excluded,
        "priorityCounts": {tier: sum(item["priorityTier"] == tier for item in selected) for tier in ("P0", "P1")},
        "priorityBasis": sorted({item["priorityBasis"] for item in selected}),
        "rightsStatus": RIGHTS_STATUS,
        "redistributionVerified": False,
        "productionBuiltin": False,
        "sourceTiming": "independent smf_reference.py; no audio inference",
        "sourceFilesCopied": False,
        "songsDirectoryTouched": False,
        "userDataTouched": False,
        "nativeKeySendAttempts": 0,
    }
    readme = (
        "# midi_lyric_corpus 中文流行结构化候选\n\n"
        "本目录是隔离研究候选，不是生产内置曲库。MIDI 由 manifest 绝对路径引用，未复制来源文件。\n\n"
        f"- 来源：`{source_url}`\n- commit：`{source_commit}`\n- 选中：`{len(selected)}`（P0={audit['priorityCounts']['P0']}，P1={audit['priorityCounts']['P1']}）\n"
        f"- 解析失败：`{len(failures)}`；limit 排除：`{len(excluded)}`\n"
        f"- rightsStatus：`{RIGHTS_STATUS}`；redistributionVerified：`false`\n\n"
        "P0/P1 是透明的编辑分层，不是抖音、酷狗或网易云实时榜单认证。来源仓库未见逐曲再分发授权声明，"
        "不得据此宣称可公开分发；人工音乐审核、原神内验收和版权核验均未完成。\n"
    )
    result = {"manifest": batch_manifest, "audit": audit, "readme": readme, "selected": selected, "count": len(selected)}
    if write:
        (output / "references").mkdir(parents=True, exist_ok=False)
        _write_new(output / "manifest.json", canonical_json(batch_manifest))
        _write_new(output / "source-audit.json", canonical_json(audit))
        _write_new(output / "README.md", readme)
        for item in selected:
            _write_new(output / "references" / f"{item['id']}.reference.json", canonical_json(item["reference"]))
    return result


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert midi_lyric_corpus intake into isolated PopBatch candidates")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        result = convert_batch(args.manifest, args.output, limit=args.limit, write=True)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": "PASS", "count": result["count"], "output": str(Path(args.output).resolve()), "productionBuiltin": False}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

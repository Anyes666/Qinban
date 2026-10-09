"""中文流行优先准入审计（仅审计元数据，不修改歌曲或运行时）。

该工具读取 Songs/catalog.db，并可选读取 intake manifest，对 provider、语种标签、
tags/category 和批次分类做确定性统计。它不根据标题文字猜测语言，也不把 BFDB 等
未标语种来源自动当作英文或中文；它也不执行下载、按键、安装、覆盖或音乐验收。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "Songs" / "catalog.db"
SCHEMA_VERSION = "1.0"
CHINESE_LANGUAGE_BASES = {"zh", "cmn", "yue"}
UNKNOWN_LANGUAGE_BASES = {"und", "unknown", "unspecified"}


class AuditError(ValueError):
    """可报告给用户的输入或审计错误。"""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _list_of_text(value: Any) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    return [_text(item) for item in values if _text(item)]


def _get(mapping: dict[str, Any], *names: str) -> Any:
    lowered = {str(key).lower(): value for key, value in mapping.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def _base_language(tag: str) -> str:
    return tag.strip().lower().split("-", 1)[0]


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        value = _text(value)
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _metadata_view(raw: dict[str, Any]) -> dict[str, Any]:
    """把 catalog 行、manifest 行或直接 metadata 统一为审计视图。"""
    nested = _get(raw, "metadata", "metadata_json")
    if isinstance(nested, str):
        try:
            nested = json.loads(nested)
        except json.JSONDecodeError:
            nested = None
    source = nested if isinstance(nested, dict) else raw
    provenance = _get(source, "provenance")
    provenance = provenance if isinstance(provenance, dict) else {}

    provider = _get(provenance, "provider") or _get(source, "provider") or _get(raw, "provider")
    language_tags = _get(provenance, "languageTags", "language_tags")
    if language_tags is None:
        language_tags = _get(source, "languageTags", "language_tags")
    if language_tags is None:
        language_tags = _get(raw, "languageTags", "language_tags")
    tags = _get(provenance, "tags")
    if tags is None:
        tags = _get(source, "tags")
    if tags is None:
        tags = _get(raw, "tags")
    category = _get(source, "category") or _get(provenance, "category") or _get(raw, "category")

    # 这些字段只作为明确的编辑/来源标签，不包含 title，避免从中文字符推断语种。
    marker_fields = []
    for name in ("tags", "category", "genre", "contentType", "classification", "batchKind"):
        value = _get(source, name) if name not in {"tags", "category"} else (_get(source, name) or _get(raw, name))
        marker_fields.extend(_list_of_text(value))
    marker_fields.extend(_list_of_text(tags))
    if category:
        marker_fields.append(_text(category))

    return {
        "id": _text(_get(source, "id", "catalogId", "catalog_id") or _get(raw, "id", "Id", "catalogId", "entryId")),
        "workId": _text(_get(source, "workId", "work_id") or _get(raw, "workId", "WorkId")),
        "relativePath": _text(_get(source, "relativePath", "relative_path") or _get(raw, "relativePath", "RelativePath", "file", "File")),
        "provider": _text(provider),
        "languageTags": _unique(_list_of_text(language_tags)),
        "tags": _unique(_list_of_text(tags)),
        "category": _text(category),
        "markerText": " | ".join(marker_fields),
    }


def _marker_flags(view: dict[str, Any]) -> dict[str, bool]:
    text = view["markerText"].casefold()
    # 这些是显式元数据标记；不使用标题、不使用 provider 单独推断语种。
    chinese = any(token in text for token in (
        "中文", "华语", "国语", "粤语", "普通话", "mandopop", "cantopop",
        "chinese pop", "chinese song", "chinese-pop", "c-pop",
    ))
    pop = any(token in text for token in (
        "流行", "pop", "cantopop", "mandopop", "c-pop",
    ))
    folk = any(token in text for token in ("民歌", "folk", "民族音乐", "traditional folk"))
    non_chinese = any(token in text for token in (
        "非中文", "英文", "英语", "english", "日文", "日语", "japanese",
        "韩文", "韩语", "korean",
    ))
    return {
        "markedChineseCandidate": chinese,
        "markedPop": pop,
        "markedFolk": folk,
        "markedNonChinese": non_chinese,
    }


def _language_flags(language_tags: list[str]) -> dict[str, bool]:
    bases = {_base_language(tag) for tag in language_tags if _text(tag)}
    chinese = bool(bases & CHINESE_LANGUAGE_BASES)
    unknown_only = not bases or bases <= UNKNOWN_LANGUAGE_BASES
    other = bool(bases - CHINESE_LANGUAGE_BASES - UNKNOWN_LANGUAGE_BASES)
    return {
        "languageTaggedChinese": chinese,
        "languageUnlabeled": unknown_only,
        "languageTaggedOther": other,
    }


def classify(view: dict[str, Any]) -> str:
    """返回 chinese_pop/chinese_folk/non_chinese/unknown。"""
    marker = _marker_flags(view)
    language = _language_flags(view["languageTags"])
    chinese_evidence = marker["markedChineseCandidate"] or language["languageTaggedChinese"]
    if marker["markedFolk"] and chinese_evidence:
        return "chinese_folk"
    if marker["markedPop"] and chinese_evidence:
        return "chinese_pop"
    if marker["markedNonChinese"] or language["languageTaggedOther"]:
        return "non_chinese"
    return "unknown"


def _counter_dict(counter: Counter[str]) -> dict[str, int]:
    return {key: counter[key] for key in sorted(counter)}


def _ratio(count: int, total: int) -> float:
    return round(count / total, 6) if total else 0.0


def _load_catalog(path: Path) -> tuple[list[dict[str, Any]], str, list[str]]:
    if not path.is_file():
        raise AuditError(f"catalog 不存在或不是文件: {path}")
    catalog_hash = sha256_file(path)
    errors: list[str] = []
    entries: list[dict[str, Any]] = []
    connection: sqlite3.Connection | None = None
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        columns = {row[1] for row in connection.execute("PRAGMA table_info(entries)")}
        required = {"id", "work_id", "relative_path", "metadata_json"}
        missing = sorted(required - columns)
        if missing:
            raise AuditError(f"catalog entries 缺少列: {', '.join(missing)}")
        rows = connection.execute(
            "SELECT id, work_id, relative_path, metadata_json FROM entries ORDER BY id"
        ).fetchall()
    except sqlite3.Error as exc:
        raise AuditError(f"读取 catalog 失败: {exc}") from exc
    finally:
        if connection is not None:
            connection.close()

    for row_number, row in enumerate(rows, 1):
        try:
            metadata = json.loads(row["metadata_json"])
            if not isinstance(metadata, dict):
                raise ValueError("metadata_json 不是对象")
            raw = dict(metadata)
            raw.update({
                "id": row["id"],
                "work_id": row["work_id"],
                "relative_path": row["relative_path"],
            })
            view = _metadata_view(raw)
            view["id"] = _text(row["id"])
            view["workId"] = _text(row["work_id"])
            view["relativePath"] = _text(row["relative_path"])
            view["classification"] = classify(view)
            entries.append(view)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"catalog 第 {row_number} 行 metadata 无法解析: {exc}")
    return entries, catalog_hash, errors


def _catalog_indexes(entries: list[dict[str, Any]]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    indexes: dict[str, dict[str, list[dict[str, Any]]]] = {
        "id": defaultdict(list),
        "workId": defaultdict(list),
        "relativePath": defaultdict(list),
    }
    for entry in entries:
        for field in indexes:
            value = _text(entry.get(field))
            if value:
                indexes[field][value].append(entry)
                if field == "id" and value.startswith("builtin:"):
                    indexes[field][value.removeprefix("builtin:")].append(entry)
    return indexes


def _manifest_items(path: Path) -> list[Any]:
    if not path.is_file():
        raise AuditError(f"batch manifest 不存在或不是文件: {path}")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AuditError(f"batch manifest 不是 UTF-8: {exc}") from exc
    if not text.strip():
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        items: list[Any] = []
        for line_number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise AuditError(f"batch manifest 第 {line_number} 行不是 JSON: {exc}") from exc
        return items
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("songs", "Songs", "entries", "Entries", "items", "Items", "records", "Records"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        # 一个直接的单条 intake row 也可作为 batch。
        if any(key in payload for key in ("id", "Id", "catalogId", "CatalogId", "languageTags", "LanguageTags", "tags", "Tags")):
            return [payload]
    raise AuditError("batch manifest 须为数组、JSONL，或包含 songs/entries/items/records 数组的对象")


def _resolve_batch_view(item: Any, indexes: dict[str, dict[str, list[dict[str, Any]]]]) -> tuple[dict[str, Any] | None, str | None]:
    if isinstance(item, str):
        item = {"id": item}
    if not isinstance(item, dict):
        return None, "批次条目不是对象或字符串 ID"

    # 如果 intake row 自己带有分类元数据，优先审计该 row；否则用 catalog 对照。
    direct = _metadata_view(item)
    has_direct_metadata = bool(
        direct["languageTags"] or direct["tags"] or direct["category"] or direct["provider"]
        or _get(item, "metadata", "metadata_json")
    )
    if has_direct_metadata:
        direct["classification"] = classify(direct)
        return direct, None

    candidates: list[dict[str, Any]] = []
    for field, names in (
        ("id", ("id", "Id", "catalogId", "CatalogId", "entryId", "EntryId", "file", "File")),
        ("workId", ("workId", "WorkId", "work_id")),
        ("relativePath", ("relativePath", "RelativePath", "relative_path", "path", "Path")),
    ):
        value = _text(_get(item, *names))
        if value and value in indexes[field]:
            candidates.extend(indexes[field][value])
    unique = {entry["id"]: entry for entry in candidates}
    if len(unique) == 1:
        return next(iter(unique.values())), None
    if len(unique) > 1:
        return None, "批次条目匹配到多个 catalog 条目"
    identifier = _text(_get(item, "id", "Id", "catalogId", "CatalogId", "entryId", "EntryId"))
    return None, f"批次条目无法匹配 catalog: {identifier or '<无 ID>'}"


def _catalog_counts(entries: list[dict[str, Any]]) -> dict[str, Any]:
    providers: Counter[str] = Counter()
    languages: Counter[str] = Counter()
    tags: Counter[str] = Counter()
    categories: Counter[str] = Counter()
    classification: Counter[str] = Counter()
    for entry in entries:
        providers[entry["provider"] or "<未标注>"] += 1
        for language in entry["languageTags"]:
            languages[language.casefold()] += 1
        for tag in entry["tags"]:
            tags[tag] += 1
        categories[entry["category"] or "<未标注>"] += 1
        marker = _marker_flags(entry)
        language_flags = _language_flags(entry["languageTags"])
        if marker["markedChineseCandidate"]:
            classification["markedChineseCandidate"] += 1
        if language_flags["languageTaggedChinese"]:
            classification["languageTaggedChinese"] += 1
        if language_flags["languageUnlabeled"]:
            classification["languageUnlabeled"] += 1
        if language_flags["languageTaggedOther"]:
            classification["languageTaggedOther"] += 1
    return {
        "entries": len(entries),
        "provider": _counter_dict(providers),
        "languageTags": _counter_dict(languages),
        "tags": _counter_dict(tags),
        "category": _counter_dict(categories),
        "classification": {key: classification[key] for key in sorted(classification)},
    }


def _batch_counts(items: list[Any], entries: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    indexes = _catalog_indexes(entries)
    counts: Counter[str] = Counter()
    errors: list[str] = []
    for number, item in enumerate(items, 1):
        view, error = _resolve_batch_view(item, indexes)
        if error:
            errors.append(f"batch 第 {number} 条: {error}")
            counts["unknown"] += 1
        else:
            counts[view["classification"]] += 1
    total = len(items)
    unknown_plus_non = counts["unknown"] + counts["non_chinese"]
    return {
        "total": total,
        "chinesePop": {"count": counts["chinese_pop"], "ratio": _ratio(counts["chinese_pop"], total)},
        "chineseFolk": {"count": counts["chinese_folk"], "ratio": _ratio(counts["chinese_folk"], total)},
        "nonChinese": {"count": counts["non_chinese"], "ratio": _ratio(counts["non_chinese"], total)},
        "unknown": {"count": counts["unknown"], "ratio": _ratio(counts["unknown"], total)},
        "unknownPlusNonChinese": {"count": unknown_plus_non, "ratio": _ratio(unknown_plus_non, total)},
    }, errors


def build_report(
    catalog: Path,
    batch: Path | None,
    policy: str,
    max_unknown_non_chinese_ratio: float,
) -> dict[str, Any]:
    generated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    errors: list[str] = []
    catalog_hash: str | None = None
    entries: list[dict[str, Any]] = []
    try:
        entries, catalog_hash, catalog_errors = _load_catalog(catalog)
        errors.extend(catalog_errors)
    except AuditError as exc:
        errors.append(str(exc))

    batch_report: dict[str, Any] | None = None
    if batch is not None and not errors:
        try:
            items = _manifest_items(batch)
            batch_report, batch_errors = _batch_counts(items, entries)
            errors.extend(batch_errors)
        except AuditError as exc:
            errors.append(str(exc))
            batch_report = {
                "total": 0,
                "chinesePop": {"count": 0, "ratio": 0.0},
                "chineseFolk": {"count": 0, "ratio": 0.0},
                "nonChinese": {"count": 0, "ratio": 0.0},
                "unknown": {"count": 0, "ratio": 0.0},
                "unknownPlusNonChinese": {"count": 0, "ratio": 0.0},
            }

    if not 0 <= max_unknown_non_chinese_ratio <= 1:
        errors.append("max_unknown_non_chinese_ratio 必须在 0 到 1 之间")

    policy_errors: list[str] = []
    if batch_report is not None:
        if batch_report["total"] == 0:
            policy_errors.append("批次为空，拒绝准入")
        if policy == "chinese-pop-first":
            if batch_report["chinesePop"]["count"] == 0:
                policy_errors.append("chinese-pop-first: 批次没有中文流行候选")
            if batch_report["unknownPlusNonChinese"]["ratio"] > max_unknown_non_chinese_ratio:
                policy_errors.append(
                    "chinese-pop-first: 未知+非中文比例 "
                    f"{batch_report['unknownPlusNonChinese']['ratio']:.6f} 超过阈值 "
                    f"{max_unknown_non_chinese_ratio:.6f}"
                )
    elif policy == "chinese-pop-first":
        policy_errors.append("chinese-pop-first 需要 --batch")
    errors.extend(policy_errors)

    status = "PASS" if not errors else "FAIL"
    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAtUtc": generated,
        "catalogHash": catalog_hash,
        "counts": {
            "catalog": _catalog_counts(entries),
            "batch": batch_report,
        },
        "policy": {
            "name": policy,
            "maxUnknownPlusNonChineseRatio": max_unknown_non_chinese_ratio,
            "emptyBatch": "FAIL",
        },
        "status": status,
        "errors": errors,
        "sourceBoundary": {
            "type": "metadata-admission-audit-only",
            "statement": "本报告仅审计元数据准入与批次标签；不是版权验收、音乐验收或游戏内验收。",
            "catalog": str(catalog.resolve()),
            "batch": str(batch.resolve()) if batch is not None else None,
            "mutations": 0,
            "downloads": 0,
            "nativeKeySendAttempts": 0,
        },
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
    except FileExistsError as exc:
        raise AuditError(f"拒绝覆盖已有报告: {path}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="中文流行优先准入审计（仅元数据）")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG, help="Songs/catalog.db 路径")
    parser.add_argument("--batch", type=Path, help="intake manifest（JSON、JSON 数组或 JSONL）")
    parser.add_argument("--report", type=Path, required=True, help="不可覆盖的 JSON 报告路径")
    parser.add_argument(
        "--policy",
        choices=("none", "chinese-pop-first"),
        default="none",
        help="批次策略；chinese-pop-first 要求有中文流行候选且未知+非中文不超阈值",
    )
    parser.add_argument(
        "--max-unknown-non-chinese-ratio",
        "--max-unknown-plus-non-chinese-ratio",
        dest="max_unknown_non_chinese_ratio",
        type=float,
        default=0.20,
        help="chinese-pop-first 的未知+非中文最大比例，默认 0.20",
    )
    args = parser.parse_args(argv)

    try:
        report = build_report(
            catalog=args.catalog,
            batch=args.batch,
            policy=args.policy,
            max_unknown_non_chinese_ratio=args.max_unknown_non_chinese_ratio,
        )
        write_report(args.report, report)
    except AuditError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"FAIL: 写入报告失败: {exc}", file=sys.stderr)
        return 1

    print(json.dumps({"status": report["status"], "report": str(args.report.resolve())}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
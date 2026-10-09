"""Curate the existing POP909 lane as the Chinese-pop-first library.

This tool is intentionally metadata-only: it never changes note events, never
installs the pending BFDB batch, never touches the executable or UserData, and
never contacts a music platform.  The source index supplies title/artist
identity; language and popularity tiers are editorial classifications and are
not rights, completeness, music-review, or chart certifications.

Dry-run is the default.  Use --apply only after the plan/report is reviewed.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SONGS = ROOT / "Songs"
RUNTIME_SONGS = ROOT.parent / "dist" / "QinBan-0.4.2-two-song-pilot-win-x64" / "Songs"
POP_INDEX = ROOT / "catalog-intake" / "discovery" / "2026-10-05-pop909" / "parsed" / "candidates.json"
RUN_ID = "chinese-pop-metadata-2026-10-07-v1"
BACKUP_ROOT = ROOT / ".validation" / RUN_ID

# These are a transparent editorial priority set, not a platform chart dump.
# Artist priority catches the well-known mainstream lanes already present in
# POP909; title priority also captures a few important works from other artists.
PRIORITY_ARTISTS = {
    "周杰伦", "林俊杰", "蔡依林", "五月天", "陈奕迅", "邓紫棋", "薛之谦",
    "毛不易", "张杰", "张韶涵", "田馥甄", "梁静茹", "王力宏", "孙燕姿",
    "李荣浩", "陈粒", "周深", "王菲", "张信哲", "林忆莲", "张宇", "陈绮贞",
    "许嵩", "S.H.E", "苏打绿", "杨宗纬", "鹿晗", "赵雷",
}
PRIORITY_TITLES = {
    "晴天", "七里香", "日不落", "小幸运", "不能说的秘密", "告白气球", "稻香",
    "青花瓷", "夜曲", "起风了", "光年之外", "泡沫", "演员", "绅士", "丑八怪",
    "易燃易爆炸", "平凡之路", "后来", "匆匆那年", "年轮", "红色高跟鞋", "小酒窝",
    "一千年以后", "江南", "修炼爱情", "可惜没如果", "爱笑的眼睛", "会呼吸的痛",
    "说好的幸福呢", "说好不哭", "我不愿让你一个人", "爱情转移", "一路生花", "向云端",
    "我会等", "可能", "海阔天空", "十年", "好久不见", "如果有来生", "盗将行",
    "红昭愿", "芒种", "大鱼", "左手指月", "赤伶", "年少有为", "戒烟", "不将就",
    "李白", "消愁", "像我这样的人", "成都", "南山南", "旅行的意义", "漂洋过海来看你",
    "至少还有你", "勇气", "童话", "可惜不是你", "体面", "我们俩", "爱如潮水", "情非得已",
    "知否知否", "凉凉", "三生三世", "小半", "走马", "奇妙能力歌", "光的方向",
    "此生不换", "偏爱", "心墙", "有点甜", "小情歌", "爱你", "舞娘", "倒带", "我怀念的",
    "天黑黑", "开始懂了", "遇见", "绿光", "当你", "可爱女人", "简单爱", "彩虹", "搁浅",
    "最长的电影", "手写的从前", "烟花易冷", "兰亭序", "发如雪", "半岛铁盒", "轨迹", "借口",
    "暗号", "退后", "龙卷风", "一路向北", "枫", "明明就", "大城小爱", "我们的歌", "美人鱼",
    "一念之间", "杀破狼", "月牙湾", "隐形的翅膀", "欧若拉", "遗失的美好", "不得不爱",
    "爱的供养", "一剪梅", "千千阙歌", "海底", "阿拉斯加海湾",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def json_text(value: Any) -> str:
    # Existing score files are Windows UTF-8/CRLF JSON. Keep that convention.
    return json.dumps(value, ensure_ascii=False, indent=2, separators=(",", ": ")) + "\r\n"


def normalize_for_search(text: str) -> str:
    # LibrarySearch.Normalize keeps letters/digits (including CJK), lowercases,
    # and turns punctuation into separators. For the added Chinese labels the
    # simple implementation below is equivalent.
    import unicodedata

    result: list[str] = []
    pending_space = False
    for char in unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", text)):
        if unicodedata.combining(char):
            continue
        if char.isalnum():
            if pending_space and result:
                result.append(" ")
            result.append(char.lower())
            pending_space = False
        else:
            pending_space = True
    return "".join(result)


def dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        value = str(value)
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def pop_id(path: Path) -> str:
    return path.stem.removeprefix("pop909-")


def load_index() -> tuple[dict[str, dict[str, Any]], str]:
    raw = POP_INDEX.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    rows = payload.get("candidates")
    if not isinstance(rows, list) or len(rows) != 909:
        raise RuntimeError("POP909 index must contain exactly 909 candidate rows")
    by_id = {str(row["sourceIndexId"]): row for row in rows}
    if len(by_id) != 909:
        raise RuntimeError("POP909 index contains duplicate sourceIndexId values")
    return by_id, sha256_bytes(raw)


def running_qinban() -> list[dict[str, Any]]:
    if os.name != "nt":
        return []
    command = (
        "$ErrorActionPreference='Stop'; @(Get-Process -Name QinBan -ErrorAction SilentlyContinue "
        "| Select-Object Id,Path) | ConvertTo-Json -Compress"
    )
    result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", command], capture_output=True, text=True, check=True)
    if not result.stdout.strip():
        return []
    parsed = json.loads(result.stdout)
    return parsed if isinstance(parsed, list) else [parsed]


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def metadata_plan(song_root: Path, index: dict[str, dict[str, Any]], index_sha: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    files = sorted(song_root.glob("pop909-*.json"), key=lambda item: item.name)
    if len(files) != 901:
        raise RuntimeError(f"expected 901 existing POP909 score files, found {len(files)} in {song_root}")
    changes: list[dict[str, Any]] = []
    missing_index: list[str] = []
    for path in files:
        sid = pop_id(path)
        source_row = index.get(sid)
        if source_row is None:
            missing_index.append(sid)
            continue
        original_bytes = path.read_bytes()
        original = json.loads(original_bytes.decode("utf-8"))
        if original.get("provenance", {}).get("provider") != "POP909":
            raise RuntimeError(f"not a POP909 provenance row: {path}")
        updated = copy.deepcopy(original)
        provenance = updated.setdefault("provenance", {})
        title = str(updated.get("title") or source_row.get("title") or "")
        artists = provenance.get("artists") or source_row.get("artists") or []
        artists = [str(item) for item in artists if str(item).strip()]
        artist_match = bool(PRIORITY_TITLES.intersection({title})) or bool(PRIORITY_ARTISTS.intersection(artists))
        tags = dedupe([*(provenance.get("tags") or []), "中文歌曲", "中文流行候选", "metadata-language-editorial"])
        if artist_match:
            tags = dedupe([*tags, "中文流行", "大众优先"])
        updated["category"] = (
            "中文流行 · 大众优先 · POP909 · 待音乐审核" if artist_match
            else "中文歌曲 · POP909 · 待音乐审核"
        )
        # The source index does not declare per-row BCP-47 language. `zh` is
        # an explicit editorial grouping so the UI can filter/search Chinese
        # music; it is not presented as a source-certified language claim.
        provenance["languageTags"] = dedupe([*(provenance.get("languageTags") or []), "zh"])
        provenance["tags"] = tags
        if not provenance.get("versionLabel"):
            provenance["versionLabel"] = "POP909来源编配版"
        if not provenance.get("rightsStatus"):
            provenance["rightsStatus"] = "candidate-unverified"
        updated_bytes = json_text(updated).encode("utf-8")
        # Metadata-only invariant: parsed musical fields must be identical.
        for key in ("notes", "bpm", "lengthMs", "keyInstrumentId", "warnings"):
            if updated.get(key) != original.get(key):
                raise RuntimeError(f"metadata migration changed score field {key}: {path}")
        changes.append({
            "path": path,
            "sourceIndexId": sid,
            "title": title,
            "artist": artists,
            "priority": artist_match,
            "beforeSha256": sha256_bytes(original_bytes),
            "afterSha256": sha256_bytes(updated_bytes),
            "before": original,
            "after": updated,
            "afterBytes": updated_bytes,
        })
    if missing_index:
        raise RuntimeError("missing POP909 index rows: " + ", ".join(sorted(missing_index)))
    report = {
        "runId": RUN_ID,
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "sourceIndex": str(POP_INDEX),
        "sourceIndexSha256": index_sha,
        "songRoot": str(song_root),
        "existingPop909": len(files),
        "plannedChanges": len(changes),
        "priorityCount": sum(1 for item in changes if item["priority"]),
        "nonPriorityCount": sum(1 for item in changes if not item["priority"]),
        "mainstreamArtistCount": len(PRIORITY_ARTISTS),
        "priorityClassification": "editorial title/artist grouping; not a platform chart certification",
        "languageClassification": "zh editorial grouping; source index languageStatus remains not-stated-by-source",
        "musicReview": "not-reviewed",
        "gameReview": "not-tested",
        "redistributionVerified": False,
        "pendingEnglishBatchV25Installed": False,
    }
    return changes, report


def backup_file(src: Path, backup_root: Path, label: str) -> Path:
    relative = src.name if label == "source" else Path(label) / src.name
    # label is only used to keep source/runtime trees separate; never accepts
    # an externally supplied path.
    target = backup_root / label / src.name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)
    return target


def backup_db(src: Path, backup_root: Path, label: str) -> Path:
    target = backup_root / f"{label}-catalog.db"
    shutil.copy2(src, target)
    return target


def update_catalog(catalog: Path, changed: list[dict[str, Any]]) -> dict[str, Any]:
    writable_mode = stat.S_IMODE(catalog.stat().st_mode)
    was_readonly = not (writable_mode & stat.S_IWRITE)
    if was_readonly:
        os.chmod(catalog, writable_mode | stat.S_IWRITE)
    updated_rows = 0
    try:
        with sqlite3.connect(catalog) as db:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE")
            for item in changed:
                path: Path = item["path"]
                relative = path.name
                row = db.execute(
                    "SELECT id, metadata_json FROM entries WHERE relative_path=?", (relative,)
                ).fetchone()
                if row is None:
                    raise RuntimeError(f"catalog entry missing for {catalog}: {relative}")
                entry_id, raw = row
                entry = json.loads(raw)
                entry["category"] = item["after"].get("category", entry.get("category", ""))
                entry["resourceHash"] = item["afterSha256"]
                entry["provenance"] = item["after"].get("provenance", entry.get("provenance", {}))
                entry_json = json_text(entry)
                db.execute(
                    "UPDATE entries SET content_hash=?, metadata_json=? WHERE id=?",
                    (item["afterSha256"], entry_json, entry_id),
                )
                # Existing title/artist keys remain valid. Append only the new
                # labels to the normalized search field so search can find
                # 中文歌曲 / 中文流行 / 大众优先 without reimplementing pinyin.
                search_row = db.execute(
                    "SELECT search_text FROM search_index WHERE entry_id=?", (entry_id,)
                ).fetchone()
                if search_row is None:
                    raise RuntimeError(f"search row missing for {catalog}: {entry_id}")
                current = search_row[0]
                labels = ["中文歌曲", "中文流行候选", "metadata-language-editorial", "中文（未细分）", "zh"]
                if item["priority"]:
                    labels.extend(["中文流行", "大众优先"])
                append = " | ".join(normalize_for_search(label) for label in labels)
                existing_terms = set(current.split(" | "))
                additions = [term for term in append.split(" | ") if term and term not in existing_terms]
                if additions:
                    current = current + " | " + " | ".join(additions)
                    db.execute("UPDATE search_index SET search_text=? WHERE entry_id=?", (current, entry_id))
                updated_rows += 1
            db.execute("PRAGMA integrity_check")
            result = db.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise RuntimeError(f"catalog integrity failed: {catalog}: {result}")
            db.commit()
    finally:
        if was_readonly:
            os.chmod(catalog, writable_mode)
    return {"catalog": str(catalog), "updatedRows": updated_rows, "restoredReadonly": was_readonly, "sha256": sha256_file(catalog)}


def apply_changes(changes: list[dict[str, Any]], report: dict[str, Any]) -> dict[str, Any]:
    if running_qinban():
        raise RuntimeError("QinBan is running; close it before metadata-only library migration")
    for target in (SOURCE_SONGS, RUNTIME_SONGS):
        if not target.is_dir() or not is_within(target, ROOT.parent):
            raise RuntimeError(f"unsafe target directory: {target}")
    if BACKUP_ROOT.exists():
        raise RuntimeError(f"refusing to overwrite existing backup/run directory: {BACKUP_ROOT}")
    BACKUP_ROOT.mkdir(parents=True)
    (BACKUP_ROOT / "source").mkdir()
    (BACKUP_ROOT / "runtime").mkdir()
    (BACKUP_ROOT / "source-catalog.db").write_bytes((SOURCE_SONGS / "catalog.db").read_bytes())
    (BACKUP_ROOT / "runtime-catalog.db").write_bytes((RUNTIME_SONGS / "catalog.db").read_bytes())
    for item in changes:
        backup_file(item["path"], BACKUP_ROOT, "source")
        backup_file(RUNTIME_SONGS / item["path"].name, BACKUP_ROOT, "runtime")
    (BACKUP_ROOT / "plan.json").write_text(json_text({
        **report,
        "backupRoot": str(BACKUP_ROOT),
        "changedFiles": [item["path"].name for item in changes],
    }), encoding="utf-8")
    # Write both trees from the same bytes, then update both catalogues. If a
    # later operation raises, the caller can restore the immutable backups.
    for item in changes:
        for path in (item["path"], RUNTIME_SONGS / item["path"].name):
            temp = path.with_name("." + path.name + ".chinese-pop.tmp")
            temp.write_bytes(item["afterBytes"])
            os.replace(temp, path)
    catalog_reports = [
        update_catalog(SOURCE_SONGS / "catalog.db", changes),
        update_catalog(RUNTIME_SONGS / "catalog.db", changes),
    ]
    source_equal_runtime = all(
        item["path"].read_bytes() == (RUNTIME_SONGS / item["path"].name).read_bytes() for item in changes
    )
    if not source_equal_runtime:
        raise RuntimeError("source/runtime POP909 score bytes diverged")
    final = {
        **report,
        "status": "PASS_METADATA_ONLY_APPLIED",
        "backupRoot": str(BACKUP_ROOT),
        "catalogReports": catalog_reports,
        "sourceRuntimePop909BytesEqual": source_equal_runtime,
        "nativeKeySendAttempts": 0,
        "executableTouched": False,
        "userDataTouched": False,
        "pendingEnglishBatchV25Installed": False,
    }
    (BACKUP_ROOT / "apply-report.json").write_text(json_text(final), encoding="utf-8")
    return final


def write_manifest(changes: list[dict[str, Any]], report: dict[str, Any]) -> Path:
    target = ROOT / "catalog-intake" / RUN_ID
    if target.exists():
        raise RuntimeError(f"refusing to overwrite manifest directory: {target}")
    target.mkdir(parents=True)
    songs = []
    for item in changes:
        after = item["after"]
        provenance = after["provenance"]
        songs.append({
            "file": item["path"].name,
            "sourceIndexId": item["sourceIndexId"],
            "title": item["title"],
            "artists": item["artist"],
            "priority": item["priority"],
            "workId": provenance.get("workId", ""),
            "editionId": provenance.get("editionId", ""),
            "versionLabel": provenance.get("versionLabel", ""),
            "languageTags": provenance.get("languageTags", []),
            "tags": provenance.get("tags", []),
            "sourceUrl": provenance.get("sourceUrl", ""),
            "sourceSha256": provenance.get("sourceSha256", ""),
            "rightsStatus": provenance.get("rightsStatus", ""),
            "musicReview": provenance.get("musicReview", ""),
            "gameReview": provenance.get("gameReview", ""),
            "redistributionVerified": provenance.get("redistributionVerified", False),
            "beforeSha256": item["beforeSha256"],
            "afterSha256": item["afterSha256"],
        })
    manifest = {
        **report,
        "status": "PLANNED_METADATA_ONLY" if not (BACKUP_ROOT / "apply-report.json").exists() else "APPLIED_METADATA_ONLY",
        "songs": songs,
    }
    path = target / "manifest.json"
    path.write_text(json_text(manifest), encoding="utf-8")
    readme = target / "README.md"
    readme.write_text(
        "# 中文流行优先元数据层\n\n"
        "本批只对已有 POP909 901 条条目补充可搜索的中文分组、编辑版语种标签、版本标签和 rightsStatus；没有修改任何 notes、BPM、音长、轨道或乐器映射。\n\n"
        "- `中文歌曲`：POP909 条目编辑分组；源索引本身不逐条声明语言。\n"
        "- `中文流行` / `大众优先`：基于透明的歌手/歌名优先集合，不等同于抖音、酷狗或网易云的实时榜单认证。\n"
        "- `candidate-unverified`、`not-reviewed`、`not-tested`、`redistributionVerified=false` 保持保守，不能据此宣称已清权、人工精校或原神内验收。\n"
        "- 待安装的 BFDB v25 英文批次没有被本批安装。\n",
        encoding="utf-8",
    )
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="apply metadata-only migration to source/runtime")
    args = parser.parse_args()
    index, index_sha = load_index()
    changes, report = metadata_plan(SOURCE_SONGS, index, index_sha)
    manifest = write_manifest(changes, report)
    # The dry-run manifest is useful even if no migration is applied. Applying
    # writes a second, immutable evidence report under .validation.
    print(json.dumps({**report, "manifest": str(manifest), "apply": args.apply}, ensure_ascii=False, indent=2))
    if args.apply:
        result = apply_changes(changes, report)
        # Update the manifest status without changing the content of score files.
        manifest_json = json.loads(manifest.read_text(encoding="utf-8"))
        manifest_json.update({"status": result["status"], "applyReport": str(BACKUP_ROOT / "apply-report.json")})
        manifest.write_text(json_text(manifest_json), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

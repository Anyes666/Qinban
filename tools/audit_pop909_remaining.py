from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import json
import re
import sqlite3
import unicodedata
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET

TOTAL_POP909 = 909
DEFAULT_COMMIT = "d83e6edba6872a704f5d3b8b32f5cb540088dae6"
POP_ID_RE = re.compile(r"^pop909:(\d{3})$")


def _norm_text(value: Any) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).replace("\u3000", " ")
    return re.sub(r"\s+", " ", text).strip()


def _key_text(value: Any) -> str:
    text = _norm_text(value).casefold()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)


VERSION_PATTERNS = [
    ("DJ", re.compile(r"(?i)\bd\s*j\b|(?<![A-Za-z])dj(?=[\u4e00-\u9fffA-Za-z0-9])")),
    ("original", re.compile(r"原版|原始版|original", re.I)),
    ("new", re.compile(r"新版|新版本|new\s*version|new\s*edit", re.I)),
    ("mute", re.compile(r"消音|消音版|无声版|無聲版", re.I)),
    ("live", re.compile(r"现场|現場|演唱会|演唱會|音乐会|音樂會|live", re.I)),
    ("remix", re.compile(r"remix|混音|重混", re.I)),
    ("instrumental", re.compile(r"纯音乐|純音樂|伴奏|instrumental|karaoke", re.I)),
    ("cover", re.compile(r"翻唱|cover", re.I)),
    ("acoustic", re.compile(r"acoustic|unplugged", re.I)),
    ("demo", re.compile(r"demo|小样|小樣", re.I)),
    ("edit", re.compile(r"remaster|重制|重製|edit|version", re.I)),
]


def extract_version_labels(title: Any, metadata_label: Any = "") -> tuple[str, list[str], str]:
    raw = _norm_text(title)
    labels: list[str] = []
    markers: list[str] = []
    for label, pattern in VERSION_PATTERNS:
        matches = list(pattern.finditer(raw))
        if matches:
            labels.append(label)
            markers.extend(m.group(0) for m in matches)
    metadata_raw = _norm_text(metadata_label)
    if metadata_raw:
        markers.append(metadata_raw)
        for token, label in (
            ("dj", "DJ"), ("原版", "original"), ("新版", "new"),
            ("消音", "mute"), ("现场", "live"), ("現場", "live"),
            ("伴奏", "instrumental"), ("纯音乐", "instrumental"),
            ("純音樂", "instrumental"), ("remix", "remix"),
            ("翻唱", "cover"), ("cover", "cover"),
        ):
            if token.casefold() in metadata_raw.casefold():
                labels.append(label)
    labels = sorted(set(labels), key=lambda x: [p[0] for p in VERSION_PATTERNS].index(x) if x in [p[0] for p in VERSION_PATTERNS] else 999)

    base = raw
    # Remove bracketed annotations only when they contain a recognized marker.
    bracket = re.compile(r"(\[[^\]]*\]|【[^】]*】|\([^)]*\)|（[^）]*）|\{[^}]*\}|《[^》]*》)")
    for match in list(bracket.finditer(base))[::-1]:
        fragment = match.group(0)
        if any(pattern.search(fragment) for _, pattern in VERSION_PATTERNS):
            base = base[:match.start()] + " " + base[match.end():]
    # DJ plus a trailing performer is a common suffix in this index.
    base = re.sub(r"(?i)(?:^|[\s·/_-])dj[\s·/_-]*[\u4e00-\u9fffA-Za-z0-9 _-]*$", " ", base)
    for _, pattern in VERSION_PATTERNS:
        base = pattern.sub(" ", base)
    base = re.sub(r"[\[\]【】()（）{}<>《》]", " ", base)
    base = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", " ", base)
    base = _norm_text(base)
    return base, labels, "|".join(markers)


def make_work_keys(title: Any, artist: Any, metadata_label: Any = "") -> dict[str, Any]:
    base, labels, markers = extract_version_labels(title, metadata_label)
    title_key = _key_text(base)
    artist_key = _key_text(artist)
    work_key = title_key if not artist_key else f"{title_key}::{artist_key}"
    return {
        "title_base": base,
        "normalized_title_key": title_key,
        "normalized_artist_key": artist_key,
        "normalized_work_key": work_key,
        "version_labels": labels,
        "version_markers": markers,
    }


def _column_index(cell_ref: str) -> int:
    letters = re.match(r"[A-Z]+", cell_ref.upper())
    if not letters:
        raise ValueError(f"invalid cell reference: {cell_ref}")
    result = 0
    for char in letters.group(0):
        result = result * 26 + ord(char) - ord("A") + 1
    return result


def _xml_local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _read_xlsx_index(path: Path) -> list[dict[str, str]]:
    ns_main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    ns_rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    ns_pkg = "http://schemas.openxmlformats.org/package/2006/relationships"
    with zipfile.ZipFile(path) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root:
                shared.append("".join(node.text or "" for node in item.iter() if _xml_local(node.tag) == "t"))
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
        target = None
        for sheet in workbook.iter(f"{{{ns_main}}}sheet"):
            if sheet.attrib.get("name") == "POP909":
                rid = sheet.attrib[f"{{{ns_rel}}}id"]
                target = rel_map[rid]
                break
        if target is None:
            raise ValueError("POP909 worksheet not found")
        sheet_path = target.lstrip("/")
        if not sheet_path.startswith("xl/"):
            sheet_path = "xl/" + sheet_path
        root = ET.fromstring(archive.read(sheet_path))
        rows: list[list[str]] = []
        for row in root.iter(f"{{{ns_main}}}row"):
            values: dict[int, str] = {}
            for cell in row:
                if _xml_local(cell.tag) != "c":
                    continue
                idx = _column_index(cell.attrib.get("r", ""))
                kind = cell.attrib.get("t")
                if kind == "inlineStr":
                    value = "".join(node.text or "" for node in cell.iter() if _xml_local(node.tag) == "t")
                else:
                    value_node = next((node for node in cell if _xml_local(node.tag) == "v"), None)
                    value = value_node.text if value_node is not None and value_node.text is not None else ""
                    if kind == "s" and value:
                        value = shared[int(value)]
                values[idx] = value
            if values:
                width = max(values)
                rows.append([values.get(i, "") for i in range(1, width + 1)])
    if not rows:
        raise ValueError("empty POP909 worksheet")
    headers = [_norm_text(x) for x in rows[0]]
    expected = ["song_id", "name", "artist", "modify_times", "num_beats_per_measure", "num_quavers_per_beat"]
    if headers != expected:
        raise ValueError(f"unexpected POP909 headers: {headers!r}")
    result = []
    for row in rows[1:]:
        padded = row + [""] * (len(headers) - len(row))
        item = {headers[i]: _norm_text(padded[i]) for i in range(len(headers))}
        item["song_id"] = item["song_id"].zfill(3)
        result.append(item)
    if len(result) != TOTAL_POP909:
        raise ValueError(f"expected {TOTAL_POP909} POP909 rows, got {len(result)}")
    if {item["song_id"] for item in result} != {f"{i:03d}" for i in range(1, TOTAL_POP909 + 1)}:
        raise ValueError("POP909 song IDs are not exactly 001..909")
    return sorted(result, key=lambda item: item["song_id"])


def _git_blob_sha1(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _load_sources(index_path: Path, archive_path: Path, tree_path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    tree_doc = json.loads(tree_path.read_text(encoding="utf-8-sig"))
    if tree_doc.get("truncated") is not False:
        raise ValueError("source-tree.json is truncated")
    commit = tree_doc.get("sha", "")
    if commit != DEFAULT_COMMIT:
        raise ValueError(f"unexpected POP909 source commit: {commit!r}")
    tree_map: dict[str, dict[str, Any]] = {}
    for entry in tree_doc.get("tree", []):
        path = entry.get("path", "")
        match = re.fullmatch(r"POP909/(\d{3})/(\d{3})\.mid", path)
        if match and match.group(1) == match.group(2):
            tree_map[match.group(1)] = entry
    if set(tree_map) != {f"{i:03d}" for i in range(1, TOTAL_POP909 + 1)}:
        raise ValueError(f"source-tree.json does not contain exactly {TOTAL_POP909} MIDI entries")
    sources: dict[str, dict[str, Any]] = {}
    with zipfile.ZipFile(archive_path) as archive:
        members = {}
        for info in archive.infolist():
            match = re.search(r"/POP909/(\d{3})/\1\.mid$", info.filename)
            if match:
                members[match.group(1)] = info
        if set(members) != set(tree_map):
            raise ValueError("source-archive.zip MIDI set differs from source-tree.json")
        for song_id in sorted(tree_map):
            info = members[song_id]
            data = archive.read(info)
            tree_entry = tree_map[song_id]
            git_sha = _git_blob_sha1(data)
            if len(data) != int(tree_entry["size"]):
                raise ValueError(f"source size mismatch for {song_id}")
            if git_sha != tree_entry["sha"]:
                raise ValueError(f"Git blob SHA mismatch for {song_id}")
            sources[song_id] = {
                "source_sha256": hashlib.sha256(data).hexdigest().upper(),
                "source_size": len(data),
                "git_blob_sha1": git_sha,
                "tree_sha": tree_entry["sha"],
                "archive_member": info.filename,
            }
    source_sha_groups: dict[str, list[str]] = defaultdict(list)
    for song_id, item in sources.items():
        source_sha_groups[item["source_sha256"]].append(song_id)
    duplicates = {key: sorted(value) for key, value in source_sha_groups.items() if len(value) > 1}
    meta = {
        "source_commit": commit,
        "expected_source_commit": DEFAULT_COMMIT,
        "source_commit_matches_expected": commit == DEFAULT_COMMIT,
        "archive_midi_count": len(sources),
        "source_sha_duplicate_groups": duplicates,
        "index_sha256": _sha256_file(index_path),
        "archive_sha256": _sha256_file(archive_path),
        "tree_sha256": _sha256_file(tree_path),
    }
    return sources, meta


def _load_catalog(catalog_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    uri = f"file:{catalog_path.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        count = connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        rows = connection.execute(
            "SELECT id, work_id, relative_path, content_hash, original_hash, metadata_json FROM entries ORDER BY id"
        ).fetchall()
    finally:
        connection.close()
    if count != len(rows):
        raise ValueError("catalog row count changed during read")
    current: list[dict[str, Any]] = []
    for entry_id, work_id, relative_path, content_hash, original_hash, metadata_json in rows:
        metadata = json.loads(metadata_json)
        provenance = metadata.get("provenance") or {}
        if provenance.get("provider") != "POP909":
            continue
        # A work can have multiple POP909 editions (for example an original
        # and a DJ/影视 version), so work_id is not a unique source-song key.
        # Resolve the source identity from the normalized resource path first;
        # fall back to the pinned source URL for older catalog fixtures.
        path_match = re.fullmatch(r"pop909-(\d{3})\.json", str(relative_path or ""))
        source_url = str(provenance.get("sourceUrl") or "")
        url_match = re.search(r"/POP909/(\d{3})/\1\.mid(?:$|[?#])", source_url)
        if path_match and url_match and path_match.group(1) != url_match.group(1):
            raise ValueError("catalog POP909 path/source URL identity mismatch: " + str(relative_path))
        match = path_match or url_match
        if not match:
            # Keep compatibility with older catalog fixtures that only carried
            # the work identity; real current entries have a source path.
            match = POP_ID_RE.fullmatch(str(work_id or ""))
        if not match:
            raise ValueError("POP909 entry has no stable source-song identity: " + str(relative_path))
        song_id = match.group(1)
        keys = make_work_keys(metadata.get("title", ""), provenance.get("artist", ""), provenance.get("versionLabel", ""))
        current.append({
            "catalog_entry_id": entry_id,
            "song_id": song_id,
            "work_id": work_id,
            "relative_path": relative_path,
            "title": _norm_text(metadata.get("title", "")),
            "artist": _norm_text(provenance.get("artist", "")),
            "version_label_raw": _norm_text(provenance.get("versionLabel", "")),
            "content_hash": str(content_hash or "").upper(),
            "original_hash": str(original_hash or "").upper(),
            "source_sha256": str(provenance.get("sourceSha256", "")).upper(),
            **keys,
        })
    if len(current) != len({item["song_id"] for item in current}):
        raise ValueError("catalog contains duplicate POP909 song IDs")
    source_hash_groups: dict[str, list[str]] = defaultdict(list)
    for item in current:
        if item["source_sha256"]:
            source_hash_groups[item["source_sha256"]].append(item["song_id"])
    duplicates = {key: sorted(value) for key, value in source_hash_groups.items() if len(value) > 1}
    return current, {"catalog_entry_count": count, "catalog_pop909_count": len(current), "catalog_source_sha_duplicate_groups": duplicates}


def _similar_items(item: dict[str, Any], candidates: Iterable[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    results = []
    left = item["normalized_title_key"]
    if not left:
        return results
    for other in candidates:
        if other.get("song_id") == item.get("song_id") and other.get("source") == item.get("source"):
            continue
        right = other.get("normalized_title_key", "")
        if not right or right == left:
            continue
        ratio = difflib.SequenceMatcher(None, left, right).ratio()
        contained = len(left) >= 4 and (left in right or right in left)
        if ratio >= 0.86 or contained:
            results.append({
                "song_id": other.get("song_id", ""),
                "title": other.get("title", ""),
                "artist": other.get("artist", ""),
                "score": round(ratio, 4),
            })
    results.sort(key=lambda value: (-value["score"], value["song_id"]))
    return results[:limit]


def _artist_distribution(all_items: list[dict[str, Any]], current_ids: set[str]) -> list[dict[str, Any]]:
    totals = Counter(item["artist"] or "<unknown>" for item in all_items)
    collected = Counter(item["artist"] or "<unknown>" for item in all_items if item["song_id"] in current_ids)
    result = []
    for artist in sorted(totals, key=lambda value: (-totals[value], value)):
        result.append({
            "artist": "" if artist == "<unknown>" else artist,
            "total": totals[artist],
            "collected": collected[artist],
            "remaining": totals[artist] - collected[artist],
        })
    return result


def build_audit(workspace: Path, batch_size: int = 100) -> dict[str, Any]:
    intake = workspace / "catalog-intake" / "pop100-2026-10-06"
    index_path = intake / "index.xlsx"
    archive_path = intake / "source-archive.zip"
    tree_path = intake / "source-tree.json"
    catalog_path = workspace / "Songs" / "catalog.db"
    for path in (index_path, archive_path, tree_path, catalog_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    index_rows = _read_xlsx_index(index_path)
    sources, source_meta = _load_sources(index_path, archive_path, tree_path)
    current, catalog_meta = _load_catalog(catalog_path)
    current_by_id = {item["song_id"]: item for item in current}
    current_ids = set(current_by_id)
    source_items: list[dict[str, Any]] = []
    for row in index_rows:
        song_id = row["song_id"]
        keys = make_work_keys(row["name"], row["artist"])
        source_items.append({
            "source": "POP909",
            "song_id": song_id,
            "title": row["name"],
            "artist": row["artist"],
            "modify_times": row["modify_times"],
            "num_beats_per_measure": row["num_beats_per_measure"],
            "num_quavers_per_beat": row["num_quavers_per_beat"],
            "status": "collected" if song_id in current_ids else "remaining",
            **keys,
            **sources[song_id],
        })
    for item in source_items:
        current_item = current_by_id.get(item["song_id"])
        item["catalog_entry_id"] = current_item["catalog_entry_id"] if current_item else ""
        item["current_title"] = current_item["title"] if current_item else ""
        item["current_version_label_raw"] = current_item["version_label_raw"] if current_item else ""
        item["current_source_sha256"] = current_item["source_sha256"] if current_item else ""
        item["source_sha_matches_catalog"] = bool(current_item and item["source_sha256"] == current_item["source_sha256"])

    current_work_groups: dict[str, list[str]] = defaultdict(list)
    source_work_groups: dict[str, list[str]] = defaultdict(list)
    current_title_groups: dict[str, list[str]] = defaultdict(list)
    source_title_groups: dict[str, list[str]] = defaultdict(list)
    for item in current:
        current_work_groups[item["normalized_work_key"]].append(item["song_id"])
        current_title_groups[item["normalized_title_key"]].append(item["song_id"])
    for item in source_items:
        source_work_groups[item["normalized_work_key"]].append(item["song_id"])
        source_title_groups[item["normalized_title_key"]].append(item["song_id"])
    version_conflict_groups: dict[str, dict[str, Any]] = {}
    for key, ids in source_work_groups.items():
        current_matches = [song_id for song_id in current_work_groups.get(key, []) if song_id not in ids]
        labels = [source_items[int(song_id) - 1]["version_labels"] for song_id in ids]
        has_label = any(labels) or any(current_by_id.get(song_id, {}).get("version_labels") for song_id in current_matches)
        if len(ids) > 1 or current_matches:
            version_conflict_groups[key] = {
                "normalized_work_key": key,
                "source_ids": sorted(ids),
                "current_ids": sorted(current_matches),
                "has_explicit_version_label": bool(has_label),
                "kind": "version-or-work-collision",
            }
    source_sha_groups: dict[str, list[str]] = defaultdict(list)
    for item in source_items:
        source_sha_groups[item["source_sha256"]].append(item["song_id"])
    source_sha_duplicates = {key: sorted(value) for key, value in source_sha_groups.items() if len(value) > 1}

    current_items_for_similarity = [{**item, "source": "catalog"} for item in current]
    for item in source_items:
        item["same_work_current_ids"] = sorted(x for x in current_work_groups.get(item["normalized_work_key"], []) if x != item["song_id"])
        item["same_title_source_ids"] = sorted(x for x in source_title_groups.get(item["normalized_title_key"], []) if x != item["song_id"])
        item["similar_source_titles"] = _similar_items(item, source_items)
        item["similar_current_titles"] = _similar_items(item, current_items_for_similarity)
        item["version_conflict"] = bool(item["same_work_current_ids"] or len(source_work_groups[item["normalized_work_key"]]) > 1)
        item["same_work_current"] = bool(item["same_work_current_ids"])
        item["near_title_match"] = bool(item["similar_source_titles"] or item["similar_current_titles"])
        item["source_sha_duplicate"] = len(source_sha_groups[item["source_sha256"]]) > 1
        item["recommended_version_label"] = item["version_labels"][0] if len(item["version_labels"]) == 1 else ("+".join(item["version_labels"]) if item["version_labels"] else "")

    remaining = [item for item in source_items if item["status"] == "remaining"]
    current_artist_counts = Counter(item["artist"] for item in current)
    for item in remaining:
        risk = 0
        reasons = []
        if item["source_sha_duplicate"]:
            risk += 1000
            reasons.append("source-sha-duplicate")
        if item["same_work_current"]:
            risk += 40
            reasons.append("same-normalized-work-as-current")
        if item["same_title_source_ids"]:
            risk += 30
            reasons.append("same-normalized-title-in-pop909")
        if item["near_title_match"]:
            risk += 20
            reasons.append("near-title-match")
        if item["version_labels"]:
            risk += 10
            reasons.append("explicit-version-label")
        item["candidate_risk_score"] = risk
        item["candidate_review_reasons"] = reasons
        item["candidate_recommendation"] = "review" if reasons else "ready-for-next-batch-review"
        item["current_artist_count"] = current_artist_counts[item["artist"]]
    remaining.sort(key=lambda item: (item["candidate_risk_score"], item["current_artist_count"], item["song_id"]))
    for rank, item in enumerate(remaining, 1):
        item["candidate_rank"] = rank
        item["recommended_next_batch"] = rank <= batch_size and not item["source_sha_duplicate"]

    conflict_records = [item for item in source_items if item["version_conflict"]]
    collected = sum(item["status"] == "collected" for item in source_items)
    collected_hash_mismatches = [
        item for item in source_items
        if item["status"] == "collected" and not item["source_sha_matches_catalog"]
    ]
    return {
        "summary": {
            "pop909_total": TOTAL_POP909,
            "catalog_entry_count": catalog_meta["catalog_entry_count"],
            "catalog_pop909_collected": collected,
            "pop909_remaining": TOTAL_POP909 - collected,
            "source_archive_midi_count": source_meta["archive_midi_count"],
            "source_sha_duplicate_group_count": len(source_sha_duplicates),
            "source_sha_duplicate_record_count": sum(len(v) for v in source_sha_duplicates.values()),
            "catalog_source_sha_mismatch_record_count": len(collected_hash_mismatches),
            "version_conflict_group_count": len(version_conflict_groups),
            "version_conflict_record_count": len(conflict_records),
            "explicit_version_record_count": sum(bool(item["version_labels"]) for item in source_items),
            "remaining_near_title_record_count": sum(item["near_title_match"] for item in remaining),
            "remaining_explicit_version_record_count": sum(bool(item["version_labels"]) for item in remaining),
            "next_batch_size": min(batch_size, len(remaining)),
        },
        "inputs": {
            "index": str(index_path),
            "source_archive": str(archive_path),
            "source_tree": str(tree_path),
            "catalog_db": str(catalog_path),
            **source_meta,
            **catalog_meta,
        },
        "source_sha_duplicates": source_sha_duplicates,
        "version_conflict_groups": version_conflict_groups,
        "singer_distribution": _artist_distribution(source_items, current_ids),
        "items": source_items,
        "remaining": remaining,
    }


def _csv_value(value: Any) -> str:
    if isinstance(value, list):
        return ";".join(str(x) for x in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, bool):
        return "1" if value else "0"
    return "" if value is None else str(value)


def write_report(result: dict[str, Any], output_dir: Path) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty report directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "audit.json"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fields = [
        "song_id", "status", "title", "artist", "title_base", "normalized_title_key", "normalized_artist_key",
        "normalized_work_key", "version_labels", "version_markers", "source_sha256", "source_size", "git_blob_sha1",
        "catalog_entry_id", "source_sha_matches_catalog", "same_work_current_ids", "same_title_source_ids",
        "similar_source_titles", "similar_current_titles", "version_conflict", "near_title_match", "source_sha_duplicate",
        "recommended_version_label", "candidate_rank", "candidate_risk_score", "candidate_review_reasons", "recommended_next_batch",
    ]
    for name, rows in (("pop909_all.csv", result["items"]), ("pop909_remaining.csv", result["remaining"])):
        with (output_dir / name).open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({field: _csv_value(row.get(field)) for field in fields})
    with (output_dir / "singer_distribution.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        fields = ["artist", "total", "collected", "remaining"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(result["singer_distribution"])
    summary = result["summary"]
    lines = [
        "# POP909 remaining audit",
        "",
        "Read-only audit of the fixed POP909 source materials and Songs/catalog.db.",
        "",
        f"- POP909 total: {summary['pop909_total']}",
        f"- catalog.db total entries: {summary['catalog_entry_count']}",
        f"- collected POP909 entries: {summary['catalog_pop909_collected']}",
        f"- remaining POP909 entries: {summary['pop909_remaining']}",
        f"- version/work collision groups: {summary['version_conflict_group_count']}",
        f"- records in version/work collision groups: {summary['version_conflict_record_count']}",
        f"- source SHA duplicate groups: {summary['source_sha_duplicate_group_count']}",
        f"- catalog source-SHA mismatches among collected rows: {summary['catalog_source_sha_mismatch_record_count']}",
        f"- explicit version-label records: {summary['explicit_version_record_count']}",
        f"- remaining records with near-title matches: {summary['remaining_near_title_record_count']}",
        f"- recommended next batch rows: {summary['next_batch_size']}",
        "",
        "Candidate ranking is deterministic: source-SHA duplicates, normalized-work collisions, normalized-title collisions, near-title matches, explicit version labels, then current artist count and POP909 ID.",
        "`recommended_next_batch=1` marks the first configured batch after ranking; all remaining rows are retained in pop909_remaining.csv.",
        "No network access, extraction to Songs, catalog writes, EXE writes, or UserData writes are performed by this tool.",
    ]
    (output_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only POP909 remaining-capacity audit")
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args(argv)
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be positive")
    result = build_audit(args.workspace.resolve(), args.batch_size)
    write_report(result, args.output.resolve())
    print(json.dumps(result["summary"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())




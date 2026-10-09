"""Metadata-first MutopiaProject MIDI intake.

This tool consumes the pinned local MutopiaProject LilyPond repository and the
official Mutopia MIDI endpoint. It writes an isolated intake directory only; it
never touches QinBan Songs, an EXE, UserData, or a game/window.
"""
from __future__ import annotations

import argparse
import collections
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import unicodedata
import urllib.request
from typing import Any, Callable, Iterable

try:
    from smf_reference import parse_smf
except ModuleNotFoundError:
    from tools.smf_reference import parse_smf

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_ROOT = ROOT.parent / ".tools" / "sources" / "mutopia-project-2026-10-06"
DEFAULT_OUTPUT_ROOT = ROOT / "catalog-intake" / "mutopia-2026-10-06"
MUTOPIA_BASE_URL = "https://www.mutopiaproject.org/ftp/"
MUTOPIA_REPOSITORY_URL = "https://github.com/MutopiaProject/MutopiaProject"
MUTOPIA_LICENSE_URL = "https://creativecommons.org/publicdomain/mark/1.0/"
MUTOPIA_LICENSE_CATALOG: dict[str, dict[str, str]] = {
    "public domain": {
        "label": "Public Domain (source header)",
        "url": MUTOPIA_LICENSE_URL,
        "tag": "public-domain",
        "kind": "public-domain",
    },
    "publicdomain": {
        "label": "Public Domain (source header)",
        "url": MUTOPIA_LICENSE_URL,
        "tag": "public-domain",
        "kind": "public-domain",
    },
    "creative commons attribution-sharealike 4.0": {
        "label": "CC BY-SA 4.0",
        "url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "tag": "cc-by-sa-4.0",
        "kind": "cc-by-sa",
    },
    "creative commons attribution 4.0": {
        "label": "CC BY 4.0",
        "url": "https://creativecommons.org/licenses/by/4.0/",
        "tag": "cc-by-4.0",
        "kind": "cc-by",
    },
    "creative commons attribution-sharealike 3.0": {
        "label": "CC BY-SA 3.0",
        "url": "https://creativecommons.org/licenses/by-sa/3.0/",
        "tag": "cc-by-sa-3.0",
        "kind": "cc-by-sa",
    },
    "creative commons attribution 3.0": {
        "label": "CC BY 3.0",
        "url": "https://creativecommons.org/licenses/by/3.0/",
        "tag": "cc-by-3.0",
        "kind": "cc-by",
    },
    "creative commons attribution-sharealike 4.0 international": {
        "label": "CC BY-SA 4.0 International",
        "url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "tag": "cc-by-sa-4.0",
        "kind": "cc-by-sa",
    },
}
MUTOPIA_LICENSES = set(MUTOPIA_LICENSE_CATALOG)
MAX_MIDI_BYTES = 16 * 1024 * 1024
MIN_DURATION_MS = 1000.0
MAX_DURATION_MS = 1_800_000.0
MAX_NOTES = 100_000
MIN_BPM = 20.0
MAX_BPM = 400.0
CORE_TITLE_LIMIT = 180
SOURCE_SHA_RE = re.compile(r"^[0-9a-fA-F]{64}$")
MUTOPIA_LICENSES = {"public domain", "publicdomain"}
EXCLUDED_FRAGMENT_STEMS = {
    "header", "lyrics", "lyric", "basso", "bc", "global", "parts", "score", "music",
}
TOP_LEVEL_FIELDS = {
    "Songs", "SourceCommit", "SourceRecord", "RetrievedAtUtc", "Provider", "BatchKind", "SourceUrl",
    "License", "LicenseUrl", "RightsStatus", "RightsNote", "RedistributionVerified", "Author", "Category",
    "Description", "IdPattern", "SmartInterludesDefault",
}
SONG_FIELDS = {
    "Id", "Title", "Artist", "MidiPath", "ReferencePath", "SourceUrl", "SourceSha256", "LanguageTags",
    "Artists", "Provider", "SourceCommit", "SourceRecord", "BatchKind", "Author", "Category", "Description",
    "IdPattern", "SmartInterludes", "WorkId", "EditionId", "VersionLabel", "License", "LicenseUrl",
    "RightsStatus", "RightsNote", "Album", "Aliases", "Tags", "Completeness", "MusicReview", "GameReview",
    "RedistributionVerified",
}


class IntakeError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _write_json_new(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
    except FileExistsError as exc:
        raise IntakeError(f"refusing to overwrite {path}") from exc


def _write_text_new(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(value)
    except FileExistsError as exc:
        raise IntakeError(f"refusing to overwrite {path}") from exc


def _write_bytes_new(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(value)
    except FileExistsError as exc:
        raise IntakeError(f"refusing to overwrite {path}") from exc


def _raw(value: Any) -> str:
    return "" if value is None else str(value)


def _bounded_title(value: Any) -> tuple[str, bool]:
    text = _raw(value).strip()
    if len(text) <= CORE_TITLE_LIMIT:
        return text, False
    suffix = "..."
    return text[:CORE_TITLE_LIMIT - len(suffix)].rstrip() + suffix, True


def _slug(value: Any, fallback: str = "unknown") -> str:
    text = _raw(value).strip()
    # WorkId must remain stable when two source headers differ only by a Unicode
    # accent spelling (for example Frederic vs Fr?d?ric). Keep the public display
    # text unchanged; fold only the identity token.
    text = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return text[:96] or fallback


def _header_field(text: str, name: str) -> str:
    # Mutopia headers normally use a simple quoted value. We deliberately do not
    # evaluate LilyPond code or infer missing metadata.
    pattern = rf"(?m)^\s*{re.escape(name)}\s*=\s*\"([^\"]*)\""
    match = re.search(pattern, text[:64 * 1024])
    return match.group(1).strip() if match else ""


def _license_key(value: Any) -> str:
    return re.sub(r"\s+", " ", _raw(value).strip().casefold())


def _license_info(value: Any) -> dict[str, str] | None:
    info = MUTOPIA_LICENSE_CATALOG.get(_license_key(value))
    return dict(info) if info is not None else None


def _resolve_license_filter(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    key = _license_key(value)
    if key in MUTOPIA_LICENSE_CATALOG:
        return key
    for candidate, info in MUTOPIA_LICENSE_CATALOG.items():
        if _license_key(info["label"]) == key:
            return candidate
    raise IntakeError(f"unsupported Mutopia license filter: {value}")


def _rights_note(info: dict[str, str]) -> str:
    label = info["label"]
    if info["kind"] == "public-domain":
        return f"Source header declares {label}; exact bundled-source scope remains candidate-unverified."
    if info["kind"] == "cc-by-sa":
        return (
            f"Source header declares {label}; attribution and ShareAlike obligations, "
            "exact bundled-source scope, and treatment of derived game notation remain candidate-unverified."
        )
    return (
        f"Source header declares {label}; attribution obligations, exact bundled-source scope, "
        "and treatment of derived game notation remain candidate-unverified."
    )


def _source_candidates(source_root: Path, *, license_filter: str | None = None) -> list[dict[str, Any]]:
    resolved_filter = _resolve_license_filter(license_filter)
    ftp = source_root / "ftp"
    if not ftp.is_dir():
        raise IntakeError(f"Mutopia ftp directory does not exist: {ftp}")
    rows: list[dict[str, Any]] = []
    for path in sorted(ftp.rglob("*.ly"), key=lambda item: item.relative_to(ftp).as_posix().casefold()):
        try:
            data = path.read_bytes()
            text = data.decode("utf-8", errors="replace")
        except OSError as exc:
            raise IntakeError(f"cannot read LilyPond source: {path}: {exc}") from exc
        title = _header_field(text, "title")
        composer = _header_field(text, "composer")
        license_text = _header_field(text, "license")
        license_key = _license_key(license_text)
        license_info = _license_info(license_text)
        footer = _header_field(text, "footer")
        if not title or not composer or license_info is None:
            continue
        if resolved_filter is not None and license_key != resolved_filter:
            continue
        if path.stem.casefold() in EXCLUDED_FRAGMENT_STEMS:
            continue
        relative = path.relative_to(ftp).as_posix()
        candidates: list[str] = [relative[:-3] + ".mid"]
        if path.parent.name.endswith("-lys"):
            base_dir = path.parent.name[:-4]
            parent = path.parent.parent.relative_to(ftp).as_posix()
            candidates.extend((f"{parent}/{base_dir}.mid", f"{parent}/{path.stem}.mid"))
        candidates.append(f"{path.parent.relative_to(ftp).as_posix()}/{path.stem}.mid")
        candidates = list(dict.fromkeys(candidates))
        title_display, title_truncated = _bounded_title(title)
        rows.append({
            "lyPath": relative,
            "lyAbsolute": path,
            "lySha256": sha256_bytes(data),
            "title": title,
            "titleDisplay": title_display,
            "titleWasTruncated": title_truncated,
            "composer": composer,
            "license": license_text,
            "licenseKey": license_key,
            "licenseInfo": license_info,
            "footer": footer,
            "midCandidates": candidates,
        })
    return rows


def _work_id(title: str, composer: str) -> str:
    return f"mutopia-work:{_slug(title, 'untitled')}::{_slug(composer, 'unknown-composer')}"


def _edition_id(commit: str, ly_path: str) -> str:
    token = hashlib.sha1(ly_path.encode("utf-8")).hexdigest()[:20]
    return f"mutopia:{commit[:12]}:{token}"


def _version_label(row: dict[str, Any], commit: str) -> str:
    basis = row["footer"] or f"commit {commit[:12]}"
    label = f"Mutopia {basis} / {row['lyPath']}"
    return label if len(label) <= 256 else label[:253].rstrip() + "..."


def _manifest_value(record: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in record:
            return record[name]
    return None


def _load_exclusions(paths: Iterable[Path | str] | Path | str | None) -> dict[str, set[str]]:
    source_hashes: set[str] = set()
    edition_ids: set[str] = set()
    if paths is None:
        return {"sourceHashes": source_hashes, "editionIds": edition_ids}
    raw_paths = [paths] if isinstance(paths, (Path, str)) else list(paths)
    for raw in raw_paths:
        path = Path(raw).expanduser().resolve()
        if path.is_dir():
            path = path / "manifest.json"
        if not path.is_file():
            raise IntakeError(f"exclude manifest does not exist: {path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise IntakeError(f"invalid exclude manifest: {path}: {exc}") from exc
        songs = payload.get("Songs") if isinstance(payload, dict) else None
        if not isinstance(songs, list):
            songs = payload.get("songs") if isinstance(payload, dict) else None
        if not isinstance(songs, list):
            raise IntakeError(f"exclude manifest has no Songs list: {path}")
        for index, song in enumerate(songs, start=1):
            if not isinstance(song, dict):
                raise IntakeError(f"exclude manifest Songs[{index}] is not an object: {path}")
            source = _raw(_manifest_value(song, "SourceSha256", "sourceSha256")).strip().upper()
            edition = _raw(_manifest_value(song, "EditionId", "editionId")).strip()
            if source and SOURCE_SHA_RE.fullmatch(source):
                source_hashes.add(source)
            if edition:
                edition_ids.add(edition)
    return {"sourceHashes": source_hashes, "editionIds": edition_ids}


def _download(url: str, *, opener: Callable[..., Any] | None = None) -> bytes:
    opener = opener or urllib.request.urlopen
    request = urllib.request.Request(url, headers={"User-Agent": "QinBan-Mutopia-Intake/1.0"})
    try:
        with opener(request, timeout=30) as response:
            data = response.read(MAX_MIDI_BYTES + 1)
    except Exception as exc:
        raise IntakeError(f"MIDI download failed: {url}: {exc}") from exc
    if len(data) > MAX_MIDI_BYTES:
        raise IntakeError(f"MIDI exceeds size budget: {url}")
    return data


def _download_candidate(row: dict[str, Any], *, opener: Callable[..., Any] | None = None) -> dict[str, Any]:
    failures: list[str] = []
    for mid_path in row["midCandidates"]:
        url = MUTOPIA_BASE_URL + mid_path
        try:
            data = _download(url, opener=opener)
            reference = parse_smf(data)
            notes = reference.get("notes")
            length = float(reference.get("lengthMs", 0))
            bpm = float(reference.get("bpm", 0))
            if not isinstance(notes, list) or not notes:
                raise IntakeError("SMF has no notes")
            if length < MIN_DURATION_MS or length > MAX_DURATION_MS:
                raise IntakeError(f"duration outside budget: {length}")
            if not math.isfinite(bpm) or bpm < MIN_BPM or bpm > MAX_BPM:
                raise IntakeError(f"BPM outside QinBan budget: {bpm}")
            if len(notes) > MAX_NOTES:
                raise IntakeError("note count exceeds budget")
            source_hash = sha256_bytes(data)
            return {**row, "midPath": mid_path, "sourceUrl": url, "data": data,
                    "sourceSha256": source_hash, "reference": reference}
        except Exception as exc:
            failures.append(f"{mid_path}: {exc}")
    raise IntakeError("; ".join(failures) or "no MIDI candidate")


def _build_item(row: dict[str, Any], output: Path, commit: str, retrieved_at: str) -> dict[str, Any]:
    stem = "mutopiaproject-" + hashlib.sha1(row["lyPath"].encode("utf-8")).hexdigest()[:20]
    midi_path = output / "midi" / f"{stem}.mid"
    reference_path = output / "references" / f"{stem}.json"
    ly_path = output / "source" / "ly" / f"{stem}.ly"
    metadata_path = output / "metadata" / "records" / f"{stem}.json"
    work_id = _work_id(row["title"], row["composer"])
    edition_id = _edition_id(commit, row["lyPath"])
    version_label = _version_label(row, commit)
    reference = dict(row["reference"])
    reference.update({
        "schemaVersion": "mutopia-independent-smf-reference-v1",
        "sourcePath": f"./midi/{stem}.mid",
        "sourceUrl": row["sourceUrl"],
        "sourceSha256": row["sourceSha256"],
        "parserScope": "independent Python SMF parser; no audio inference, transcription, or game validation",
    })
    license_info = dict(row["licenseInfo"])
    rights_note = _rights_note(license_info)
    metadata_document = {
        "schemaVersion": "mutopia-source-record-v1",
        "retrievedAtUtc": retrieved_at,
        "provider": "MutopiaProject",
        "source": {
            "repository": MUTOPIA_REPOSITORY_URL,
            "commit": commit,
            "lyPath": row["lyPath"],
            "lySha256": row["lySha256"],
            "midiPath": row["midPath"],
            "midiUrl": row["sourceUrl"],
            "midiSha256": row["sourceSha256"],
        },
        "header": {
            "title": row["title"], "composer": row["composer"], "license": row["license"], "footer": row["footer"],
        },
        "derived": {
            "workId": work_id, "editionId": edition_id, "versionLabel": version_label,
            "displayTitle": row["titleDisplay"], "titleWasTruncated": row["titleWasTruncated"],
            "rights": {
                "sourceHeaderLicense": row["license"],
                "license": license_info["label"],
                "licenseUrl": license_info["url"],
                "redistributionVerified": False,
                "note": rights_note,
            },
        },
        "qualification": {
            "status": "STRUCTURAL_CANDIDATE_ONLY", "qualityGrade": "ungraded",
            "rightsReview": "required", "musicReview": "required", "gameReview": "required",
        },
    }
    item = {
        "id": stem, "title": row["titleDisplay"], "artist": row["composer"],
        "workId": work_id, "editionId": edition_id, "versionLabel": version_label,
        "midiPath": str(midi_path.resolve()), "referencePath": str(reference_path.resolve()),
        "lyPath": str(ly_path.resolve()), "metadataPath": str(metadata_path.resolve()),
        "sourceUrl": row["sourceUrl"], "sourceSha256": row["sourceSha256"],
        "sourceLySha256": row["lySha256"], "sourceLyRelativePath": row["lyPath"],
        "licenseInfo": license_info,
        "sourceTitle": row["title"], "sourceComposer": row["composer"], "sourceLicense": row["license"],
        "reference": reference, "metadataDocument": metadata_document,
    }
    return item


def _decorated_display_title(source_title: str, suffix: str) -> tuple[str, bool]:
    source_title = source_title.strip() or "Untitled"
    suffix = suffix.strip()
    full = f"{source_title} ({suffix})"
    if len(full) <= CORE_TITLE_LIMIT:
        return full, False
    available = CORE_TITLE_LIMIT - len(suffix) - 2
    if available <= 0:
        return _bounded_title(full)
    return source_title[:available].rstrip() + f" ({suffix})", True


def _edition_suffix(item: dict[str, Any]) -> str:
    label = _raw(item.get("versionLabel"))
    match = re.search(r"Mutopia-\d{4}/\d{2}/\d{2}-(\d+)", label)
    if match:
        return f"Mutopia edition {match.group(1)}"
    path = _raw(item.get("sourceLyRelativePath"))
    return f"edition {Path(path).stem or _raw(item.get('editionId'))[-8:]}"


def _disambiguate_duplicate_display_titles(
    items: list[dict[str, Any]], *, avoid_titles: Iterable[str] = ()
) -> None:
    # Runtime search/title collision policy is global: two unrelated works with
    # the same display title must not be emitted with identical titles, even when
    # their composers differ. Identity still comes from WorkId/EditionId; this
    # only makes the user-facing title deterministic and collision-safe.
    groups: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for item in items:
        groups[_raw(item.get("sourceTitle")).casefold()].append(item)
    avoided = {_raw(title).strip().casefold() for title in avoid_titles if _raw(title).strip()}
    for title_key, group in groups.items():
        if len(group) < 2 and title_key not in avoided:
            continue
        used: set[str] = set()
        for item in sorted(group, key=lambda value: (value.get("editionId", ""), value.get("id", ""))):
            suffix = _edition_suffix(item)
            title, truncated = _decorated_display_title(_raw(item.get("sourceTitle")), suffix)
            if title in used:
                title, truncated = _decorated_display_title(
                    _raw(item.get("sourceTitle")), f"{suffix} / {_raw(item.get('editionId'))[-8:]}"
                )
            used.add(title)
            item["title"] = title
            metadata_document = item.get("metadataDocument")
            if isinstance(metadata_document, dict):
                derived = metadata_document.setdefault("derived", {})
                derived["displayTitle"] = title
                derived["titleWasTruncated"] = truncated
                derived["displayTitleDisambiguation"] = {
                    "reason": "duplicate-title-and-artist",
                    "suffix": suffix,
                    "workIdUnchanged": True,
                    "editionIdUnchanged": True,
                }


def _contract_song(item: dict[str, Any]) -> dict[str, Any]:
    info = dict(item["licenseInfo"])
    rights_note = _rights_note(info)
    return {
        "Id": item["id"], "Title": item["title"], "Artist": item["artist"],
        "MidiPath": item["midiPath"], "ReferencePath": item["referencePath"],
        "SourceUrl": item["sourceUrl"], "SourceSha256": item["sourceSha256"],
        "LanguageTags": [], "Artists": [item["artist"]], "Provider": "MutopiaProject",
        "SourceCommit": item["sourceCommit"], "SourceRecord": MUTOPIA_REPOSITORY_URL,
        "BatchKind": f"mutopia-{info['tag']}-candidate-intake", "Author": "MutopiaProject / source typesetter",
        "Category": f"Mutopia - {info['label']} candidate",
        "Description": f"Mutopia {info['label']} header candidate with independent SMF timing evidence; rights/music/game review pending",
        "IdPattern": "mutopiaproject-<stable-path-hash>", "SmartInterludes": True,
        "WorkId": item["workId"], "EditionId": item["editionId"], "VersionLabel": item["versionLabel"],
        "License": info["label"], "LicenseUrl": info["url"],
        "RightsStatus": "candidate-unverified",
        "RightsNote": rights_note,
        "Album": "", "Aliases": [], "Tags": ["mutopia", f"{info['tag']}-candidate"],
        "Completeness": "source-structured", "MusicReview": "not-reviewed", "GameReview": "not-tested",
        "RedistributionVerified": False,
    }


def _source_license_text(commit: str, info: dict[str, str]) -> str:
    return f"""MutopiaProject source attribution and rights boundary
====================================================
Repository: {MUTOPIA_REPOSITORY_URL}
Pinned commit: {commit}
MIDI endpoint: {MUTOPIA_BASE_URL}
Selected header license family: {info["label"]}
License reference: {info["url"]}

This intake preserves the license declared in each local LilyPond header. The
declaration is not silently upgraded to legal clearance for every derived file,
bundled redistribution, or modern adaptation. {"Attribution and ShareAlike obligations" if info["kind"] == "cc-by-sa" else "Attribution obligations" if info["kind"] == "cc-by" else "The public-domain declaration"} and the exact bundled-source scope remain candidate-unverified.
Each entry remains candidate-unverified until the exact source path, MIDI hash, work,
edition, and intended distribution scope are reviewed.

No music-review, game-review, or native-input claim is made by this intake.
"""


def _manifest_summary(exclusions: dict[str, set[str]]) -> dict[str, Any]:
    return {"uniqueSourceSha256": len(exclusions["sourceHashes"]), "uniqueEditionIds": len(exclusions["editionIds"])}


def acquire_batch(
    source_root: Path,
    output: Path,
    *,
    limit: int = 100,
    offset: int = 0,
    exclude_manifests: Iterable[Path | str] | Path | str | None = None,
    license_filter: str | None = None,
    avoid_titles: Iterable[str] = (),
    opener: Callable[..., Any] | None = None,
    now_fn: Callable[[], str] = utc_now,
    enforce_output_root: bool = True,
) -> dict[str, Any]:
    source_root = Path(source_root).resolve()
    output = Path(output).resolve()
    if limit <= 0 or offset < 0:
        raise IntakeError("limit must be positive and offset must be non-negative")
    if not source_root.is_dir():
        raise IntakeError(f"source root does not exist: {source_root}")
    if output.exists():
        raise IntakeError(f"refusing existing output: {output}")
    if enforce_output_root and not output.is_relative_to(DEFAULT_OUTPUT_ROOT.resolve()):
        raise IntakeError(f"output must be under catalog-intake: {output}")
    commit = "unknown"
    try:
        import subprocess
        commit = subprocess.check_output(["git", "-C", str(source_root), "rev-parse", "HEAD"], text=True, timeout=30, stderr=subprocess.DEVNULL).strip()
    except Exception:
        pass
    exclusions = _load_exclusions(exclude_manifests)
    resolved_license_filter = _resolve_license_filter(license_filter)
    candidates = _source_candidates(source_root, license_filter=resolved_license_filter)
    seen_editions: set[str] = set()
    ready: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for row in candidates:
        edition_id = _edition_id(commit, row["lyPath"])
        if edition_id in exclusions["editionIds"] or edition_id in seen_editions:
            rejected.append({"lyPath": row["lyPath"], "reason": "duplicate EditionId"})
            continue
        seen_editions.add(edition_id)
        try:
            item = _download_candidate(row, opener=opener)
        except Exception as exc:
            rejected.append({"lyPath": row["lyPath"], "reason": str(exc)})
            continue
        if item["sourceSha256"] in exclusions["sourceHashes"]:
            rejected.append({"lyPath": row["lyPath"], "reason": "duplicate SourceSha256"})
            continue
        if any(existing["sourceSha256"] == item["sourceSha256"] for existing in ready):
            rejected.append({"lyPath": row["lyPath"], "reason": "duplicate SourceSha256 within batch"})
            continue
        ready.append(item)
        if len(ready) >= offset + limit:
            break
    selected = ready[offset:offset + limit]
    if len(selected) != limit:
        raise IntakeError(f"only {len(selected)} candidates available after filtering; need {limit}")
    license_keys = {item["licenseKey"] for item in selected}
    if len(license_keys) != 1:
        raise IntakeError("selected batch contains mixed Mutopia header licenses; use --license to isolate one family")
    batch_license_key = next(iter(license_keys))
    batch_license_info = dict(_license_info(batch_license_key) or {})
    if not batch_license_info:
        raise IntakeError(f"missing license metadata for {batch_license_key}")
    retrieved_at = now_fn()
    # The caller may choose a new batch directory under the intake root.
    # Create only its parent chain; the output itself remains add-only and
    # is still refused above when it already exists.
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=False)
    for name in ("midi", "references", "source/ly", "metadata/records"):
        (output / name).mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    for raw in selected:
        item = _build_item(raw, output, commit, retrieved_at)
        item["sourceCommit"] = commit
        items.append(item)
    _disambiguate_duplicate_display_titles(items, avoid_titles=avoid_titles)
    for raw, item in zip(selected, items):
        _write_bytes_new(Path(item["midiPath"]), raw["data"])
        _write_json_new(Path(item["referencePath"]), item["reference"])
        _write_bytes_new(Path(item["lyPath"]), raw["lyAbsolute"].read_bytes())
        _write_json_new(Path(item["metadataPath"]), item["metadataDocument"])
    groups: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for item in items:
        groups[item["workId"]].append({"id": item["id"], "editionId": item["editionId"], "versionLabel": item["versionLabel"], "title": item["sourceTitle"], "artist": item["sourceComposer"]})
    manifest = {
        "Songs": [_contract_song(item) for item in items], "SourceCommit": commit,
        "SourceRecord": MUTOPIA_REPOSITORY_URL, "RetrievedAtUtc": retrieved_at,
        "Provider": "MutopiaProject", "BatchKind": f"mutopia-{batch_license_info['tag']}-candidate-intake",
        "SourceUrl": MUTOPIA_BASE_URL, "License": batch_license_info["label"], "LicenseUrl": batch_license_info["url"],
        "RightsStatus": "candidate-unverified", "RightsNote": _rights_note(batch_license_info),
        "RedistributionVerified": False, "Author": "MutopiaProject / source typesetter", "Category": f"Mutopia - {batch_license_info['label']} candidate",
        "Description": f"Mutopia {batch_license_info['label']} header candidates with independent SMF timing evidence; review pending",
        "IdPattern": "mutopiaproject-<stable-path-hash>", "SmartInterludesDefault": True,
    }
    _write_json_new(output / "manifest.json", manifest)
    _write_json_new(output / "build-manifest.json", manifest)
    _write_json_new(output / "version-groups.json", {"policy": "WorkId groups source works; EditionId and VersionLabel distinguish source editions.", "groups": dict(sorted(groups.items()))})
    _write_text_new(output / "source-LICENSE.txt", _source_license_text(commit, batch_license_info))
    report = {
        "status": f"PASS_MUTOPIA_{batch_license_info['tag'].upper().replace('-', '_')}_METADATA_FIRST_BATCH", "provider": "MutopiaProject",
        "license": batch_license_info["label"], "licenseUrl": batch_license_info["url"],
        "sourceCommit": commit, "selectedCount": len(items), "distinctWorkIds": len({x["workId"] for x in items}),
        "sourceHashes": len({x["sourceSha256"] for x in items}), "selectionOffset": offset,
        "candidateCount": len(candidates), "rejectedCount": len(rejected), "rejected": rejected,
        "existingIntake": _manifest_summary(exclusions), "smartInterludesDefault": True,
        "rightsStatus": "candidate-unverified", "musicReview": "not-reviewed", "gameReview": "not-tested",
        "redistributionVerified": False, "selected": [{"id": x["id"], "title": x["sourceTitle"], "artist": x["sourceComposer"], "workId": x["workId"], "editionId": x["editionId"], "versionLabel": x["versionLabel"], "sourceSha256": x["sourceSha256"], "sourceLySha256": x["sourceLySha256"]} for x in items],
        "limitations": [f"Only source headers declaring {batch_license_info['label']} were selected.", "Source declaration is not treated as automatic redistribution clearance; attribution/share-alike obligations remain to be reviewed.", "SMF parsing is structural timing evidence only; no audio, music, game, or native-input validation was performed."],
    }
    _write_json_new(output / "acquisition-report.json", report)
    _write_text_new(output / "README.md", f"# MutopiaProject candidate intake ({len(items)} entries)\n\nSource commit: `{commit}`\n\nSelected: `{len(items)}`; WorkId count: `{report['distinctWorkIds']}`.\n\nAll entries remain `candidate-unverified`, `musicReview=not-reviewed`, `gameReview=not-tested`, and `RedistributionVerified=false`.\n")
    return {"manifest": manifest, "report": report}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--exclude-manifest", action="append", default=[])
    parser.add_argument("--license", dest="license_filter", default=None, help="limit to one exact source-header license family (for example: CC BY-SA 4.0)")
    parser.add_argument("--avoid-title", action="append", default=[], help="decorate an incoming title to avoid a title collision with an existing work")
    args = parser.parse_args(argv)
    try:
        result = acquire_batch(args.source_root, args.output, limit=args.limit, offset=args.offset, exclude_manifests=args.exclude_manifest, license_filter=args.license_filter, avoid_titles=args.avoid_title)
    except (IntakeError, OSError, ValueError) as exc:
        print(f"FAIL Mutopia intake: {exc}")
        return 2
    print(f"PASS Mutopia intake: selected={result['report']['selectedCount']} output={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Deterministic OpenScore Lieder intake for QinBan.

The module reads a pinned local OpenScore Lieder Git tree, converts selected
MusicXML files with the MuseScore 4 batch job interface, independently parses
every produced SMF, and writes a new catalog-intake directory only after the
complete batch passes. It never touches product Songs, an EXE, UserData, a game
process, native input, the network, or privileges.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
from typing import Any, Callable, Iterable, Mapping, Sequence
import unicodedata
import xml.etree.ElementTree as ET
import zipfile

try:
    from smf_reference import parse_smf
except ModuleNotFoundError:
    from tools.smf_reference import parse_smf

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_ROOT = ROOT.parent / ".tools" / "sources" / "openscore-lieder-2026-10-06"
DEFAULT_OUTPUT_ROOT = ROOT / "catalog-intake"
OPEN_SCORE_REPOSITORY = "https://github.com/OpenScore/Lieder"
OPEN_SCORE_MUSESCORE_COLLECTION = "https://musescore.com/openscore-lieder-corpus"
OPEN_SCORE_LICENSE = "CC0 1.0 Universal"
OPEN_SCORE_LICENSE_URL = "https://creativecommons.org/publicdomain/zero/1.0/"
PROVIDER = "OpenScoreLieder"
MAX_MIDI_BYTES = 16 * 1024 * 1024
MIN_DURATION_MS = 1_000.0
MAX_DURATION_MS = 1_800_000.0
MAX_NOTES = 100_000
MIN_BPM = 20.0
MAX_BPM = 400.0
CORE_TITLE_LIMIT = 180
SOURCE_HASH_RE = re.compile(r"^[0-9A-Fa-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9A-Fa-f]{40}$")
SCORE_ID_RE = re.compile(r"^lc(?P<id>[0-9]+)$", re.IGNORECASE)
LANGUAGE_MAP = {
    "EN": "en", "DE": "de", "FR": "fr", "PT": "pt", "IT": "it",
    "ES": "es", "SV": "sv", "PL": "pl", "HAW": "haw", "RU": "ru",
    "UK": "uk", "CS": "cs", "SK": "sk", "NL": "nl", "DA": "da",
    "NO": "no", "FI": "fi", "HU": "hu", "EL": "el", "AR": "ar",
    "HE": "he", "JA": "ja", "KO": "ko", "ZH": "zh",
}


class IntakeError(RuntimeError):
    """A fail-closed intake error with structured per-item failures."""

    def __init__(self, message: str, *, failures: Iterable[Mapping[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.failures = [dict(item) for item in (failures or [])]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


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


def _read_bytes(path: Path, open_fn: Callable[..., Any]) -> bytes:
    try:
        with open_fn(path, "rb") as stream:
            data = stream.read()
    except Exception as exc:
        raise IntakeError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, bytes):
        raise IntakeError(f"reader returned non-bytes for {path}")
    return data


def _raw(value: Any) -> str:
    return "" if value is None else str(value)


def _bounded_title(value: Any) -> tuple[str, bool]:
    text = _raw(value).strip()
    if len(text) <= CORE_TITLE_LIMIT:
        return text, False
    suffix = "..."
    return text[: CORE_TITLE_LIMIT - len(suffix)].rstrip() + suffix, True


def _slug(value: Any, fallback: str = "unknown") -> str:
    text = unicodedata.normalize("NFKD", _raw(value).strip())
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:96] or fallback


def _casefold_key(value: Any) -> str:
    return _raw(value).strip().casefold()


def _manifest_value(record: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in record:
            return record[name]
    folded = {_casefold_key(key): value for key, value in record.items()}
    for name in names:
        if _casefold_key(name) in folded:
            return folded[_casefold_key(name)]
    return default


def _no_reparse(path: Path) -> None:
    """Reject symlinks/junctions in a path this tool may write through."""
    current = Path(os.path.abspath(path))
    while True:
        try:
            info = current.lstat()
        except FileNotFoundError:
            pass
        else:
            attrs = getattr(info, "st_file_attributes", 0)
            reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            if stat.S_ISLNK(info.st_mode) or bool(attrs & reparse):
                raise IntakeError(f"symlink/reparse point refused: {current}")
        parent = current.parent
        if parent == current:
            break
        current = parent


def _validate_output_path(output: Path, catalog_root: Path) -> tuple[Path, Path]:
    root = Path(os.path.abspath(catalog_root))
    if not root.is_dir():
        raise IntakeError(f"catalog-intake root does not exist: {root}")
    _no_reparse(root)
    target = Path(os.path.abspath(output))
    if target == root or not target.is_relative_to(root):
        raise IntakeError(f"output must be a new directory below catalog-intake: {target}")
    if target.exists():
        raise IntakeError(f"output already exists; refusing overwrite: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    _no_reparse(target.parent)
    if target.exists():
        raise IntakeError(f"output appeared during preflight; refusing overwrite: {target}")
    return root, target


def _load_exclusions(paths: Iterable[Path | str] | Path | str | None) -> dict[str, set[str]]:
    source_hashes: set[str] = set()
    edition_ids: set[str] = set()
    mxl_hashes: set[str] = set()
    mscz_hashes: set[str] = set()
    if paths is None:
        return {"sourceHashes": source_hashes, "editionIds": edition_ids, "mxlHashes": mxl_hashes, "msczHashes": mscz_hashes}
    raw_paths = [paths] if isinstance(paths, (Path, str)) else list(paths)
    for raw in raw_paths:
        path = Path(raw).expanduser().absolute()
        if path.is_dir():
            path = path / "manifest.json"
        if not path.is_file():
            raise IntakeError(f"exclude manifest does not exist: {path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise IntakeError(f"invalid exclude manifest: {path}: {exc}") from exc
        songs = payload.get("Songs") if isinstance(payload, dict) else None
        if not isinstance(songs, list) and isinstance(payload, dict):
            songs = payload.get("songs")
        if not isinstance(songs, list):
            raise IntakeError(f"exclude manifest has no Songs list: {path}")
        for index, song in enumerate(songs, start=1):
            if not isinstance(song, dict):
                raise IntakeError(f"exclude manifest Songs[{index}] is not an object: {path}")
            provenance = song.get("provenance") if isinstance(song.get("provenance"), dict) else {}
            merged = dict(provenance)
            merged.update(song)
            source = _raw(_manifest_value(merged, "SourceSha256", "sourceSha256")).strip().upper()
            edition = _raw(_manifest_value(merged, "EditionId", "editionId")).strip()
            mxl = _raw(_manifest_value(merged, "MxlSha256", "mxlSha256", "SourceMxlSha256", "sourceMxlSha256")).strip().upper()
            mscz = _raw(_manifest_value(merged, "MsczSha256", "msczSha256", "SourceMsczSha256", "sourceMsczSha256")).strip().upper()
            if source and SOURCE_HASH_RE.fullmatch(source):
                source_hashes.add(source)
            if edition:
                edition_ids.add(edition)
            if mxl and SOURCE_HASH_RE.fullmatch(mxl):
                mxl_hashes.add(mxl)
            if mscz and SOURCE_HASH_RE.fullmatch(mscz):
                mscz_hashes.add(mscz)
    return {"sourceHashes": source_hashes, "editionIds": edition_ids, "mxlHashes": mxl_hashes, "msczHashes": mscz_hashes}
def _yaml_scalar(value: str) -> Any:
    text = value.strip()
    if not text:
        return ""
    if text in {"null", "Null", "NULL", "~"}:
        return None
    if text.lower() in {"true", "false"}:
        return text.lower() == "true"
    if re.fullmatch(r"[-+]?\d+", text):
        try:
            return int(text)
        except ValueError:
            pass
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1].replace('\\"', '"')
    return text


def _fallback_yaml_mapping(text: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if raw_line[0].isspace():
            if current is None or ":" not in raw_line:
                raise IntakeError("unsupported scores.yaml indentation")
            key, value = raw_line.strip().split(":", 1)
            current[key.strip()] = _yaml_scalar(value)
            continue
        if not raw_line.rstrip().endswith(":"):
            raise IntakeError("unsupported scores.yaml top-level shape")
        key = raw_line.rstrip()[:-1].strip()
        current = {}
        result[key] = current
    return result


def _parse_scores_yaml(text: str) -> dict[str, dict[str, Any]]:
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError:
        return _fallback_yaml_mapping(text)
    try:
        payload = yaml.safe_load(text)
    except Exception as exc:
        raise IntakeError(f"scores.yaml parse failed: {exc}") from exc
    if not isinstance(payload, dict):
        raise IntakeError("scores.yaml must contain a mapping")
    result: dict[str, dict[str, Any]] = {}
    for key, value in payload.items():
        if not isinstance(value, dict):
            raise IntakeError(f"scores.yaml record {key!r} is not an object")
        result[str(key)] = {str(k): v for k, v in value.items()}
    return result


def _parse_tabular_metadata(text: str, *, delimiter: str | None = None) -> dict[str, dict[str, Any]]:
    """Parse a small CSV/TSV score index for offline mirrors and fixtures."""
    lines = text.splitlines()
    if delimiter is None:
        delimiter = "\t" if lines and "\t" in lines[0] else ","
    rows = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not rows.fieldnames:
        raise IntakeError("tabular score metadata has no header")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        clean = {str(key).strip(): (value or "").strip() for key, value in row.items() if key is not None}
        score_id = _raw(_manifest_value(clean, "id", "score_id", "scoreId", "score")).strip()
        if not score_id:
            raise IntakeError("tabular score metadata row has no score id")
        result[score_id] = clean
    return result


def _load_score_index(source_root: Path, open_fn: Callable[..., Any]) -> tuple[dict[str, dict[str, Any]], Path, str]:
    data_root = source_root / "data"
    yaml_path = data_root / "scores.yaml"
    if yaml_path.is_file():
        raw = _read_bytes(yaml_path, open_fn)
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise IntakeError(f"scores.yaml is not UTF-8: {yaml_path}") from exc
        return _parse_scores_yaml(text), yaml_path, sha256_bytes(raw)
    for name in ("scores.tsv", "scores.csv"):
        candidate = data_root / name
        if candidate.is_file():
            raw = _read_bytes(candidate, open_fn)
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise IntakeError(f"score metadata is not UTF-8: {candidate}") from exc
            return _parse_tabular_metadata(text), candidate, sha256_bytes(raw)
    raise IntakeError(f"missing data/scores.yaml (or scores.csv/scores.tsv) below {source_root}")


def _git_rev(source_root: Path, expression: str, runner: Callable[..., Any] | None = None) -> str:
    run = runner or subprocess.run
    try:
        result = run(
            ["git", "-C", str(source_root), "rev-parse", expression],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except Exception as exc:
        raise IntakeError(f"cannot read local Git {expression}: {exc}") from exc
    value = _raw(getattr(result, "stdout", "")).strip()
    if not value:
        raise IntakeError(f"local Git returned empty value for {expression}")
    return value


def _source_commit_and_tree(source_root: Path, source_commit: str | None, git_runner: Callable[..., Any] | None) -> tuple[str, str]:
    commit = source_commit.strip() if source_commit else _git_rev(source_root, "HEAD", git_runner)
    if not COMMIT_RE.fullmatch(commit):
        raise IntakeError(f"source commit is not a 40-hex Git hash: {commit!r}")
    tree = _git_rev(source_root, "HEAD^{tree}", git_runner) if source_commit is None else ""
    if tree and not COMMIT_RE.fullmatch(tree):
        raise IntakeError(f"source tree hash is not a 40-hex Git hash: {tree!r}")
    return commit.lower(), tree.lower()


def _local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _element_text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return "".join(element.itertext()).strip()


def _first_text(root: ET.Element, tag_name: str) -> str:
    for element in root.iter():
        if _local_tag(element.tag) == tag_name and _element_text(element):
            return _element_text(element)
    return ""


def _parse_musicxml(data: bytes) -> dict[str, Any]:
    if b"<!ENTITY" in data.upper():
        raise IntakeError("MusicXML entity declarations are refused")
    try:
        root = ET.fromstring(data)
    except (ET.ParseError, ValueError) as exc:
        raise IntakeError(f"MusicXML parse failed: {exc}") from exc
    title = ""
    for tag_name in ("work-title", "movement-title"):
        title = _first_text(root, tag_name)
        if title:
            break
    if not title:
        for credit in root.iter():
            if _local_tag(credit.tag) != "credit":
                continue
            kind, words = "", ""
            for child in credit.iter():
                if _local_tag(child.tag) == "credit-type":
                    kind = _element_text(child).casefold()
                elif _local_tag(child.tag) == "credit-words":
                    words = _element_text(child)
            if kind == "title" and words:
                title = words
                break
    composer = ""
    for element in root.iter():
        if _local_tag(element.tag) == "creator" and _casefold_key(element.attrib.get("type")) == "composer":
            composer = _element_text(element)
            if composer:
                break
    if not composer:
        for credit in root.iter():
            if _local_tag(credit.tag) != "credit":
                continue
            kind, words = "", ""
            for child in credit.iter():
                if _local_tag(child.tag) == "credit-type":
                    kind = _element_text(child).casefold()
                elif _local_tag(child.tag) == "credit-words":
                    words = _element_text(child)
            if kind == "composer" and words:
                composer = words
                break
    source = _first_text(root, "source")
    rights = _first_text(root, "rights")
    xml_languages: list[str] = []
    lyrics: list[str] = []
    for element in root.iter():
        local = _local_tag(element.tag)
        if local in {"language", "lang"} and _element_text(element):
            xml_languages.append(_element_text(element))
        if local == "miscellaneous-field" and _casefold_key(element.attrib.get("name")) in {"language", "lang"}:
            if _element_text(element):
                xml_languages.append(_element_text(element))
        if local == "lyric":
            values = [_element_text(child) for child in element.iter() if _local_tag(child.tag) == "text" and _element_text(child)]
            if values:
                lyrics.append(" ".join(values))
    return {
        "title": title.strip(),
        "composer": composer.strip(),
        "source": source.strip(),
        "rights": rights.strip(),
        "xmlLanguages": xml_languages,
        "lyrics": lyrics,
        "lyricCount": len(lyrics),
    }


def _musicxml_payload(mxl_data: bytes) -> bytes:
    try:
        with zipfile.ZipFile(io.BytesIO(mxl_data)) as archive:
            names = set(archive.namelist())
            rootfile = ""
            if "META-INF/container.xml" in names:
                container = ET.fromstring(archive.read("META-INF/container.xml"))
                for element in container.iter():
                    if _local_tag(element.tag) == "rootfile":
                        rootfile = _raw(element.attrib.get("full-path")).replace("\\", "/")
                        if rootfile:
                            break
            if not rootfile:
                rootfile = "score.xml" if "score.xml" in names else next(
                    (name for name in names if name.lower().endswith((".xml", ".musicxml")) and not name.startswith("META-INF/")),
                    "",
                )
            if not rootfile or rootfile.startswith("/") or ".." in Path(rootfile).parts or rootfile not in names:
                raise IntakeError("MXL has no safe MusicXML rootfile")
            return archive.read(rootfile)
    except IntakeError:
        raise
    except (OSError, zipfile.BadZipFile, ET.ParseError, KeyError) as exc:
        raise IntakeError(f"MXL container parse failed: {exc}") from exc


def _normalise_url(value: str, score_id: str) -> tuple[str, str]:
    raw = " ".join(value.split())
    matches = re.findall(r"https?://[^\s<>\"']+", raw)
    source = matches[-1].rstrip(".,;)'\"]") if matches else ""
    official = f"{OPEN_SCORE_MUSESCORE_COLLECTION}/scores/{score_id}"
    if not re.fullmatch(r"https?://[^\s<>\"']+", source or ""):
        source = official
    return source, official


def _normalise_language_values(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = _raw(value).strip()
        if not text:
            continue
        for token in re.split(r"[\s,;/|]+", text):
            token = token.strip().upper()
            if not token or token in {"UNKNOWN", "UNSPECIFIED", "N/A", "NA", "NONE"}:
                continue
            normalized = LANGUAGE_MAP.get(token)
            if normalized is None and re.fullmatch(r"[A-Z]{2,3}", token):
                normalized = token.lower()
            if normalized and normalized not in result:
                result.append(normalized)
    return result


def _script_language(lyrics: Iterable[str]) -> str:
    text = " ".join(lyrics)
    if not text:
        return ""
    if re.search(r"[\u3040-\u30ff]", text):
        return "ja"
    if re.search(r"[\uac00-\ud7af]", text):
        return "ko"
    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"
    if re.search(r"[\u0400-\u052f]", text):
        return "ru"
    if re.search(r"[\u0600-\u06ff]", text):
        return "ar"
    if re.search(r"[\u0370-\u03ff]", text):
        return "el"
    if re.search(r"[\u0900-\u097f]", text):
        return "hi"
    return ""


def _language_tags(xml: Mapping[str, Any], row: Mapping[str, Any]) -> tuple[list[str], str]:
    xml_values = _normalise_language_values(xml.get("xmlLanguages", []))
    if xml_values:
        return xml_values, "musicxml-explicit"
    row_values = _normalise_language_values([_manifest_value(row, "language", "Language")])
    if row_values:
        return row_values, "scores-metadata-explicit"
    inferred = _script_language(xml.get("lyrics", []))
    return ([inferred] if inferred else []), ("lyrics-script-conservative" if inferred else "unknown")
def _score_id_from_path(path: Path) -> str:
    match = SCORE_ID_RE.fullmatch(path.stem)
    if not match:
        raise IntakeError(f"score filename must be lc<digits>.mxl: {path}")
    return match.group("id")


def _scan_candidates(source_root: Path, score_index: Mapping[str, Mapping[str, Any]], open_fn: Callable[..., Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    scores_root = source_root / "scores"
    if not scores_root.is_dir():
        raise IntakeError(f"missing scores directory: {scores_root}")
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen_mxl: set[str] = set()
    seen_mscz: set[str] = set()
    for mxl_path in sorted(scores_root.rglob("*.mxl"), key=lambda item: item.relative_to(source_root).as_posix().casefold()):
        relative = mxl_path.relative_to(source_root).as_posix()
        score_id = ""
        try:
            score_id = _score_id_from_path(mxl_path)
            mscz_path = mxl_path.with_suffix(".mscz")
            if not mscz_path.is_file():
                raise IntakeError("matching .mscz is missing")
            row = score_index.get(score_id)
            if row is None:
                raise IntakeError("score id is absent from data/scores.yaml")
            expected_path = mxl_path.parent.relative_to(scores_root).as_posix()
            metadata_path = _raw(_manifest_value(row, "path", "Path")).replace("\\", "/").strip("/")
            if metadata_path != expected_path:
                raise IntakeError(f"scores metadata path mismatch: {metadata_path!r} != {expected_path!r}")
            mxl_data = _read_bytes(mxl_path, open_fn)
            mscz_data = _read_bytes(mscz_path, open_fn)
            mxl_hash = sha256_bytes(mxl_data)
            mscz_hash = sha256_bytes(mscz_data)
            if mxl_hash in seen_mxl or mscz_hash in seen_mscz:
                raise IntakeError("duplicate raw MXL/MSCZ hash in source tree")
            seen_mxl.add(mxl_hash)
            seen_mscz.add(mscz_hash)
            candidates.append({
                "scoreId": score_id,
                "mxlPath": mxl_path,
                "msczPath": mscz_path,
                "mxlRelativePath": relative,
                "msczRelativePath": mscz_path.relative_to(source_root).as_posix(),
                "mxlSha256": mxl_hash,
                "msczSha256": mscz_hash,
                "row": dict(row),
            })
        except Exception as exc:
            rejected.append({"scoreId": score_id, "sourcePath": relative, "stage": "source-scan", "error": str(exc)})
    candidates.sort(key=lambda item: (int(item["scoreId"]), item["mxlRelativePath"].casefold()))
    return candidates, rejected


def _work_id(title: str, composer: str) -> str:
    return f"openscore-work:{_slug(title, 'untitled')}::{_slug(composer, 'unknown-composer')}"


def _edition_id(score_id: str, mxl_sha256: str) -> str:
    return f"openscore-lieder:{score_id}:{mxl_sha256[:16].lower()}"


def _version_label(candidate: Mapping[str, Any], xml: Mapping[str, Any]) -> str:
    row = candidate["row"]
    set_id = _raw(_manifest_value(row, "set_id", "setId")).strip()
    title = _raw(xml.get("title")).strip()
    label = f"OpenScore score {candidate['scoreId']} / {title} / {candidate['mxlRelativePath']}"
    if set_id:
        label += f" / set {set_id}"
    return label if len(label) <= 256 else label[:253].rstrip() + "..."


def _build_identity(candidate: dict[str, Any], source_commit: str, source_tree_hash: str, source_metadata_sha256: str, open_fn: Callable[..., Any]) -> dict[str, Any]:
    mxl_data = _read_bytes(candidate["mxlPath"], open_fn)
    mscz_data = _read_bytes(candidate["msczPath"], open_fn)
    if sha256_bytes(mxl_data) != candidate["mxlSha256"] or sha256_bytes(mscz_data) != candidate["msczSha256"]:
        raise IntakeError("source changed after scan; raw hash no longer matches")
    xml = _parse_musicxml(_musicxml_payload(mxl_data))
    title = _raw(xml.get("title")).strip()
    composer = _raw(xml.get("composer")).strip()
    if not title:
        raise IntakeError("MusicXML has no title")
    if not composer:
        raise IntakeError("MusicXML has no composer")
    source_url, official_url = _normalise_url(_raw(xml.get("source")), candidate["scoreId"])
    languages, language_source = _language_tags(xml, candidate["row"])
    title_display, truncated = _bounded_title(title)
    work_id = _work_id(title, composer)
    edition_id = _edition_id(candidate["scoreId"], candidate["mxlSha256"])
    version_label = _version_label(candidate, xml)
    stem = f"openscore-lieder-{candidate['scoreId']}"
    row = candidate["row"]
    instruments = _raw(_manifest_value(row, "instruments", "Instruments")).strip()
    item = dict(candidate)
    item.update({
        "id": stem,
        "sourceTitle": title,
        "title": title_display,
        "titleWasTruncated": truncated,
        "sourceComposer": composer,
        "sourceUrl": source_url,
        "officialSourceUrl": official_url,
        "workId": work_id,
        "editionId": edition_id,
        "versionLabel": version_label,
        "languages": languages,
        "languageSource": language_source,
        "instruments": instruments,
        "sourceCommit": source_commit,
        "sourceTreeHash": source_tree_hash,
        "sourceMetadataSha256": source_metadata_sha256,
        "xml": xml,
        "mxlData": mxl_data,
        "msczData": mscz_data,
    })
    return item


def _disambiguate_duplicate_titles(items: list[dict[str, Any]]) -> None:
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        groups.setdefault(_casefold_key(item["sourceTitle"]), []).append(item)
    for group in groups.values():
        if len(group) <= 1:
            continue
        for item in group:
            decorated, _ = _bounded_title(f"{item['sourceTitle']} (OpenScore score {item['scoreId']})")
            item["title"] = decorated


def _resolve_executable(value: str | Path, *, strict: bool) -> str:
    raw = _raw(value).strip()
    if not raw:
        raise IntakeError("--musescore-exe cannot be empty")
    path = Path(raw)
    if path.is_file():
        return str(path.absolute())
    found = shutil.which(raw)
    if found:
        return str(Path(found).absolute())
    if strict:
        raise IntakeError(f"MuseScore executable not found: {raw}")
    return raw


def _result_summary(result: Any) -> dict[str, Any]:
    return {
        "returncode": getattr(result, "returncode", None),
        "stdout": _raw(getattr(result, "stdout", ""))[-4000:],
        "stderr": _raw(getattr(result, "stderr", ""))[-4000:],
    }


def _validate_midi(data: bytes, label: str) -> dict[str, Any]:
    if len(data) > MAX_MIDI_BYTES:
        raise IntakeError(f"{label}: MIDI exceeds size budget")
    try:
        reference = parse_smf(data)
    except Exception as exc:
        raise IntakeError(f"{label}: independent SMF parser rejected MIDI: {exc}") from exc
    notes = reference.get("notes")
    length = float(reference.get("lengthMs", 0.0))
    bpm = float(reference.get("bpm", 0.0))
    if not isinstance(notes, list) or not notes:
        raise IntakeError(f"{label}: MIDI has no notes")
    if len(notes) > MAX_NOTES:
        raise IntakeError(f"{label}: note count exceeds budget")
    if not math.isfinite(length) or length < MIN_DURATION_MS or length > MAX_DURATION_MS:
        raise IntakeError(f"{label}: duration outside QinBan budget: {length}")
    if not math.isfinite(bpm) or bpm < MIN_BPM or bpm > MAX_BPM:
        raise IntakeError(f"{label}: BPM outside QinBan budget: {bpm}")
    return reference


def _run_musescore_job(executable: str, jobs: list[dict[str, str]], job_path: Path, *, process_runner: Callable[..., Any] | None) -> dict[str, Any]:
    command = [executable, "--test-mode", "-F", "-j", str(job_path)]
    runner = process_runner or subprocess.run
    try:
        result = runner(
            command,
            cwd=str(job_path.parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=60 * 60,
        )
    except Exception as exc:
        return {"processError": repr(exc), "command": command}
    summary = _result_summary(result)
    summary["command"] = command
    return summary


def _invoke_converter(selected: list[dict[str, Any]], temp_root: Path, *, executable: str | None, converter: Callable[[str | None, list[dict[str, str]], Path], Any] | None, process_runner: Callable[..., Any] | None) -> tuple[dict[str, Path], dict[str, Any]]:
    midi_root = temp_root / "midi"
    midi_root.mkdir(parents=True, exist_ok=True)
    jobs: list[dict[str, str]] = []
    output_paths: dict[str, Path] = {}
    for item in selected:
        output = midi_root / f"{item['id']}.mid"
        output_paths[item["id"]] = output
        jobs.append({"in": str(item["mxlPath"].absolute()), "out": str(output.absolute())})
    job_path = temp_root / "musescore-job.json"
    _write_json_new(job_path, jobs)
    if converter is not None:
        try:
            converter(executable, jobs, job_path)
            process = {"converter": "injected", "returncode": 0, "command": []}
        except Exception as exc:
            process = {"converter": "injected", "processError": repr(exc), "returncode": None, "command": []}
    else:
        if executable is None:
            raise IntakeError("no converter or MuseScore executable was supplied")
        process = _run_musescore_job(executable, jobs, job_path, process_runner=process_runner)
    process["jobPath"] = str(job_path)
    process["jobCount"] = len(jobs)
    return output_paths, process
def _contract_song(item: Mapping[str, Any], reference_path: Path, midi_path: Path) -> dict[str, Any]:
    row = item["row"]
    tags = ["OpenScore Lieder"]
    if item.get("instruments"):
        tags.append(_raw(item["instruments"]))
    tags.extend(item.get("languages", []))
    return {
        "Id": item["id"],
        "Title": item["title"],
        "Artist": item["sourceComposer"],
        "MidiPath": str(midi_path.absolute()),
        "ReferencePath": str(reference_path.absolute()),
        "SourceUrl": item["sourceUrl"],
        "SourceSha256": item["midiSha256"],
        "LanguageTags": list(item.get("languages", [])),
        "Artists": [item["sourceComposer"]],
        "Provider": PROVIDER,
        "SourceCommit": item["sourceCommit"],
        "SourceRecord": OPEN_SCORE_REPOSITORY,
        "BatchKind": "openscore-lieder-cc0-candidate-intake",
        "Author": "OpenScore Lieder contributors",
        "Category": "OpenScore Lieder - CC0 candidate",
        "Description": "OpenScore Lieder MusicXML converted by MuseScore and independently SMF-validated; review pending",
        "IdPattern": "openscore-lieder-<musescore-id>",
        "SmartInterludes": True,
        "WorkId": item["workId"],
        "EditionId": item["editionId"],
        "VersionLabel": item["versionLabel"],
        "License": OPEN_SCORE_LICENSE,
        "LicenseUrl": OPEN_SCORE_LICENSE_URL,
        "RightsStatus": "candidate-unverified",
        "RightsNote": "The source repository declares CC0; exact bundled-source and redistribution scope remains candidate-unverified.",
        "Album": _raw(_manifest_value(row, "set_id", "setId")),
        "Aliases": [],
        "Tags": tags,
        "Completeness": "source-mxl-mscz-midi-validated",
        "MusicReview": "not-reviewed",
        "GameReview": "not-tested",
        "RedistributionVerified": False,
    }


def _metadata_record(item: Mapping[str, Any], reference: Mapping[str, Any]) -> dict[str, Any]:
    xml = item["xml"]
    return {
        "schemaVersion": "openscore-lieder-intake-v1",
        "id": item["id"],
        "provider": PROVIDER,
        "source": {
            "repository": OPEN_SCORE_REPOSITORY,
            "collection": OPEN_SCORE_MUSESCORE_COLLECTION,
            "commit": item["sourceCommit"],
            "treeHash": item["sourceTreeHash"],
            "scoreId": item["scoreId"],
            "scoreUrl": item["officialSourceUrl"],
            "sourceUrl": item["sourceUrl"],
            "mxlPath": item["mxlRelativePath"],
            "msczPath": item["msczRelativePath"],
            "metadataPath": "data/scores.yaml",
            "metadataSha256": item["sourceMetadataSha256"],
            "metadataRecord": item["row"],
            "rawFiles": {
                "mxl": {"path": f"./source/mxl/{item['id']}.mxl", "sha256": item["mxlSha256"]},
                "mscz": {"path": f"./source/mscz/{item['id']}.mscz", "sha256": item["msczSha256"]},
            },
        },
        "musicXml": {
            "title": item["sourceTitle"],
            "composer": item["sourceComposer"],
            "sourceField": xml.get("source", ""),
            "rightsField": xml.get("rights", ""),
            "lyricCount": xml.get("lyricCount", 0),
            "languageSignals": xml.get("xmlLanguages", []),
        },
        "work": {"workId": item["workId"], "title": item["sourceTitle"], "composer": item["sourceComposer"]},
        "edition": {
            "editionId": item["editionId"],
            "versionLabel": item["versionLabel"],
            "displayTitle": item["title"],
            "titleWasTruncated": item["titleWasTruncated"],
        },
        "language": {"tags": item.get("languages", []), "source": item.get("languageSource", "unknown")},
        "conversion": {
            "midiPath": f"./midi/{item['id']}.mid",
            "referencePath": f"./references/{item['id']}.json",
            "midiSha256": reference.get("sourceSha256", ""),
            "parser": reference.get("reference", "independent Python SMF parser; no transcription"),
            "lengthMs": reference.get("lengthMs"),
            "bpm": reference.get("bpm"),
            "notes": len(reference.get("notes", [])),
        },
        "rights": {"license": OPEN_SCORE_LICENSE, "licenseUrl": OPEN_SCORE_LICENSE_URL, "status": "candidate-unverified", "redistributionVerified": False},
        "review": {"music": "not-reviewed", "game": "not-tested"},
        "evidenceBoundary": "source bytes, metadata, MuseScore conversion result, and independent SMF timing only; no music review, audio playback, game test, or redistribution clearance",
    }


def _load_license(source_root: Path, open_fn: Callable[..., Any]) -> str:
    license_path = source_root / "LICENSE.txt"
    if license_path.is_file():
        try:
            return _read_bytes(license_path, open_fn).decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise IntakeError(f"source LICENSE.txt is not UTF-8: {license_path}") from exc
    return "OpenScore Lieder source repository declares CC0 1.0 Universal.\n"


def _cleanup(path: Path | None) -> None:
    if path is not None and path.exists():
        shutil.rmtree(path, ignore_errors=True)


def acquire_batch(
    source_root: Path,
    output: Path,
    *,
    limit: int = 100,
    offset: int = 0,
    exclude_manifests: Iterable[Path | str] | Path | str | None = None,
    allow_partial: bool = False,
    musescore_exe: str | Path | None = None,
    converter: Callable[[str | None, list[dict[str, str]], Path], Any] | None = None,
    open_fn: Callable[..., Any] = open,
    process_runner: Callable[..., Any] | None = None,
    git_runner: Callable[..., Any] | None = None,
    source_commit: str | None = None,
    now_fn: Callable[[], str] = utc_now,
    catalog_root: Path | None = None,
) -> dict[str, Any]:
    if not isinstance(limit, int) or limit <= 0:
        raise IntakeError(f"limit must be a positive integer: {limit!r}")
    if not isinstance(offset, int) or offset < 0:
        raise IntakeError(f"offset must be a non-negative integer: {offset!r}")
    _, target = _validate_output_path(Path(output), catalog_root or DEFAULT_OUTPUT_ROOT)
    source = Path(os.path.abspath(source_root))
    if not source.is_dir():
        raise IntakeError(f"source root does not exist: {source}")
    _no_reparse(source)
    if converter is None:
        if musescore_exe is None:
            raise IntakeError("MuseScore CLI is required; refusing to synthesize or invent MIDI", failures=[{"stage": "preflight", "error": "no musescore executable supplied"}])
        executable = _resolve_executable(musescore_exe, strict=process_runner is None)
    else:
        executable = _raw(musescore_exe) if musescore_exe is not None else None
    exclusions = _load_exclusions(exclude_manifests)
    index, metadata_path, metadata_sha256 = _load_score_index(source, open_fn)
    commit, tree_hash = _source_commit_and_tree(source, source_commit, git_runner)
    candidates, rejected = _scan_candidates(source, index, open_fn)
    eligible: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item in candidates:
        edition_id = _edition_id(item["scoreId"], item["mxlSha256"])
        if edition_id in exclusions["editionIds"] or item["mxlSha256"] in exclusions["mxlHashes"] or item["msczSha256"] in exclusions["msczHashes"]:
            skipped.append({"scoreId": item["scoreId"], "stage": "exclude", "editionId": edition_id})
            continue
        item["editionId"] = edition_id
        eligible.append(item)
    needed = offset + limit
    if len(eligible) < needed:
        raise IntakeError(
            "not enough eligible OpenScore Lieder scores",
            failures=[{"stage": "selection", "error": f"only {len(eligible)} eligible scores available; need offset+limit={needed}", "candidateCount": len(candidates), "rejectedCount": len(rejected)}],
        )
    selected_base = eligible[offset:needed]
    selected: list[dict[str, Any]] = []
    identity_failures: list[dict[str, Any]] = []
    for candidate in selected_base:
        try:
            selected.append(_build_identity(candidate, commit, tree_hash, metadata_sha256, open_fn))
        except Exception as exc:
            identity_failures.append({"id": f"openscore-lieder-{candidate['scoreId']}", "scoreId": candidate["scoreId"], "stage": "metadata", "error": str(exc)})
    if identity_failures:
        raise IntakeError("OpenScore metadata/XML validation failed; no output created", failures=identity_failures)
    _disambiguate_duplicate_titles(selected)
    temp_root: Path | None = None
    try:
        temp_root = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=str(target.parent)))
        for name in ("midi", "references", "source/mxl", "source/mscz", "metadata/records"):
            (temp_root / name).mkdir(parents=True, exist_ok=True)
        output_paths, process = _invoke_converter(selected, temp_root, executable=executable, converter=converter, process_runner=process_runner)
        failures: list[dict[str, Any]] = []
        process_failed = process.get("returncode") not in (None, 0) or bool(process.get("processError"))
        process_reason = (f"MuseScore batch exited with code {process.get('returncode')}" if process.get("returncode") not in (None, 0) else _raw(process.get("processError")) or "MuseScore batch runner failed")
        references: dict[str, dict[str, Any]] = {}
        midi_data: dict[str, bytes] = {}
        midi_hashes: dict[str, str] = {}
        for item in selected:
            midi_path = output_paths[item["id"]]
            # Strict mode preserves the original all-or-nothing contract. In
            # partial mode, a non-zero batch exit is only a warning: each
            # output must still exist and pass the independent SMF parser.
            if process_failed and not allow_partial:
                failures.append({"id": item["id"], "scoreId": item["scoreId"], "stage": "musescore-convert", "error": process_reason})
            if not midi_path.is_file():
                failures.append({"id": item["id"], "scoreId": item["scoreId"], "stage": "musescore-convert", "error": "expected .mid output is missing"})
                continue
            try:
                data = midi_path.read_bytes()
                reference = _validate_midi(data, item["id"])
                midi_data[item["id"]] = data
                midi_hashes[item["id"]] = sha256_bytes(data)
                references[item["id"]] = reference
            except Exception as exc:
                failures.append({"id": item["id"], "scoreId": item["scoreId"], "stage": "midi-parse", "error": str(exc)})
        accepted_ids = set(references)
        seen_midi: dict[str, str] = {}
        for item in selected:
            midi_hash = midi_hashes.get(item["id"])
            if not midi_hash:
                continue
            prior = seen_midi.get(midi_hash)
            if prior:
                failures.append({"id": item["id"], "scoreId": item["scoreId"], "stage": "duplicate", "error": f"MIDI SHA256 duplicates selected score {prior}: {midi_hash}"})
                accepted_ids.discard(item["id"])
            else:
                seen_midi[midi_hash] = item["id"]
            if midi_hash in exclusions["sourceHashes"]:
                failures.append({"id": item["id"], "scoreId": item["scoreId"], "stage": "duplicate", "error": f"MIDI SHA256 is present in exclude manifest: {midi_hash}"})
                accepted_ids.discard(item["id"])
        if failures and not allow_partial:
            raise IntakeError("OpenScore conversion/validation failed; no output created", failures=failures)
        accepted = [item for item in selected if item["id"] in accepted_ids]
        if not accepted:
            raise IntakeError("OpenScore conversion/validation produced no acceptable MIDI; no output created", failures=failures or [{"stage": "musescore-convert", "error": process_reason}])
        # Do not publish rejected/invalid MIDI files even though MuseScore may
        # have created them in the temporary conversion directory.
        for item in selected:
            if item["id"] not in accepted_ids:
                rejected_midi = output_paths[item["id"]]
                if rejected_midi.exists():
                    rejected_midi.unlink()
        stable_job = {
            "format": "MuseScore4 batch conversion evidence",
            "arguments": ["--test-mode", "-F", "-j", "<temporary-job.json>"],
            "jobs": [{"in": item["mxlRelativePath"], "out": f"./midi/{item['id']}.mid"} for item in selected],
        }
        _write_json_new(temp_root / "conversion-job.json", stable_job)
        temporary_job = temp_root / "musescore-job.json"
        if temporary_job.exists():
            temporary_job.unlink()
        process["jobPath"] = "conversion-job.json"
        if process.get("command"):
            process["command"] = [process["command"][0], "--test-mode", "-F", "-j", "<temporary-job.json>"]
        retrieved_at = now_fn()
        manifest_songs: list[dict[str, Any]] = []
        selected_report: list[dict[str, Any]] = []
        groups: dict[str, list[dict[str, Any]]] = {}
        for item in accepted:
            midi_path = temp_root / "midi" / f"{item['id']}.mid"
            reference_path = temp_root / "references" / f"{item['id']}.json"
            final_midi_path = target / "midi" / f"{item['id']}.mid"
            final_reference_path = target / "references" / f"{item['id']}.json"
            reference = dict(references[item["id"]])
            item["midiSha256"] = midi_hashes[item["id"]]
            reference.update({
                "schemaVersion": "openscore-lieder-independent-smf-reference-v1",
                "sourcePath": f"./midi/{item['id']}.mid",
                "sourceSha256": midi_hashes[item["id"]],
                "sourceMxlSha256": item["mxlSha256"],
                "sourceMsczSha256": item["msczSha256"],
                "provider": PROVIDER,
                "sourceCommit": commit,
                "workId": item["workId"],
                "editionId": item["editionId"],
                "versionLabel": item["versionLabel"],
                "sourceUrl": item["sourceUrl"],
                "parserScope": "independent Python SMF parser; no transcription, audio, or game validation",
            })
            _write_json_new(reference_path, reference)
            _write_bytes_new(temp_root / "source" / "mxl" / f"{item['id']}.mxl", item["mxlData"])
            _write_bytes_new(temp_root / "source" / "mscz" / f"{item['id']}.mscz", item["msczData"])
            _write_json_new(temp_root / "metadata" / "records" / f"{item['id']}.json", _metadata_record(item, reference))
            manifest_songs.append(_contract_song(item, final_reference_path, final_midi_path))
            groups.setdefault(item["workId"], []).append({
                "id": item["id"],
                "editionId": item["editionId"],
                "versionLabel": item["versionLabel"],
                "title": item["sourceTitle"],
                "displayTitle": item["title"],
                "artist": item["sourceComposer"],
            })
            selected_report.append({
                "id": item["id"],
                "scoreId": item["scoreId"],
                "title": item["sourceTitle"],
                "displayTitle": item["title"],
                "artist": item["sourceComposer"],
                "workId": item["workId"],
                "editionId": item["editionId"],
                "versionLabel": item["versionLabel"],
                "midiSha256": midi_hashes[item["id"]],
                "mxlSha256": item["mxlSha256"],
                "msczSha256": item["msczSha256"],
                "languageTags": item.get("languages", []),
            })
        source_license = _load_license(source, open_fn)
        _write_bytes_new(temp_root / "source" / "scores.yaml", _read_bytes(metadata_path, open_fn))
        _write_text_new(temp_root / "source-LICENSE.txt", source_license)
        _write_text_new(
            temp_root / "README.md",
            f"# OpenScore Lieder candidate intake ({len(manifest_songs)} entries)\n\n"
            f"Source commit: `{commit}`\n\n"
            f"Selected: `{len(manifest_songs)}`; WorkId count: `{len(groups)}`.\n\n"
            "The source repository declares CC0, but this intake keeps `RightsStatus=candidate-unverified` "
            "and `RedistributionVerified=false` until the exact redistribution scope is reviewed.\n\n"
            f"MuseScore conversion and independent SMF parsing passed for every accepted entry. "
            f"Requested candidates: {len(selected)}; accepted entries: {len(accepted)}; conversion rejections: {len(failures)}. "
            "Music review, audio review, game testing, and native-input testing were not performed.\n",
        )
        manifest = {
            "Songs": manifest_songs,
            "SourceCommit": commit,
            "SourceRecord": OPEN_SCORE_REPOSITORY,
            "RetrievedAtUtc": retrieved_at,
            "Provider": PROVIDER,
            "BatchKind": "openscore-lieder-cc0-candidate-intake",
            "SourceUrl": OPEN_SCORE_MUSESCORE_COLLECTION,
            "License": OPEN_SCORE_LICENSE,
            "LicenseUrl": OPEN_SCORE_LICENSE_URL,
            "RightsStatus": "candidate-unverified",
            "RightsNote": "Source repository declares CC0; exact bundled-source and redistribution scope remains candidate-unverified.",
            "RedistributionVerified": False,
            "Author": "OpenScore Lieder contributors",
            "Category": "OpenScore Lieder - CC0 candidate",
            "Description": "OpenScore Lieder MusicXML converted through MuseScore batch CLI and independently SMF-validated; review pending",
            "IdPattern": "openscore-lieder-<musescore-id>",
            "SmartInterludesDefault": True,
        }
        report = {
            "status": "PASS_OPENSCORE_LIEDER_PARTIAL_CANDIDATE_INTAKE" if (allow_partial and (failures or process_failed or len(accepted) < len(selected))) else "PASS_OPENSCORE_LIEDER_CANDIDATE_INTAKE",
            "provider": PROVIDER,
            "sourceRepository": OPEN_SCORE_REPOSITORY,
            "sourceCommit": commit,
            "sourceTreeHash": tree_hash,
            "sourceMetadataPath": metadata_path.relative_to(source).as_posix(),
            "sourceMetadataSha256": metadata_sha256,
            "selectedCount": len(manifest_songs),
            "requestedCount": len(selected),
            "acceptedCount": len(accepted),
            "selectionOffset": offset,
            "limit": limit,
            "candidateCount": len(candidates),
            "eligibleCount": len(eligible),
            "rejectedCount": len(rejected),
            "rejected": rejected,
            "conversionRejectedCount": len(failures),
            "conversionRejected": failures,
            "skippedByExclude": skipped,
            "selected": selected_report,
            "converter": process,
            "rightsStatus": "candidate-unverified",
            "musicReview": "not-reviewed",
            "gameReview": "not-tested",
            "redistributionVerified": False,
            "nativeInputAttempts": 0,
            "smartInterludesDefault": True,
            "evidenceBoundary": "source files, metadata, MuseScore conversion exit/output, and independent SMF timing only; no music review, game test, audio playback, or redistribution clearance",
        }
        _write_json_new(temp_root / "manifest.json", manifest)
        _write_json_new(temp_root / "build-manifest.json", manifest)
        _write_json_new(temp_root / "version-groups.json", {"policy": "WorkId groups source works; EditionId and VersionLabel distinguish score editions.", "groups": dict(sorted(groups.items()))})
        _write_json_new(temp_root / "acquisition-report.json", report)
        if target.exists():
            raise IntakeError(f"output appeared before commit; refusing overwrite: {target}")
        temp_root.rename(target)
        temp_root = None
        return {"manifest": manifest, "report": report}
    finally:
        _cleanup(temp_root)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="new directory below AutoMidiPlayer/catalog-intake")
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--exclude-manifest", action="append", default=[])
    parser.add_argument("--allow-partial", action="store_true", help="publish only individually validated MIDI outputs and record per-score conversion failures")
    parser.add_argument("--musescore-exe", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        result = acquire_batch(args.source_root, args.output, limit=args.limit, offset=args.offset, exclude_manifests=args.exclude_manifest, allow_partial=args.allow_partial, musescore_exe=args.musescore_exe)
    except IntakeError as exc:
        print(f"FAIL OpenScore Lieder intake: {exc}")
        if exc.failures:
            print(json.dumps({"failures": exc.failures}, ensure_ascii=False, indent=2))
        return 2
    except (OSError, ValueError) as exc:
        print(f"FAIL OpenScore Lieder intake: {exc}")
        return 2
    print(f"PASS OpenScore Lieder intake: selected={result['report']['selectedCount']} output={Path(args.output).absolute()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
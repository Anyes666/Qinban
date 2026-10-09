"""Read-only independent audit of a POP909 132 -> 332 staged catalogue.

A converter PASS is only a completion claim. Every MIDI is hashed and parsed
with smf_reference; both the supplied reference and normalized JSON are compared
independently. No network/audio/process/deployment/OS input is used. Only the
CLI's NEW report is written. Private _fixture mode labels disposable test data;
it never relaxes the 200/132/332 counts and is unavailable through the CLI.
"""
import argparse
from contextlib import closing
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import struct
import sys
import unicodedata
from urllib.parse import urlparse

# Import the existing read-only helper without writing bytecode caches.
sys.dont_write_bytecode = True
from smf_reference import parse_smf

ADDED_SONGS = 200
BASELINE_SONGS = 132
CATALOG_SONGS = BASELINE_SONGS + ADDED_SONGS
TIMING_TOLERANCE_MS = 0.0021
LICENSE_DECLARATION = "POP909 repository MIT; underlying song redistribution unverified"
REPO = Path(__file__).resolve().parents[1]
NOTE_FIELDS = {"pitch", "startMs", "durationMs", "track", "velocity", "percussion"}


class AuditError(ValueError):
    """Independently observed contract violation, not a converter claim."""


def require(value, reason):
    if not value:
        raise AuditError(reason)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def hash_value(value, label):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value),
            label + ": expected SHA256 hex")
    return value.upper()


def no_links(path):
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        require(not stat.S_ISLNK(info.st_mode)
                and not getattr(info, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400),
                "Symlink/reparse point refused: " + str(part))
    return path


def relative_key(value):
    require(isinstance(value, str) and value, "Empty resource path")
    value = value.replace("\\", "/")
    parts = value.split("/")
    require(not value.startswith("/") and all(p not in ("", ".", "..") for p in parts)
            and not any(":" in p or p.endswith((" ", ".")) for p in parts),
            "Unsafe resource path: " + value)
    return value


def resolve_resource(root, relative):
    relative = relative_key(relative)
    path = no_links(Path(root) / relative)
    require(path.resolve().is_relative_to(Path(root).resolve()), "Resource escapes root: " + relative)
    return path


def strict_json(text, label):
    def pairs(items):
        obj, seen = {}, set()
        for key, value in items:
            folded = key.casefold()
            require(folded not in seen, label + ": duplicate JSON property " + key)
            seen.add(folded)
            obj[key] = value
        return obj

    def constant(value):
        raise AuditError(label + ": non-finite JSON number " + value)

    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except json.JSONDecodeError as error:
        raise AuditError(label + ": invalid JSON: " + str(error)) from error


class Evidence:
    def __init__(self):
        self.hashes = {}

    def watch(self, path, payload=None):
        path = no_links(path)
        require(path.is_file(), "Missing file: " + str(path))
        digest = sha(path) if payload is None else hashlib.sha256(payload).hexdigest().upper()
        previous = self.hashes.setdefault(path, digest)
        require(previous == digest, "File changed during audit: " + str(path))
        return digest

    def read(self, path):
        path = no_links(path)
        payload = path.read_bytes()
        self.watch(path, payload)
        return payload

    def json(self, path):
        return strict_json(self.read(path).decode("utf-8-sig"), str(path))

    def unchanged(self):
        for path, expected in self.hashes.items():
            no_links(path)
            require(path.is_file() and sha(path) == expected, "File changed during audit: " + str(path))


def title_key(value):
    require(isinstance(value, str) and value.strip(), "Missing title")
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def integer(value, low, high, label):
    require(type(value) is int and low <= value <= high, label + ": invalid integer")
    return value


def number(value, label, low=0, high=1_800_000):
    require(type(value) in (int, float) and math.isfinite(value) and low <= value <= high,
            label + ": invalid finite number")
    return value


def same(actual, expected):
    """JSON equality without Python's True == 1 loophole."""
    if isinstance(expected, dict):
        return (isinstance(actual, dict) and actual.keys() == expected.keys()
                and all(same(actual[k], v) for k, v in expected.items()))
    if isinstance(expected, list):
        return (isinstance(actual, list) and len(actual) == len(expected)
                and all(same(a, b) for a, b in zip(actual, expected)))
    if type(expected) in (int, float):
        return type(actual) in (int, float) and actual == expected
    return type(actual) is type(expected) and actual == expected


def baseline_metadata(entry):
    result = copy.deepcopy(entry)
    require(isinstance(result.get("options"), dict), "Baseline options missing")
    # Core's new nullable field serializes as null; old raw JSON omits it.
    # Both inherit the same default. No other missing/unknown field is ignored.
    result["options"].setdefault("smartInterludes", None)
    return result


def notes(document, label):
    require(isinstance(document, dict) and isinstance(document.get("notes"), list)
            and 0 < len(document["notes"]) <= 100_000, label + ": invalid notes count")
    for i, note in enumerate(document["notes"]):
        where = f"{label} note {i}"
        require(isinstance(note, dict) and note.keys() == NOTE_FIELDS, where + ": missing/extra note fields")
        integer(note["pitch"], 0, 127, where + " pitch")
        integer(note["track"], 0, 255, where + " track")
        integer(note["velocity"], 1, 127, where + " velocity")
        require(type(note["percussion"]) is bool, where + ": invalid percussion")
        number(note["startMs"], where + " startMs")
        number(note["durationMs"], where + " durationMs", 0.000000001, 60_000)
        require(note["startMs"] + note["durationMs"] <= 1_800_000, where + ": note end out of budget")
    number(document.get("lengthMs"), label + " lengthMs")
    number(document.get("bpm"), label + " bpm", 0.000000001, 1_000_000_000)
    # Identity-first sorting tolerates reordered chords whose onsets round equal.
    return sorted(document["notes"], key=lambda n: (n["track"], n["pitch"], n["velocity"],
                  n["percussion"], n["startMs"], n["durationMs"]))


def compare_document(document, reference, label):
    actual, expected = notes(document, label), notes(reference, label + " independent SMF")
    require(len(actual) == len(expected), label + ": note count differs")
    onset = duration = 0.0
    for i, (a, b) in enumerate(zip(actual, expected)):
        require(all(a[k] == b[k] for k in ("pitch", "track", "velocity", "percussion")),
                f"{label}: note identity differs at sorted note {i}")
        onset = max(onset, abs(a["startMs"] - b["startMs"]))
        duration = max(duration, abs(a["durationMs"] - b["durationMs"]))
    length = abs(document["lengthMs"] - reference["lengthMs"])
    require(max(onset, duration, length) <= TIMING_TOLERANCE_MS,
            f"{label}: timing differs: onset={onset:.12g}, duration={duration:.12g}, length={length:.12g} ms")
    bpm_error = abs(document["bpm"] - reference["bpm"])
    require(bpm_error <= max(0.000001, reference["bpm"] * 0.00000001), label + ": BPM differs")
    return {"notes": len(actual), "maxOnsetErrorMs": onset, "maxDurationErrorMs": duration,
            "lengthErrorMs": length, "bpmError": bpm_error}


def midi_track_names(data):
    """Read source track-name events independently of converter track evidence."""
    require(len(data) >= 14 and data[:4] == b"MThd", "Invalid MIDI header")
    size = int.from_bytes(data[4:8], "big")
    fmt, count, division = struct.unpack(">HHH", data[8:14])
    require(size >= 6 and fmt in (0, 1) and 1 <= count <= 256 and 0 < division < 0x8000
            and (fmt != 0 or count == 1), "Unsupported MIDI header")
    pos, result = 8 + size, []

    def vlq(buf, at):
        value = 0
        for _ in range(4):
            require(at < len(buf), "Truncated MIDI VLQ")
            byte = buf[at]
            at += 1
            value = (value << 7) | (byte & 127)
            if byte < 128:
                return value, at
        raise AuditError("Invalid MIDI VLQ")

    for _ in range(count):
        require(data[pos:pos + 4] == b"MTrk" and pos + 8 <= len(data), "Missing MIDI track")
        length = int.from_bytes(data[pos + 4:pos + 8], "big")
        buf = data[pos + 8:pos + 8 + length]
        pos += 8 + length
        require(len(buf) == length, "Truncated MIDI track")
        at, running, names = 0, None, []
        while at < len(buf):
            _, at = vlq(buf, at)
            require(at < len(buf), "Missing MIDI event")
            status = buf[at]
            if status >= 128:
                at += 1
            else:
                require(running is not None, "Invalid MIDI running status")
                status = running
            if status == 0xff:
                require(at < len(buf), "Missing MIDI meta type")
                kind = buf[at]
                length, at = vlq(buf, at + 1)
                payload = buf[at:at + length]
                at += length
                require(len(payload) == length, "Truncated MIDI meta event")
                if kind == 0x03:
                    names.append(payload.decode("utf-8", errors="replace"))
                if kind == 0x2f:
                    require(length == 0 and at == len(buf), "Invalid MIDI end-of-track")
            elif status in (0xf0, 0xf7):
                length, at = vlq(buf, at)
                at += length
                require(at <= len(buf), "Truncated MIDI sysex")
                running = None
            else:
                require(0x80 <= status < 0xf0, "Unsupported MIDI system event")
                running = status
                length = 1 if status & 0xf0 in (0xc0, 0xd0) else 2
                require(at + length <= len(buf) and all(v < 128 for v in buf[at:at + length]),
                        "Invalid MIDI channel event")
                at += length
        result.append(names)
    require(pos == len(data), "Unparsed MIDI trailing bytes")
    return result


def melody_tracks(source_names, reference):
    melodic = {n["track"] for n in reference["notes"] if not n["percussion"]}
    selected = [i for i, names_ in enumerate(source_names)
                if i in melodic and any(name.strip().casefold() == "melody" for name in names_)]
    if not selected:
        require(len(melodic) == 1, "No source MELODY; multiple melodic tracks cannot be guessed")
        selected = sorted(melodic)
    return selected


def safety_claims(obj, label, fixture, provenance=False):
    require(isinstance(obj, dict), label + ": expected metadata object")
    for key in ("musicReviewed", "humanReviewed", "gameTested", "redistributionVerified", "isFormalSong"):
        if key in obj:
            require(obj[key] is False, label + ": forged/unsupported " + key)
    for key, expected in (("musicReview", "not-reviewed"), ("gameReview", "not-tested"),
                          ("completeness", "unknown")):
        if provenance or key in obj:
            require(obj.get(key) == expected, label + ": unsupported " + key)
    if provenance:
        require(obj.get("synthetic") is fixture, label + ": synthetic marker mismatch")
        require(obj.get("redistributionVerified") is False, label + ": redistribution not verified")
        require(obj.get("timingStatus") == "source-compared", label + ": timing status mismatch")
        require(obj.get("license") == LICENSE_DECLARATION, label + ": unsupported license declaration")


def catalog(path, evidence, expected_count, fixture=False):
    path = no_links(path)
    for suffix in ("-wal", "-shm", "-journal"):
        require(not path.with_name(path.name + suffix).exists(), "SQLite sidecar refused: " + suffix)
    evidence.watch(path)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        require(db.execute("PRAGMA integrity_check").fetchall() == [("ok",)], "SQLite integrity check failed")
        require(not db.execute("PRAGMA foreign_key_check").fetchall(), "SQLite foreign key check failed")
        meta = dict(db.execute("SELECT key,value FROM meta"))
        require(meta.get("schema") == "1" and meta.get("synthetic") == ("1" if fixture else "0"),
                "Catalogue schema/synthetic marker mismatch")
        rows = db.execute("SELECT id,work_id,relative_path,content_hash,original_hash,metadata_json FROM entries ORDER BY id").fetchall()
        require(len(rows) == expected_count, f"Catalogue count must be {expected_count}, got {len(rows)}")
        result, resources = {}, set()
        for identity, work, relative, content, original, raw in rows:
            require(isinstance(identity, str) and identity and identity not in result, "Duplicate/empty catalogue ID")
            entry = strict_json(raw, "Catalogue metadata " + identity)
            require(isinstance(entry, dict) and entry.get("id") == identity and entry.get("catalogId") == identity
                    and entry.get("builtIn") is True, "Catalogue stable ID/builtIn mismatch: " + identity)
            relative = relative_key(relative)
            require(relative.casefold() not in resources and relative.casefold().endswith(".json"),
                    "Duplicate/non-JSON catalogue resource: " + relative)
            resources.add(relative.casefold())
            require(entry.get("relativePath") == relative, "Catalogue relative_path mismatch: " + identity)
            require(isinstance(entry.get("provenance"), dict), "Catalogue provenance missing: " + identity)
            require(work == (entry["provenance"].get("workId") or identity), "Catalogue work_id mismatch: " + identity)
            resource_hash = hash_value(entry.get("resourceHash") or entry.get("hash"), identity + " resourceHash")
            require(hash_value(content, identity + " content_hash") == resource_hash
                    and hash_value(original, identity + " original_hash") == hash_value(entry.get("hash"), identity + " hash"),
                    "Catalogue SQL/metadata hash mismatch: " + identity)
            require(evidence.watch(resolve_resource(path.parent, relative)) == resource_hash,
                    "Catalogue resource hash mismatch: " + identity)
            result[identity] = {"entry": entry, "raw": raw, "sha256": resource_hash}
        search = db.execute("SELECT entry_id,duration,provider,timing_verified,completeness,human_reviewed FROM search_index").fetchall()
        require(len(search) == expected_count and len({r[0] for r in search}) == expected_count
                and {r[0] for r in search} == result.keys(), "Search index coverage/IDs mismatch")
        for identity, duration, provider, timing, complete, human in search:
            entry, provenance = result[identity]["entry"], result[identity]["entry"]["provenance"]
            require(abs(number(duration, identity + " search duration")
                        - number(entry.get("durationMs"), identity + " durationMs")) <= TIMING_TOLERANCE_MS
                    and provider == provenance.get("provider", "local")
                    and timing == int(provenance.get("timingStatus") == "source-compared")
                    and complete == provenance.get("completeness", "unknown")
                    and human == int(provenance.get("musicReview") == "human-reviewed"),
                    "Search index metadata mismatch: " + identity)
    return result


def file_set(root):
    result = set()
    for directory, dirs, files in os.walk(root, followlinks=False):
        no_links(directory)
        for name in dirs:
            no_links(Path(directory) / name)
        for name in files:
            path = no_links(Path(directory) / name)
            relative = relative_key(path.relative_to(root).as_posix())
            require(relative.casefold() not in result, "Case-insensitive file collision: " + relative)
            result.add(relative.casefold())
    return result


def validate_provenance(provenance, song, manifest, label, fixture):
    safety_claims(provenance, label, fixture, provenance=True)
    expected = {"workId": "pop909:" + song["id"],
                "editionId": "pop909:" + manifest["sourceCommit"] + ":" + song["id"],
                "provider": "POP909", "artist": song["artist"], "artists": [song["artist"]],
                "languageTags": song["languageTags"], "sourceUrl": song["sourceUrl"]}
    for key, value in expected.items():
        require(same(provenance.get(key), value), label + ": identity differs: " + key)
    require(hash_value(provenance.get("sourceSha256"), label + " sourceSha256")
            == hash_value(song["sourceSha256"], label + " manifest SHA"), label + ": source SHA mismatch")
    retrieved = provenance.get("retrievedAt")
    require(isinstance(retrieved, str), label + ": retrieval date missing")
    try:
        require(datetime.fromisoformat(retrieved.replace("Z", "+00:00"))
                == datetime.fromisoformat(manifest["retrievedAtUtc"].replace("Z", "+00:00")), label + ": retrieval date mismatch")
    except ValueError as error:
        raise AuditError(label + ": invalid retrieval date") from error
    for key, value in (("album", song.get("album", "")), ("versionLabel", song.get("versionLabel", ""))):
        require(provenance.get(key, "") == value, label + ": unsupported " + key)


def validate_options(entry, selected, label):
    options = entry.get("options")
    require(isinstance(options, dict), label + ": options missing")
    require(same(options.get("tracks"), selected), label + ": default tracks are not source MELODY only")
    require(options.get("excludePercussion") is True, label + ": percussion must be excluded by default")
    # Explicit true enables rather than inherits; false disables. New entries
    # keep the existing POP909 provider default (absent or nullable null).
    require(options.get("smartInterludes") is None, label + ": smartInterludes must inherit POP909 default")
    for key, expected in (("instrumentId", "windsong"), ("holdByScore", True), ("speed", 1),
                          ("octave", 0), ("accidentals", "Nearest"), ("range", "FoldOctaves"),
                          ("chords", "Simultaneous"), ("maxChordNotes", 5)):
        require(same(options.get(key), expected), label + ": unexpected default " + key)
    integer(options.get("transpose"), -24, 24, label + " transpose")


def audit(intake, stage, *, _fixture=False):
    intake, stage = no_links(intake), no_links(stage)
    require(intake.is_dir() and stage.is_dir(), "Intake/stage must be existing directories")
    require(not intake.resolve().is_relative_to(stage.resolve())
            and not stage.resolve().is_relative_to(intake.resolve()), "Intake/stage overlap")
    evidence = Evidence()
    manifest = evidence.json(intake / "manifest.json")
    report = evidence.json(stage / "build-report.json")
    baseline = evidence.json(stage / "baseline-entries.json")
    snapshots = evidence.json(stage / "baseline-input-hashes.json")
    require(isinstance(manifest, dict) and isinstance(manifest.get("songs"), list)
            and len(manifest["songs"]) == ADDED_SONGS, "Manifest must contain exactly 200 new songs")
    require(isinstance(manifest.get("sourceCommit"), str) and 0 < len(manifest["sourceCommit"]) <= 256,
            "Manifest sourceCommit missing/invalid")
    require(manifest.get("provider", "POP909") == "POP909", "Manifest provider mismatch")
    date = manifest.get("retrievedAtUtc")
    require(isinstance(date, str), "Manifest retrieval date missing")
    try:
        parsed_date = datetime.fromisoformat(date.replace("Z", "+00:00"))
    except ValueError as error:
        raise AuditError("Invalid retrieval date") from error
    require(parsed_date.tzinfo is not None and parsed_date.utcoffset() == timezone.utc.utcoffset(parsed_date),
            "Manifest retrieval date must be explicit UTC")
    require(isinstance(report, dict) and isinstance(report.get("status"), str)
            and report["status"].startswith("PASS"), "Build report incomplete/failed; do not publish")
    require(report.get("syntheticFixture") is _fixture, "Build syntheticFixture marker mismatch")
    safety_claims(report, "Build report", _fixture)
    for key in ("musicReviewed", "gameTested", "redistributionVerified", "audioPlayed"):
        require(report.get(key) is False, "Build report must not claim " + key)
    require(type(report.get("nativeKeySendAttempts")) is int and report["nativeKeySendAttempts"] == 0,
            "Build report declares OS key input")
    require(report.get("failure") in (None, "") and not report.get("failures"), "Build report has failures")
    for key in ("sourceFilesUnchanged", "baselineFilesUnchanged", "baselineMetadataUnchanged", "normalizedRoundTripPreserved"):
        if key in report:
            require(report[key] is True, "Build report declares incomplete check: " + key)
    if "sourceCommit" in report:
        require(report["sourceCommit"] == manifest["sourceCommit"], "Build/manifest sourceCommit mismatch")
    require(isinstance(baseline, list) and len(baseline) == BASELINE_SONGS, "Baseline must contain exactly 132 entries")
    old = {}
    old_paths, old_titles, old_source_ids, old_hashes, old_work_ids = set(), set(), set(), set(), set()
    for entry in baseline:
        require(isinstance(entry, dict), "Invalid baseline entry")
        identity = entry.get("id")
        require(isinstance(identity, str) and identity and identity not in old, "Duplicate baseline ID")
        require(entry.get("catalogId") == identity and entry.get("builtIn") is True, "Baseline stable ID mismatch")
        relative = relative_key(entry.get("relativePath"))
        require(relative.casefold() not in old_paths, "Duplicate baseline resource")
        old_paths.add(relative.casefold())
        old_titles.add(title_key(entry.get("title")))
        old_hashes.add(hash_value(entry.get("hash"), identity + " baseline hash"))
        provenance = entry.get("provenance")
        require(isinstance(provenance, dict), "Baseline provenance missing")
        old_work_ids.add(provenance.get("workId"))
        match = re.fullmatch(r"pop909-([0-9]{3})\.json", relative, re.IGNORECASE)
        if match:
            old_source_ids.add(match[1])
        work = provenance.get("workId", "")
        if isinstance(work, str) and re.fullmatch(r"pop909:[0-9]{3}", work, re.IGNORECASE):
            old_source_ids.add(work.split(":")[1])
        baseline_metadata(entry)
        old[identity] = entry
    require(isinstance(snapshots, list), "Baseline hashes must be FileEvidence list")
    protected = {}
    for item in snapshots:
        require(isinstance(item, dict), "Invalid baseline file evidence")
        relative = relative_key(item.get("relativePath"))
        require(relative.casefold() not in protected, "Duplicate baseline snapshot path")
        protected[relative.casefold()] = (relative, hash_value(item.get("sha256"), relative + " baseline SHA"))
    require("catalog.db" in protected and old_paths <= protected.keys(), "Baseline snapshot omits catalog/resources")
    require(not any(k.endswith(("-wal", "-shm", "-journal")) for k in protected), "Baseline SQLite sidecar refused")
    for identity, entry in old.items():
        require(protected[relative_key(entry["relativePath"]).casefold()][1]
                == hash_value(entry.get("resourceHash") or entry["hash"], identity + " baseline resourceHash"),
                "Baseline entries/snapshot hash mismatch: " + identity)

    inputs, ids, titles, source_hashes, paths = [], set(), set(), set(), set()
    for song in manifest["songs"]:
        require(isinstance(song, dict), "Invalid manifest song")
        identity = song.get("id")
        require(isinstance(identity, str) and re.fullmatch(r"[0-9]{3}", identity)
                and 1 <= int(identity) <= 909, "Invalid POP909 ID")
        require(identity not in ids and identity not in old_source_ids, "Duplicate/new-old source ID: " + identity)
        ids.add(identity)
        title = title_key(song.get("title"))
        require(title not in titles and title not in old_titles, "Duplicate/new-old title: " + song["title"])
        titles.add(title)
        require(isinstance(song.get("artist"), str) and song["artist"].strip(), "Manifest artist missing")
        require(isinstance(song.get("languageTags"), list) and all(isinstance(v, str) for v in song["languageTags"]),
                "Manifest languageTags invalid")
        source_hash = hash_value(song.get("sourceSha256"), identity + " manifest SHA")
        require(source_hash not in source_hashes and source_hash not in old_hashes, "Duplicate/new-old MIDI SHA: " + identity)
        source_hashes.add(source_hash)
        require(isinstance(song.get("sourceUrl"), str) and urlparse(song["sourceUrl"]).scheme in ("http", "https")
                and urlparse(song["sourceUrl"]).netloc, "Manifest source URL invalid")
        safety_claims(song, "Manifest " + identity, _fixture)
        for key, extensions in (("midiPath", (".mid", ".midi")), ("referencePath", (".json",))):
            value = song.get(key)
            require(isinstance(value, str) and Path(value).is_absolute(), "Manifest input must be absolute: " + key)
            path = no_links(value)
            require(path.is_file() and path.suffix.lower() in extensions and not path.resolve().is_relative_to(stage.resolve()),
                    "Manifest missing/invalid/stage-owned input: " + key)
            folded = str(path.resolve()).casefold()
            require(folded not in paths, "Duplicate manifest input path")
            paths.add(folded)
        relative = "pop909-" + identity + ".json"
        catalog_id = "builtin:" + relative
        require(relative.casefold() not in old_paths and catalog_id not in old
                and "pop909:" + identity not in old_work_ids, "New/old catalogue identity overlap")
        inputs.append((song, relative, catalog_id))

    songs_root = no_links(stage / "Songs")
    require(songs_root.is_dir(), "Stage Songs directory missing")
    expected_files = set(protected) | {r.casefold() for _, r, _ in inputs}
    require(file_set(songs_root) == expected_files, "Stage resource file set missing/extra versus baseline + 200")
    observed = catalog(songs_root / "catalog.db", evidence, CATALOG_SONGS, _fixture)
    require(observed.keys() == old.keys() | {i for _, _, i in inputs}, "Catalogue entry ID set differs from baseline + 200")
    for relative, digest in protected.values():
        if relative.casefold() != "catalog.db":
            require(evidence.watch(resolve_resource(songs_root, relative)) == digest, "Baseline file bytes changed: " + relative)
    for identity, expected in old.items():
        require(same(baseline_metadata(observed[identity]["entry"]), baseline_metadata(expected)),
                "Baseline metadata/defaults changed: " + identity)

    # Prefer the isolated original baseline adjacent to the caller's stage.
    # Hash matching, not its directory name or a converter flag, anchors it.
    raw_baseline_checks, baseline_anchor = 0, None
    isolated_anchor = stage.parent / "baseline-Songs" / "catalog.db"
    if isolated_anchor.parent.exists():
        require(isolated_anchor.is_file(), "Original baseline catalogue missing")
    for candidate in (isolated_anchor, REPO / "Songs" / "catalog.db"):
        anchor = no_links(candidate)
        if not anchor.is_file():
            continue
        digest = sha(anchor)
        if candidate == isolated_anchor:
            require(digest == protected["catalog.db"][1], "Original baseline catalogue hash mismatch")
        if digest != protected["catalog.db"][1]:
            continue
        anchored = catalog(anchor, evidence, BASELINE_SONGS, _fixture)
        require(file_set(anchor.parent) == set(protected), "Original baseline file snapshot coverage mismatch")
        for relative, expected_hash in protected.values():
            require(evidence.watch(resolve_resource(anchor.parent, relative)) == expected_hash,
                    "Original baseline file hash mismatch: " + relative)
        require(anchored.keys() == old.keys(), "Original baseline/snapshot ID mismatch")
        for identity, row in anchored.items():
            require(row["raw"] == observed[identity]["raw"], "Original baseline raw metadata changed: " + identity)
        raw_baseline_checks = len(anchored)
        baseline_anchor = str(anchor)
        break

    index = None
    if (intake / "index.xlsx").exists():
        from discover_pop_metadata import parse_index
        index = {r["sourceIndexId"]: r for r in parse_index(evidence.read(intake / "index.xlsx"))}
    report_songs = report.get("songs")
    require(isinstance(report_songs, list) and len(report_songs) == ADDED_SONGS, "Build report song coverage must match manifest 200")
    report_by_id = {}
    for item in report_songs:
        require(isinstance(item, dict) and item.get("id") in ids and item["id"] not in report_by_id,
                "Build report song IDs duplicate/unknown")
        report_by_id[item["id"]] = item
    rows, total_notes = [], 0
    max_onset = max_duration = max_length = 0.0
    for song, relative, catalog_id in inputs:
        identity, label = song["id"], "Song " + song["id"]
        source = evidence.read(song["midiPath"])
        source_hash = hashlib.sha256(source).hexdigest().upper()
        require(source_hash == song["sourceSha256"].upper(), label + ": original MIDI SHA mismatch")
        source_names = midi_track_names(source)
        independent = parse_smf(source)
        reference = evidence.json(song["referencePath"])
        reference_comparison = compare_document(reference, independent, label + " supplied reference")
        for key in ("tempoChanges", "ticksPerQuarter", "durationKinds"):
            require(type(reference.get(key)) is int and reference[key] == independent[key], label + ": reference " + key + " mismatch")
        if "sourceSha256" in reference:
            require(hash_value(reference["sourceSha256"], label + " reference source SHA") == source_hash,
                    label + ": reference source SHA mismatch")
        normalized_path = resolve_resource(songs_root, relative)
        normalized = evidence.json(normalized_path)
        comparison = compare_document(normalized, independent, label + " normalized")
        normalized_reference_comparison = compare_document(normalized, reference, label + " normalized/reference")
        normalized_hash = evidence.watch(normalized_path)
        entry = observed[catalog_id]["entry"]
        require(normalized.get("title") == entry.get("title") == song["title"], label + ": title mismatch")
        safety_claims(normalized, label + " normalized", _fixture)
        safety_claims(entry, label + " catalogue", _fixture)
        validate_provenance(normalized.get("provenance"), song, manifest, label + " provenance", _fixture)
        require(same(entry["provenance"], normalized["provenance"]), label + ": catalogue/score provenance differs")
        require(hash_value(entry.get("hash"), label + " catalogue source hash") == source_hash
                and hash_value(entry.get("resourceHash"), label + " catalogue normalized hash") == normalized_hash,
                label + ": source/normalized catalogue SHA mismatch")
        notation_hash = normalized["provenance"].get("notationSha256", "")
        if notation_hash:
            require(hash_value(notation_hash, label + " notation SHA") == normalized_hash, label + ": notation SHA mismatch")
        require(type(entry.get("notesCount")) is int and entry["notesCount"] == len(independent["notes"]), label + ": catalogue note count mismatch")
        source_duration = max(independent["lengthMs"], max(n["startMs"] + n["durationMs"] for n in independent["notes"]))
        require(abs(number(entry.get("durationMs"), label + " catalogue duration") - source_duration) <= TIMING_TOLERANCE_MS,
                label + ": catalogue duration differs")
        require(abs(number(entry.get("bpm"), label + " catalogue bpm", 0.000000001, 1_000_000_000) - independent["bpm"])
                <= max(0.000001, independent["bpm"] * 0.00000001), label + ": catalogue BPM differs")
        for key in ("author", "category"):
            require(entry.get(key) == normalized.get(key), label + ": catalogue/score " + key + " differs")
        selected = melody_tracks(source_names, independent)
        validate_options(entry, selected, label)
        if index is not None:
            require(identity in index and index[identity]["title"] == song["title"]
                    and index[identity]["artists"] == [song["artist"]], label + ": source index title/artist mismatch")
        for key, expected in (("notes", len(independent["notes"])), ("tempoChanges", independent["tempoChanges"]),
                              ("durationKinds", independent["durationKinds"])):
            if key in song:
                require(type(song[key]) is int and song[key] == expected, label + ": manifest " + key + " differs")
        if "durationMs" in song:
            require(abs(number(song["durationMs"], label + " manifest duration") - source_duration) <= TIMING_TOLERANCE_MS,
                    label + ": manifest duration differs")
        claimed = report_by_id[identity]
        for key, expected in (("title", song["title"]), ("artist", song["artist"]), ("languageTags", song["languageTags"]),
                              ("sourceUrl", song["sourceUrl"]), ("selectedTracks", selected), ("notes", len(independent["notes"]))):
            if key in claimed:
                require(same(claimed[key], expected), label + ": build report " + key + " mismatch")
        for key, expected in (("sourceSha256", source_hash), ("jsonSha256", normalized_hash)):
            if key in claimed:
                require(hash_value(claimed[key], label + " report " + key) == expected, label + ": build report SHA mismatch")
        for key, expected in (("lengthMs", independent["lengthMs"]), ("durationMs", source_duration)):
            if key in claimed:
                require(abs(number(claimed[key], label + " report " + key) - expected) <= TIMING_TOLERANCE_MS,
                        label + ": build report timing mismatch")
        timing = claimed.get("timing")
        if timing is not None:
            require(isinstance(timing, dict), label + ": invalid build timing evidence")
            if "referenceSha256" in timing:
                require(hash_value(timing["referenceSha256"], label + " report reference SHA") == evidence.watch(song["referencePath"]),
                        label + ": build reference SHA mismatch")
        total_notes += comparison["notes"]
        comparisons = (comparison, reference_comparison, normalized_reference_comparison)
        max_onset = max(max_onset, *(c["maxOnsetErrorMs"] for c in comparisons))
        max_duration = max(max_duration, *(c["maxDurationErrorMs"] for c in comparisons))
        max_length = max(max_length, *(c["lengthErrorMs"] for c in comparisons))
        rows.append({"id": identity, "title": song["title"], "artist": song["artist"],
                     "sourceSha256": source_hash, "normalizedSha256": normalized_hash,
                     "referenceSha256": evidence.watch(song["referencePath"]), "selectedTracks": selected,
                     "smartInterludesInherited": True, "effectivePop909SmartInterludesDefault": True,
                     "normalizedComparison": comparison, "referenceComparison": reference_comparison,
                     "normalizedReferenceComparison": normalized_reference_comparison})

    catalog_hash = evidence.watch(songs_root / "catalog.db")
    for key in ("coldStart", "restart"):
        claimed = report.get(key)
        if isinstance(claimed, dict) and "catalogSha256" in claimed:
            require(hash_value(claimed["catalogSha256"], key + " catalogue SHA") == catalog_hash, "Build store catalogue SHA mismatch")
    for item in report.get("waves", []):
        require(isinstance(item, dict), "Invalid build wave evidence")
        require(evidence.watch(resolve_resource(stage, item.get("relativePath"))) == hash_value(item.get("sha256"), "Wave SHA"),
                "Build wave SHA mismatch")
    if (stage / "input-manifest.json").exists():
        captured = evidence.json(stage / "input-manifest.json")
        require(isinstance(captured, dict) and captured.get("sourceCommit") == manifest["sourceCommit"]
                and isinstance(captured.get("retrievedAtUtc"), str) and isinstance(captured.get("songs"), list), "Captured manifest differs")
        try:
            captured_date = datetime.fromisoformat(captured["retrievedAtUtc"].replace("Z", "+00:00"))
        except ValueError as error:
            raise AuditError("Captured manifest date invalid") from error
        require(captured_date == parsed_date, "Captured manifest date differs")
        def projection(value):
            fields = ("id", "title", "artist", "midiPath", "referencePath", "sourceUrl", "sourceSha256", "languageTags")
            require(all(isinstance(item, dict) and all(k in item for k in fields) for item in value["songs"]),
                    "Captured/manifest song missing 8-field contract")
            return sorted(({k: item[k] for k in fields} for item in value["songs"]), key=lambda item: item["id"])
        require(same(projection(captured), projection(manifest)), "Captured input-manifest song set differs")
    require(file_set(songs_root) == expected_files, "Stage file set changed during audit")
    evidence.unchanged()
    warnings = ["Numerical/source-byte verification only; not music review, game testing, rights clearance, or deployment."]
    if not raw_baseline_checks:
        warnings.append("Old metadata compared to supplied baseline-entries snapshot; exact original metadata strings not independently anchored.")
    if index is None:
        warnings.append("No intake index.xlsx: title/artist checked against manifest, not an independent source index.")
    return {"status": "PASS_SYNTHETIC_FIXTURE_ONLY" if _fixture else "PASS_INDEPENDENT_OUTPUT_AUDIT",
            "evidenceClass": "SYNTHETIC_FIXTURE_ONLY_NOT_REAL_SONGS" if _fixture else "INDEPENDENT_SOURCE_BYTES_AND_TIMING_ONLY",
            "syntheticFixture": _fixture, "countedAsRealSongs": not _fixture,
            "realSourceSongsVerified": 0 if _fixture else ADDED_SONGS,
            "sourceFiles": ADDED_SONGS, "baselineEntries": BASELINE_SONGS, "catalogEntries": len(observed),
            "sourceNotesCompared": total_notes, "timingToleranceMs": TIMING_TOLERANCE_MS,
            "maxOnsetErrorMs": max_onset, "maxDurationErrorMs": max_duration, "maxLengthErrorMs": max_length,
            "maxTimingErrorMs": max(max_onset, max_duration, max_length),
            "baselineScoreBytesUnchanged": True, "baselineMetadataSnapshotPreserved": True,
            "baselineRawMetadataChecks": raw_baseline_checks, "baselineCatalogAnchor": baseline_anchor,
            "metadataIndexVerified": index is not None, "catalogIntegrity": "ok", "catalogSha256": catalog_hash,
            "checkedFileHashes": len(evidence.hashes), "sourceSongs": rows,
            "musicReviewed": False, "realGameTested": False, "redistributionVerified": False,
            "audioPlayed": False, "nativeKeySendAttempts": 0, "deployed": False, "warnings": warnings}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intake", type=Path, required=True, help="NEW intake directory containing manifest.json")
    parser.add_argument("--stage", type=Path, required=True, help="NEW stage directory containing Songs and baseline evidence")
    parser.add_argument("--report", type=Path, required=True, help="NEW JSON report, never overwritten")
    args = parser.parse_args(argv)
    try:
        output = no_links(args.report)
        require(output.suffix.lower() == ".json" and output.parent.is_dir(), "Report needs .json and an existing parent")
        require(not output.exists(), "Report already exists; refusing overwrite: " + str(output))
        require(not output.resolve().is_relative_to(args.intake.resolve())
                and not output.resolve().is_relative_to((args.stage / "Songs").resolve()), "Report cannot be inside intake/Songs")
    except (OSError, AuditError) as error:
        print(str(error), file=sys.stderr)
        return 2
    try:
        result = audit(args.intake, args.stage)
        code = 0
    except Exception as error:
        result = {"status": "FAILED_INDEPENDENT_OUTPUT_AUDIT", "error": type(error).__name__ + ": " + str(error),
                  "realSourceSongsVerified": 0, "countedAsRealSongs": False, "deployed": False,
                  "nativeKeySendAttempts": 0, "musicReviewed": False, "realGameTested": False,
                  "redistributionVerified": False}
        code = 1
    try:
        with output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
    except OSError as error:
        print("Unable to create NEW report: " + str(error), file=sys.stderr)
        return 2
    print(result["status"])
    return code


if __name__ == "__main__":
    raise SystemExit(main())

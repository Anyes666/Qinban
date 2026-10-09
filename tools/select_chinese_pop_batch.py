#!/usr/bin/env python3
"""Read-only evidence gate and deterministic ranker for Chinese-pop batches."""
from __future__ import annotations
import argparse, hashlib, json, math, re, sqlite3, sys, unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

PLATFORMS = {
    "douyin": ("douyin.com", "iesdouyin.com"),
    "kugou": ("kugou.com",),
    "netease": ("163.com",),
}
RECENT_YEARS = 3
RECENT_SHARE = 0.25
CHART_MAX_AGE_DAYS = 180
MIB = 1024 * 1024
MAX_JSON_BYTES = 8 * MIB
MAX_CANDIDATES = 1000


class InputLimitError(ValueError):
    """Bounded admission input is too large; no production write is allowed."""


def read_json_bounded(path, max_bytes=MAX_JSON_BYTES):
    if max_bytes < 1 or path.stat().st_size > max_bytes:
        raise InputLimitError(f"JSON input exceeds {max_bytes} bytes: {path}")
    with path.open("rb") as handle:
        raw = handle.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise InputLimitError(f"JSON input grew past {max_bytes} bytes: {path}")
    return json.loads(raw.decode("utf-8-sig"))


def _key(s):
    return re.sub(r"[^a-z0-9]", "", str(s).casefold())


def get(obj, *names, default=None):
    if not isinstance(obj, dict):
        return default
    fields = {_key(k): v for k, v in obj.items()}
    for name in names:
        if _key(name) in fields:
            return fields[_key(name)]
    return default


def text(v):
    return "" if v is None else str(v).strip()


def canon(v):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text(v)).casefold())


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def valid_hash(value):
    value = text(value).upper()
    return value if re.fullmatch(r"[0-9A-F]{64}", value) else ""


def safe_file(root, raw):
    if not text(raw):
        return None, "path_missing"
    try:
        base = root.resolve(strict=True)
        path = Path(text(raw))
        if not path.is_absolute():
            path = base / path
        path = path.resolve(strict=True)
        path.relative_to(base)
        return (path, None) if path.is_file() else (None, "not_a_file")
    except ValueError:
        return None, "path_outside_root"
    except (OSError, RuntimeError):
        return None, "path_missing"


def evidence(root, ref):
    if not isinstance(ref, dict):
        return None, "evidence_reference_missing"
    path, err = safe_file(root, get(ref, "path", "evidencePath"))
    if err:
        return None, f"evidence_{err}"
    if path.stat().st_size > MAX_JSON_BYTES:
        return None, "evidence_json_exceeds_byte_limit"
    expected = valid_hash(get(ref, "sha256", "evidenceSha256"))
    if not expected:
        return None, "evidence_sha256_missing_or_invalid"
    if digest(path) != expected:
        return None, "evidence_sha256_mismatch"
    try:
        value = read_json_bounded(path)
    except InputLimitError:
        return None, "evidence_json_exceeds_byte_limit"
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "evidence_json_invalid"
    return (value, None) if isinstance(value, dict) else (None, "evidence_not_object")


def verify_source_artifact(root, evidence_row):
    """Verify a local copy/snapshot cited by an evidence ledger."""
    ref = get(evidence_row, "sourceArtifact", "snapshotArtifact")
    if not isinstance(ref, dict):
        return "evidence_source_artifact_missing"
    path, err = safe_file(root, get(ref, "path"))
    if err:
        return "evidence_source_artifact_" + err
    expected = valid_hash(get(ref, "sha256"))
    if not expected:
        return "evidence_source_artifact_hash_missing_or_invalid"
    if digest(path) != expected:
        return "evidence_source_artifact_hash_mismatch"
    return None

def https(value):
    parsed = urlparse(text(value))
    return parsed.scheme == "https" and bool(parsed.hostname)


def official_host(value, suffixes):
    parsed = urlparse(text(value))
    host = (parsed.hostname or "").casefold().rstrip(".")
    return parsed.scheme == "https" and any(host == d or host.endswith("." + d) for d in suffixes)


def iso_date(value):
    try:
        return date.fromisoformat(text(value)[:10])
    except (TypeError, ValueError):
        return None


def subtract_years(d, years):
    try:
        return d.replace(year=d.year - years)
    except ValueError:
        return d.replace(year=d.year - years, day=28)


def load_manifest(path, *, max_bytes=MAX_JSON_BYTES, max_candidates=MAX_CANDIDATES):
    data = read_json_bounded(path, max_bytes)
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = next((get(data, k) for k in ("songs", "candidates", "items", "allCanonicalCandidates") if isinstance(get(data, k), list)), None)
        if rows is None:
            raise ValueError(f"candidate list missing: {path}")
    else:
        raise ValueError(f"manifest must be a JSON object or array: {path}")
    if len(rows) > max_candidates:
        raise InputLimitError(f"candidate count exceeds {max_candidates}: {path}")
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"manifest contains a non-object candidate: {path}")
    return [dict(row) for row in rows]


def load_installed_catalog(path):
    found = {"sourceHashes": set(), "editionIds": set()}
    if path is None:
        return found
    db = sqlite3.connect(path.resolve(strict=True).as_uri() + "?mode=ro", uri=True)
    try:
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"catalog integrity_check failed: {integrity}")
        for (raw,) in db.execute('SELECT metadata_json FROM entries'):
            try:
                row = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue
            prov = get(row, "provenance", default={})
            source_hash = valid_hash(get(prov, "sourceSha256", "sourceHash", "notationSha256"))
            edition = text(get(prov, "editionId"))
            if source_hash:
                found["sourceHashes"].add(source_hash)
            if edition:
                found["editionIds"].add(edition)
    finally:
        db.close()
    return found


def summary(row):
    artists = get(row, "artists", default=[])
    if not isinstance(artists, list):
        artists = []
    artist = text(get(row, "artist")) or (text(artists[0]) if artists else "")
    return {"id": text(get(row, "id", "candidateId")), "title": text(get(row, "title")), "artist": artist,
            "workId": text(get(row, "workId")), "editionId": text(get(row, "editionId")),
            "versionLabel": text(get(row, "versionLabel"))}


def validate_identity(row, root, s, langs, release):
    ev, err = evidence(root, get(row, "identityEvidence"))
    if err:
        return [err]
    errors = []
    artifact_error = verify_source_artifact(root, ev)
    if artifact_error:
        errors.append(artifact_error)
    if text(get(ev, "status", "reviewStatus")).casefold() != "verified":
        errors.append("identity_evidence_not_verified")
    for field in ("title", "artist", "workId", "editionId", "versionLabel"):
        if canon(get(ev, field)) != canon(s[field]):
            errors.append("identity_" + field + "_mismatch")
    ev_langs = get(ev, "languageTags", default=[])
    if not isinstance(ev_langs, list) or not set(langs).issubset({text(x).casefold() for x in ev_langs}):
        errors.append("identity_language_mismatch")
    if release is None or iso_date(get(ev, "releaseDate")) != release:
        errors.append("identity_release_date_mismatch_or_missing")
    if not https(get(ev, "sourceUrl", "url")):
        errors.append("identity_source_url_missing_or_invalid")
    return errors


def validate_rights(row, root, s, as_of):
    errors = []
    if get(row, "redistributionVerified") is not True:
        errors.append("redistribution_not_verified")
    if get(row, "adaptationAllowed") is not True:
        errors.append("adaptation_not_verified")
    ev, err = evidence(root, get(row, "rightsEvidence"))
    if err:
        return errors + [err]
    artifact_error = verify_source_artifact(root, ev)
    if artifact_error:
        errors.append(artifact_error)
    if text(get(ev, "status", "reviewStatus")).casefold() != "verified":
        errors.append("rights_evidence_not_verified")
    if text(get(ev, "workId")) != s["workId"]:
        errors.append("rights_work_id_mismatch")
    if text(get(ev, "editionId")) != s["editionId"]:
        errors.append("rights_edition_id_mismatch")
    if not text(get(ev, "licenseId", "license")):
        errors.append("rights_license_missing")
    scope = get(ev, "scope", default={})
    if get(scope, "adaptation") is not True:
        errors.append("rights_scope_adaptation_missing")
    if get(scope, "desktopSoftwareRedistribution", "softwareRedistribution") is not True:
        errors.append("rights_scope_software_redistribution_missing")
    if not https(get(ev, "grantSourceUrl", "sourceUrl")):
        errors.append("rights_grant_source_url_missing_or_invalid")
    reviewed = iso_date(get(ev, "reviewedAt"))
    if not reviewed or reviewed > as_of or not text(get(ev, "reviewer")):
        errors.append("rights_review_receipt_missing_or_future")
    return errors


def validate_charts(row, root, s, as_of, max_age_days):
    records = get(row, "chartEvidence", "charts", default=[])
    records = records if isinstance(records, list) else []
    valid, rejected = [], []
    for i, record in enumerate(records):
        if not isinstance(record, dict):
            rejected.append(f"chart_{i}_not_object")
            continue
        platform = text(get(record, "platform")).casefold()
        observed = iso_date(get(record, "observedAt", "date"))
        try:
            rank = int(get(record, "rank"))
        except (TypeError, ValueError):
            rejected.append(f"chart_{i}_rank_invalid")
            continue
        url = text(get(record, "sourceUrl", "url"))
        if platform not in PLATFORMS:
            rejected.append(f"chart_{i}_unsupported_platform")
            continue
        if rank < 1 or observed is None or observed > as_of or (as_of - observed).days > max_age_days:
            rejected.append(f"chart_{i}_rank_or_date_invalid_or_stale")
            continue
        if not official_host(url, PLATFORMS[platform]):
            rejected.append(f"chart_{i}_not_official_https_host")
            continue
        ev, err = evidence(root, get(record, "evidence"))
        if err:
            rejected.append(f"chart_{i}_{err}")
            continue
        artifact_error = verify_source_artifact(root, ev)
        if artifact_error:
            rejected.append(f"chart_{i}_{artifact_error}")
            continue
        try:
            ev_rank = int(get(ev, "rank", default=-1))
        except (TypeError, ValueError):
            ev_rank = -1
        matches = (
            text(get(ev, "platform")).casefold() == platform and ev_rank == rank
            and iso_date(get(ev, "observedAt", "date")) == observed
            and canon(get(ev, "title")) == canon(s["title"])
            and canon(get(ev, "artist")) == canon(s["artist"])
            and text(get(ev, "sourceUrl", "url")) == url
        )
        if not matches:
            rejected.append(f"chart_{i}_evidence_mismatch")
            continue
        valid.append({"platform": platform, "rank": rank, "observedAt": observed.isoformat(), "sourceUrl": url})
    newest = {}
    for item in valid:
        old = newest.get(item["platform"])
        if old is None or (item["observedAt"], -item["rank"]) > (old["observedAt"], -old["rank"]):
            newest[item["platform"]] = item
    if not newest:
        return ["no_fresh_verified_official_chart_evidence"], rejected, []
    return [], rejected, list(newest.values())


def evaluate(row, root, as_of, max_age_days, installed):
    s = summary(row)
    errors = []
    for field in ("title", "artist", "workId", "editionId", "versionLabel"):
        if not s[field]:
            errors.append(field + "_missing")
    raw_langs = get(row, "languageTags", default=[])
    langs = [text(x).casefold() for x in raw_langs] if isinstance(raw_langs, list) else []
    zh_langs = [x for x in langs if x.split("-")[0] in {"zh", "yue", "cmn"}]
    if not zh_langs or text(get(row, "languageStatus")).casefold() != "verified":
        errors.append("chinese_language_not_verified")
    release = iso_date(get(row, "releaseDate"))
    if release and release > as_of:
        errors.append("release_date_in_future")
    errors.extend(validate_identity(row, root, s, zh_langs, release))
    errors.extend(validate_rights(row, root, s, as_of))
    chart_errors, chart_rejected, charts = validate_charts(row, root, s, as_of, max_age_days)
    errors.extend(chart_errors)
    if chart_errors:
        errors.extend(chart_rejected)
    source_path, path_error = safe_file(root, get(row, "midiPath", "rawMidiPath", "sourcePath"))
    expected = valid_hash(get(row, "sourceSha256"))
    actual = ""
    if path_error:
        errors.append("source_" + path_error)
    elif not expected:
        errors.append("source_sha256_missing_or_invalid")
    else:
        actual = digest(source_path)
        if actual != expected:
            errors.append("source_sha256_mismatch")
        if actual in installed["sourceHashes"]:
            errors.append("source_already_in_catalog")
    if s["editionId"] in installed["editionIds"]:
        errors.append("edition_already_in_catalog")
    artists = get(row, "artists", default=[])
    artists = artists if isinstance(artists, list) else []
    artist_keys = sorted({canon(x) for x in artists if canon(x)})
    if canon(s["artist"]) and canon(s["artist"]) not in artist_keys:
        artist_keys.append(canon(s["artist"]))
    score = sum(1.0 / x["rank"] for x in charts)
    recent = release is not None and release >= subtract_years(as_of, RECENT_YEARS)
    errors = list(dict.fromkeys(errors))
    return {**s, "sourceSha256Expected": expected, "sourceSha256Actual": actual,
            "releaseDate": release.isoformat() if release else "", "recentEdition": recent,
            "chartEvidence": charts, "chartEvidenceRejected": chart_rejected,
            "chartScore": round(score, 8), "chartPlatformCount": len(charts),
            "bestChartRank": min((x["rank"] for x in charts), default=None),
            "latestChartDate": max((x["observedAt"] for x in charts), default=""),
            "artistKeys": artist_keys, "eligible": not errors, "rejectionReasons": errors}


def _rank_key(item):
    date_key = int(item["latestChartDate"].replace("-", "") or "0")
    return (-item["chartScore"], -item["chartPlatformCount"], item["bestChartRank"] or 10**9,
            -date_key, item["title"].casefold(), item["editionId"])


def _can_add(item, selected, artist_cap, work_cap):
    if any(x["sourceSha256Actual"] == item["sourceSha256Actual"] or x["editionId"] == item["editionId"] for x in selected):
        return False
    if sum(x["workId"] == item["workId"] for x in selected) >= work_cap:
        return False
    return all(sum(a in x["artistKeys"] for x in selected) < artist_cap for a in item["artistKeys"])


def select_batch(candidates, root, as_of, *, limit=100, recent_share=RECENT_SHARE,
                 max_age_days=CHART_MAX_AGE_DAYS, max_per_artist=None, max_per_work=2, installed=None):
    if limit < 1 or not 0 <= recent_share <= 1 or max_age_days < 0 or max_per_work < 1:
        raise ValueError("invalid limit, recent share, chart age, or work cap")
    installed = installed or {"sourceHashes": set(), "editionIds": set()}
    checked = [evaluate(x, root, as_of, max_age_days, installed) for x in candidates]
    eligible = sorted((x for x in checked if x["eligible"]), key=_rank_key)
    if max_per_artist is not None and max_per_artist < 1:
        raise ValueError("max_per_artist must be >= 1")
    artist_cap = max_per_artist if max_per_artist is not None else max(1, math.ceil(limit * 0.10))

    # Reserve recent editions first so older high-ranked tracks cannot consume all artist slots.
    capped = []
    for item in sorted(eligible, key=lambda x: (not x["recentEdition"], _rank_key(x))):
        if len(capped) >= limit:
            break
        if _can_add(item, capped, artist_cap, max_per_work):
            capped.append(item)
    target = len(capped)
    required_recent = math.ceil(target * recent_share) if target else 0
    provisional = [x for x in capped if x["recentEdition"]][:required_recent]
    if len(provisional) < required_recent:
        status, selected = "HOLD_RECENT_DIVERSITY", []
    else:
        selected = provisional + [x for x in capped if x not in provisional]
        status = "READY" if len(selected) == limit else ("PARTIAL_READY" if selected else "NO_ELIGIBLE_CANDIDATES")

    reasons = {}
    for item in checked:
        for reason in item["rejectionReasons"]:
            reasons[reason] = reasons.get(reason, 0) + 1
    selected_keys = {(x["id"], x["editionId"]) for x in selected}
    held = [{"id": x["id"], "title": x["title"], "artist": x["artist"], "workId": x["workId"],
             "editionId": x["editionId"], "recentEdition": x["recentEdition"]} for x in capped] if status == "HOLD_RECENT_DIVERSITY" else []
    return {
        "schemaVersion": "qinban.chinese-pop-priority-audit.v1",
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "asOfDate": as_of.isoformat(),
        "status": status,
        "policy": {"verifiedLanguages": ["zh", "yue", "cmn"], "exactSourceMidiSha256": True,
                    "identityEvidenceMustMatchTitleArtistWorkEditionVersionAndReleaseDate": True,
                    "rightsMustAllowAdaptationAndDesktopRedistribution": True,
                    "freshOfficialChartDays": max_age_days, "chartPlatforms": sorted(PLATFORMS),
                    "recentEditionWindowYears": RECENT_YEARS, "minimumRecentEditionShare": recent_share,
                    "maxPerArtist": artist_cap, "maxEditionsPerWork": max_per_work,
                    "rankRule": "sum(1/rank) using newest valid snapshot per platform"},
        "counts": {"input": len(candidates), "eligibleBeforeDiversity": len(eligible),
                   "eligibleAfterDiversity": len(capped), "selected": len(selected),
                   "selectedRecentEditions": sum(x["recentEdition"] for x in selected),
                   "requiredRecentEditions": required_recent,
                   "rejected": sum(not x["eligible"] for x in checked),
                   "rejectionReasons": dict(sorted(reasons.items()))},
        "selectedCandidates": [{k: v for k, v in x.items() if k not in ("artistKeys", "eligible", "rejectionReasons", "chartEvidenceRejected")} for x in selected],
        "provisionalCandidatesHeld": held,
        "rejectedCandidates": [{"id": x["id"], "title": x["title"], "artist": x["artist"],
                                "workId": x["workId"], "editionId": x["editionId"],
                                "rejectionReasons": x["rejectionReasons"]} for x in checked if not x["eligible"]],
        "boundary": "Read-only source/evidence gate only; not legal advice, musical review, instrument adaptation, or in-game acceptance. No production files are modified."
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only Chinese-pop candidate admission and ranking")
    parser.add_argument("--manifest", action="append", required=True, help="candidate JSON; repeat to combine batches")
    parser.add_argument("--root", type=Path, required=True, help="path boundary for score/evidence files")
    parser.add_argument("--installed-catalog", type=Path, help="optional catalog.db opened read-only for duplicate checks")
    parser.add_argument("--report", type=Path, required=True, help="new report path; will not overwrite")
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--max-input-mib", type=int, default=8, help="combined manifest JSON limit")
    parser.add_argument("--max-candidates", type=int, default=1000, help="combined candidate limit")
    parser.add_argument("--max-report-mib", type=int, default=8, help="report size limit; no partial write")
    parser.add_argument("--minimum-recent-share", type=float, default=RECENT_SHARE)
    parser.add_argument("--chart-max-age-days", type=int, default=CHART_MAX_AGE_DAYS)
    parser.add_argument("--max-per-artist", type=int)
    parser.add_argument("--max-per-work", type=int, default=2)
    args = parser.parse_args(argv)
    try:
        if min(args.max_input_mib, args.max_candidates, args.max_report_mib) < 1:
            raise ValueError("resource limits must be positive")
        input_bytes = sum(Path(name).stat().st_size for name in args.manifest)
        if input_bytes > args.max_input_mib * MIB:
            raise InputLimitError("combined manifests exceed --max-input-mib")
        rows = []
        for name in args.manifest:
            rows.extend(load_manifest(Path(name), max_bytes=args.max_input_mib * MIB,
                                      max_candidates=args.max_candidates))
            if len(rows) > args.max_candidates:
                raise InputLimitError("combined candidates exceed --max-candidates")
        installed = load_installed_catalog(args.installed_catalog)
        report = select_batch(rows, args.root, args.as_of, limit=args.limit,
                              recent_share=args.minimum_recent_share, max_age_days=args.chart_max_age_days,
                              max_per_artist=args.max_per_artist, max_per_work=args.max_per_work, installed=installed)
        report["inputs"] = {"manifests": [str(Path(x).resolve()) for x in args.manifest],
                            "root": str(args.root.resolve(strict=True)),
                            "installedCatalog": str(args.installed_catalog.resolve(strict=True)) if args.installed_catalog else None,
                            "installedSourceHashCount": len(installed["sourceHashes"]),
                            "installedEditionCount": len(installed["editionIds"])}
        report["resourceLimits"] = {"batchLimit": args.limit, "combinedManifestBytes": input_bytes,
                                    "maxManifestBytes": args.max_input_mib * MIB,
                                    "maxCandidates": args.max_candidates, "maxReportBytes": args.max_report_mib * MIB,
                                    "maxEvidenceJsonBytes": MAX_JSON_BYTES, "hashReadChunkBytes": MIB,
                                    "workers": 1, "copiesBaselineLibrary": False}
        payload = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if len(payload) > args.max_report_mib * MIB:
            raise InputLimitError("report exceeds --max-report-mib; nothing written")
        output = args.report.resolve()
        if output.exists():
            raise FileExistsError(f"refusing to overwrite report: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as handle:
            handle.write(payload)
        print(json.dumps({"status": report["status"], "counts": report["counts"], "report": str(output)}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, sqlite3.Error, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())



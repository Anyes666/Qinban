from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .common import HarnessError, load_json_strict, now_local_iso, sha256_file, write_json_once


PREFERRED_IDS = ["495", "516", "330", "035", "502", "719", "377", "851", "623", "809"]


def _hash_or_none(path: Path) -> str | None:
    return sha256_file(path) if path.is_file() else None


def audit(workspace: Path, output: Path) -> dict[str, Any]:
    repo = workspace / "AutoMidiPlayer"
    discovery = repo / "catalog-intake" / "discovery" / "2026-10-05-pop909"
    parsed_path = discovery / "parsed" / "candidates.json"
    review_path = discovery / "discovery-review.json"
    candidates_doc = load_json_strict(parsed_path)
    review_doc = load_json_strict(review_path)
    rows = candidates_doc.get("candidates", [])
    by_id = {str(row.get("sourceIndexId")).zfill(3): row for row in rows}
    selected: list[dict[str, Any]] = []
    for source_id in PREFERRED_IDS:
        row = by_id.get(source_id)
        if row is None:
            raise HarnessError("CANDIDATE_MISSING", source_id)
        selected.append({
            "candidateId": row["candidateId"],
            "sourceIndexId": row["sourceIndexId"],
            "title": row["title"],
            "artists": row["artists"],
            "metadataStatus": row["metadataStatus"],
            "languageStatus": row["languageStatus"],
            "notationStatus": row["notationStatus"],
            "completeWorkStatus": row["completeWorkStatus"],
            "usageStatus": row["usageStatus"],
            "musicReview": row["musicReview"],
            "gameReview": row["gameReview"],
            "metadataSource": row["metadataSource"],
            "notationCandidateDirectory": row["notationCandidateDirectory"],
            "admissibleNow": False,
            "blockingReasons": [
                "source index provides title/artist metadata only",
                "notation body was not acquired",
                "language/album/recording edition not stated by source",
                "complete-work, rights/scope, music and game review are not verified",
            ],
        })
    pilot = repo / "catalog-intake" / "public-score-pilot-2026-10-05"
    ready_manifest_path = pilot / "ready-import-manifest.json"
    ready_manifest = load_json_strict(ready_manifest_path)
    technical_records = []
    for record in ready_manifest.get("records", []):
        ready_path = pilot / Path(record["file"].replace("\\", "/"))
        source_path = pilot / "originals" / record["sourceMidi"]
        technical_records.append({
            "title": record["title"],
            "readyImportPath": str(ready_path),
            "readyImportSha256": _hash_or_none(ready_path),
            "sourceMidiPath": str(source_path),
            "sourceMidiSha256": _hash_or_none(source_path),
            "completeness": record.get("completeness"),
            "musicReview": record.get("musicReview"),
            "artistAndLanguageNotInferred": record.get("artistAndLanguageNotInferred"),
            "formalSong": False,
            "goldenSong": False,
            "admissibleFor20kTarget": False,
            "reason": "technical public-domain fixture only; completeness and human/game review remain unknown",
        })
    report = {
        "schemaVersion": 1,
        "reportType": "G1_SOURCE_CAPACITY_AUDIT",
        "createdAt": now_local_iso(),
        "scope": "read-only local audit; no network acquisition, no catalog/UserData writes",
        "sourceIndex": {
            "path": str(parsed_path),
            "sha256": sha256_file(parsed_path),
            "candidateRows": candidates_doc.get("candidateRows"),
            "distinctTitleArtistPairs": candidates_doc.get("distinctTitleArtistPairs"),
            "realScoresObtained": candidates_doc.get("realScoresObtained"),
            "formalSongsAdded": candidates_doc.get("formalSongsAdded"),
            "languagesInferred": candidates_doc.get("languagesInferred"),
        },
        "traceableCandidates": selected,
        "traceableCandidateCount": len(selected),
        "technicalSourcesAcquired": technical_records,
        "capacity": {
            "modernTargetScoreFilesAcquired": 0,
            "technicalPublicDomainScoreFilesAcquired": len(technical_records),
            "formallyAdmittedDistinctFullWorks": 0,
            "goldenReviewedWorks": 0,
            "bTierSourceVerifiedWorks": 0,
            "targetGapTo100Pilot": 100,
            "targetGapTo20000": 20000,
            "candidateDirectoryRowsNotCountedAsScores": candidates_doc.get("candidateRows", 0),
            "variantsFragmentsMetadataOnlyNotCounted": True,
        },
        "g1Gate": "PARTIAL_BLOCKED_SOURCE_CAPACITY",
        "blockingFindings": [
            "The 10 traceable POP909 rows are metadata candidates, not acquired notation.",
            "The two acquired public-domain fixtures are technical validation material, not modern popular-song capacity.",
            "No source in this audit proves full-work completeness, rights/scope for bundling, human music review, or game review.",
            "Current trending/chart coverage is not claimed.",
        ],
        "existingReviewReference": {
            "path": str(review_path),
            "sha256": sha256_file(review_path),
            "requestedTitleCandidates": list(review_doc.get("requestedTitleCandidates", {}).keys()),
        },
        "protectedActions": {
            "songsWritten": 0,
            "userDataWritten": 0,
            "downloads": 0,
            "nativeKeySendAttempts": 0,
            "formalApprovalsCreatedByWorker": 0,
        },
    }
    try:
        output.relative_to((repo / ".validation").resolve())
    except ValueError as exc:
        raise HarnessError("AUDIT_OUTPUT_OUTSIDE_RUN", str(output)) from exc
    write_json_once(output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only G1 source-capacity audit")
    parser.add_argument("--workspace", default=str(Path(__file__).resolve().parents[3]))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        report = audit(Path(args.workspace).resolve(), Path(args.output).resolve())
        print(json.dumps({"status": "PASS", "traceableCandidates": report["traceableCandidateCount"], "modernTargetScoreFilesAcquired": report["capacity"]["modernTargetScoreFilesAcquired"], "output": args.output}, ensure_ascii=False))
        return 0
    except HarnessError as exc:
        print(json.dumps({"status": "ERROR", "error": exc.code, "message": exc.message}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

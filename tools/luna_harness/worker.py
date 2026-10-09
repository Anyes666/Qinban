from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .common import HarnessError, assert_schema, load_json_strict, now_local_iso, relative_posix, sha256_file, write_json_once


def build_result(task: dict, report_rel: str, report_sha: str, *, quarantined: bool, elapsed_ms: float) -> dict:
    if quarantined:
        status = "QUARANTINED"
        stage = "NONE"
        stop = [{"code": "SOURCE_NOT_ACQUIRED", "message": "No source score was acquired; deterministic G0 worker will not infer notes from title or metadata."}]
        warnings = ["This is a source-capacity/control result, not a music-quality approval."]
    else:
        status = "SUCCEEDED"
        stage = "SOURCE_FOUND"
        stop = []
        warnings = ["Worker completion is not human music review, game review, rights approval, or formal catalog admission."]
    result = {
        "schemaVersion": 1,
        "taskId": task["taskId"],
        "batchId": task["batchId"],
        "dataKind": task["dataKind"],
        "inputSnapshotSha256": task["inputSnapshotSha256"],
        "policySha256": task["policySha256"],
        "status": status,
        "lastCompletedStage": stage,
        "formalAcceptanceClaim": False,
        "qualityStates": {
            "identity": "candidate" if not quarantined else "unknown",
            "sourceTiming": "not_checked",
            "scope": "not_reviewed",
            "completeness": "unknown",
            "musicReview": "not_reviewed_by_worker",
            "gameReview": "not_tested_by_worker",
        },
        "artifacts": [{"kind": "task_log", "path": report_rel, "sha256": report_sha}],
        "validations": [{"checkId": "worker_no_native_input", "status": "PASS", "reportPath": report_rel, "reportSha256": report_sha, "exitCode": 0, "nativeKeySendAttempts": 0}],
        "metrics": {"sourceNotes": 0, "normalizedNotes": 0, "maxTimingErrorMs": None, "elapsedMs": elapsed_ms},
        "stopReasons": stop,
        "warnings": warnings,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic offline Luna harness worker")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    try:
        run_root = Path(args.run_root).resolve(strict=True)
        task_path = Path(args.task).resolve(strict=True)
        result_path = Path(args.result).resolve()
        output_root = Path(args.output_root).resolve(strict=True)
        task = load_json_strict(task_path)
        assert_schema(task, run_root.parents[2] / "catalog-intake" / "luna-harness-v1" / "task.schema.json", "TASK_SCHEMA_INVALID")
        if result_path.exists():
            raise HarnessError("RESULT_EXISTS", str(result_path))
        output_root.mkdir(parents=True, exist_ok=True)
        report = {
            "schemaVersion": 1,
            "worker": "luna_harness.worker",
            "taskId": task["taskId"],
            "batchId": task["batchId"],
            "createdAt": now_local_iso(),
            "offline": True,
            "nativeKeySendAttempts": 0,
            "externalCalls": 0,
            "liveCatalogWrites": 0,
            "inputArtifactCount": len(task["inputArtifacts"]),
            "decision": "QUARANTINED_SOURCE_NOT_ACQUIRED" if task["dataKind"] == "candidate_score" else "CONTROL_TASK_COMPLETED",
            "notesGenerated": 0,
            "formalAcceptanceClaim": False,
        }
        report_path = output_root / "worker-report.json"
        write_json_once(report_path, report)
        report_rel = relative_posix(report_path, run_root)
        result = build_result(task, report_rel, sha256_file(report_path), quarantined=task["dataKind"] == "candidate_score", elapsed_ms=round((time.perf_counter() - started) * 1000, 3))
        schema_path = run_root.parents[2] / "catalog-intake" / "luna-harness-v1" / "result.schema.json"
        assert_schema(result, schema_path, "RESULT_SCHEMA_INVALID")
        write_json_once(result_path, result)
        return 0
    except HarnessError as exc:
        print(json.dumps({"error": exc.code, "message": exc.message}, ensure_ascii=False), flush=True)
        return 2
    except Exception as exc:  # never silently convert an unexpected worker error to success
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False), flush=True)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())


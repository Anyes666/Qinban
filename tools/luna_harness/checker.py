from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .common import (
    HarnessError,
    assert_schema,
    canonical_input_snapshot,
    contract_hashes,
    ensure_safe_relative,
    is_reparse_point,
    load_json_strict,
    now_local_iso,
    relative_posix,
    resolve_contained,
    sha256_bytes,
    sha256_file,
    write_json_once,
)


def _check(report: dict[str, Any], check_id: str, passed: bool, details: Any = None) -> None:
    report["checks"].append({"checkId": check_id, "status": "PASS" if passed else "FAIL", "details": details})
    if not passed:
        report["failedChecks"] += 1


def _fail(report: dict[str, Any], check_id: str, exc: Exception) -> None:
    _check(report, check_id, False, {"error": getattr(exc, "code", type(exc).__name__), "message": str(exc)})


def _verify_baseline(report: dict[str, Any], manifest: dict[str, Any], contract_root: Path) -> None:
    baseline_path = contract_root / "baseline.json"
    if not baseline_path.is_file():
        _check(report, "protected_baseline", True, "no baseline configured")
        return
    baseline = load_json_strict(baseline_path)
    changed: list[str] = []
    checked = 0
    for raw_path, expected in baseline.get("protectedFileHashes", {}).items():
        checked += 1
        path = Path(raw_path)
        try:
            actual = sha256_file(path)
        except OSError:
            actual = None
        if actual != str(expected).upper():
            changed.append(str(path))
    runtime = Path(baseline.get("runtime", ""))
    for relative, expected in baseline.get("runtimeSongFileHashes", {}).items():
        checked += 1
        path = runtime / "Songs" / relative
        try:
            actual = sha256_file(path)
        except OSError:
            actual = None
        if actual != str(expected).upper():
            changed.append(str(path))
    _check(report, "protected_baseline", not changed, {"checked": checked, "changed": changed})


def _verify_checkpoints(report: dict[str, Any], run_root: Path) -> None:
    previous = None
    expected_sequence = 1
    for path in sorted((run_root / "checkpoints").glob("checkpoint-*.json")):
        try:
            value = load_json_strict(path)
            passed = value.get("sequence") == expected_sequence and value.get("previousSha256") == previous
            _check(report, f"checkpoint_{expected_sequence:06d}", passed, {"path": relative_posix(path, run_root), "event": value.get("event")})
            previous = sha256_file(path)
            expected_sequence += 1
        except Exception as exc:
            _fail(report, f"checkpoint_{expected_sequence:06d}", exc)
            break
    _check(report, "checkpoint_chain_nonempty", expected_sequence > 1, {"count": expected_sequence - 1})


def _verify_task(report: dict[str, Any], run_root: Path, task_dir: Path, manifest: dict[str, Any], contract_root: Path) -> None:
    task_path = task_dir / "task.json"
    state_path = task_dir / "state.json"
    receipt_path = task_dir / "submission-receipt.json"
    task_id = task_dir.name
    try:
        task = load_json_strict(task_path)
        assert_schema(task, contract_root / "task.schema.json", "TASK_SCHEMA_INVALID")
        _check(report, f"task_{task_id}_schema", True)
        if task["policySha256"].upper() != manifest["policySha256"]:
            raise HarnessError("POLICY_HASH_MISMATCH", "task policy hash differs from run manifest")
        actual_artifacts = []
        for artifact in task["inputArtifacts"]:
            path = resolve_contained(Path(manifest["workspaceRoot"]), artifact["path"], label=f"task {task_id} input", must_exist=True)
            actual = sha256_file(path)
            if actual != artifact["sha256"].upper():
                raise HarnessError("INPUT_HASH_MISMATCH", artifact["path"])
            actual_artifacts.append({"kind": artifact["kind"], "path": artifact["path"], "sha256": actual})
        snapshot = sha256_bytes(json.dumps(canonical_input_snapshot(task, actual_artifacts), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8"))
        if snapshot != task["inputSnapshotSha256"].upper():
            raise HarnessError("INPUT_SNAPSHOT_MISMATCH", task_id)
        _check(report, f"task_{task_id}_input_hashes", True, {"count": len(actual_artifacts)})
        receipt = load_json_strict(receipt_path)
        if receipt["taskSha256"].upper() != sha256_file(task_path) or receipt["inputSnapshotSha256"].upper() != task["inputSnapshotSha256"].upper():
            raise HarnessError("SUBMISSION_RECEIPT_BINDING", task_id)
        _check(report, f"task_{task_id}_submission_receipt", True)
        state = load_json_strict(state_path)
        status = state["status"]
        _check(report, f"task_{task_id}_state", status in {"QUEUED", "RUNNING", "RETRYABLE_FAILURE", "SUCCEEDED", "QUARANTINED", "FAILED", "BLOCKED", "CANCELLED"}, status)
        if status in {"SUCCEEDED", "QUARANTINED"}:
            _verify_result(report, run_root, task, state, manifest, contract_root)
    except Exception as exc:
        _fail(report, f"task_{task_id}", exc)

def _verify_result(report: dict[str, Any], run_root: Path, task: dict[str, Any], state: dict[str, Any], manifest: dict[str, Any], contract_root: Path) -> None:
    result_rel = state.get("resultPath")
    if not isinstance(result_rel, str):
        raise HarnessError("RESULT_PATH_MISSING", task["taskId"])
    result_path = resolve_contained(run_root, result_rel, label=f"result {task['taskId']}", must_exist=True)
    result = load_json_strict(result_path)
    assert_schema(result, contract_root / "result.schema.json", "RESULT_SCHEMA_INVALID")
    if result["taskId"] != task["taskId"] or result["batchId"] != task["batchId"] or result["dataKind"] != task["dataKind"]:
        raise HarnessError("RESULT_BINDING", task["taskId"])
    if result["policySha256"].upper() != task["policySha256"].upper() or result["inputSnapshotSha256"].upper() != task["inputSnapshotSha256"].upper():
        raise HarnessError("RESULT_HASH_BINDING", task["taskId"])
    if result["formalAcceptanceClaim"] is not False:
        raise HarnessError("FORMAL_ACCEPTANCE_FORBIDDEN", task["taskId"])
    for artifact in result["artifacts"]:
        path = resolve_contained(run_root, artifact["path"], label="result artifact", must_exist=True)
        if sha256_file(path) != artifact["sha256"].upper():
            raise HarnessError("RESULT_ARTIFACT_HASH", artifact["path"])
    for validation in result["validations"]:
        if validation["nativeKeySendAttempts"] != 0:
            raise HarnessError("NATIVE_INPUT_NONZERO", validation["checkId"])
        if validation["status"] == "PASS":
            if validation["exitCode"] != 0 or validation["reportPath"] is None or validation["reportSha256"] is None:
                raise HarnessError("FAKE_PASS", validation["checkId"])
            path = resolve_contained(run_root, validation["reportPath"], label="validation report", must_exist=True)
            if sha256_file(path) != validation["reportSha256"].upper():
                raise HarnessError("VALIDATION_REPORT_HASH", validation["checkId"])
    if result["status"] == "SUCCEEDED" and (not result["validations"] or any(x["status"] != "PASS" for x in result["validations"])):
        raise HarnessError("SUCCESS_WITHOUT_GATES", task["taskId"])
    if result["status"] != "SUCCEEDED" and not result["stopReasons"]:
        raise HarnessError("NON_SUCCESS_WITHOUT_REASON", task["taskId"])
    attempt_root = result_path.parent
    worker = load_json_strict(attempt_root / "worker-report.json")
    if worker.get("nativeKeySendAttempts") != 0 or worker.get("externalCalls") != 0 or worker.get("liveCatalogWrites") != 0:
        raise HarnessError("WORKER_SIDE_EFFECTS", task["taskId"])
    child = load_json_strict(attempt_root / "child-receipt.json")
    if child.get("allowlisted") is not True or child.get("exitCode") != 0:
        raise HarnessError("CHILD_RECEIPT_INVALID", task["taskId"])
    expected = [
        str(Path(manifest["worker"]["pythonExecutable"]).resolve()), "-m", "luna_harness.worker",
        "--run-root", str(run_root), "--task", str(task_path := task_path_for(run_root, task["taskId"])),
        "--result", str(result_path), "--output-root", str(attempt_root),
    ]
    actual = child.get("command")
    if not isinstance(actual, list) or len(actual) != len(expected):
        raise HarnessError("COMMAND_NOT_ALLOWLISTED", task["taskId"])
    for index, (left, right) in enumerate(zip(actual, expected)):
        if index == 0:
            if os.path.normcase(str(left)) != os.path.normcase(str(right)):
                raise HarnessError("COMMAND_NOT_ALLOWLISTED", task["taskId"])
        elif str(left) != str(right):
            raise HarnessError("COMMAND_NOT_ALLOWLISTED", task["taskId"])
    _check(report, f"task_{task['taskId']}_result", True, {"status": result["status"], "validations": len(result["validations"])})


def task_path_for(run_root: Path, task_id: str) -> Path:
    path = run_root / "tasks" / task_id / "task.json"
    if not path.is_file():
        raise HarnessError("TASK_NOT_FOUND", task_id)
    return path


def check_run(run_root: Path, output: Path | None = None) -> tuple[bool, dict[str, Any], Path | None]:
    run_root = run_root.resolve(strict=True)
    manifest = load_json_strict(run_root / "manifest.json")
    contract_root = Path(manifest["contractRoot"]).resolve(strict=True)
    report: dict[str, Any] = {"schemaVersion": 1, "checkedAt": now_local_iso(), "runId": manifest.get("runId"), "runRoot": str(run_root), "checks": [], "failedChecks": 0}
    try:
        hashes = contract_hashes(contract_root)
        _check(report, "manifest_policy_hash", hashes["policySha256"] == manifest["policySha256"], hashes)
        _check(report, "manifest_task_schema_hash", hashes["taskSchemaSha256"] == manifest["taskSchemaSha256"])
        _check(report, "manifest_result_schema_hash", hashes["resultSchemaSha256"] == manifest["resultSchemaSha256"])
        _check(report, "run_root_is_not_reparse", not is_reparse_point(run_root))
        _verify_baseline(report, manifest, contract_root)
        _verify_checkpoints(report, run_root)
        required_gates = set(load_json_strict(contract_root / "policy.json").get("gates", []))
        _check(report, "all_required_gates_present", required_gates.issubset(set(manifest.get("gates", {}))), {"required": sorted(required_gates), "present": sorted(manifest.get("gates", {}))})
        for task_dir in sorted((run_root / "tasks").iterdir(), key=lambda p: p.name):
            if task_dir.is_dir():
                _verify_task(report, run_root, task_dir, manifest, contract_root)
    except Exception as exc:
        _fail(report, "checker_fatal", exc)
    report["status"] = "PASS" if report["failedChecks"] == 0 else "FAIL"
    report["taskCount"] = sum(1 for p in (run_root / "tasks").iterdir() if p.is_dir())
    report_path: Path | None = None
    if output is not None:
        output = output.resolve()
        try:
            output.relative_to(run_root)
        except ValueError as exc:
            raise HarnessError("CHECK_REPORT_OUTSIDE_RUN", str(output)) from exc
        write_json_once(output, report)
        report_path = output
    return report["status"] == "PASS", report, report_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Independent Luna harness checker")
    parser.add_argument("run_root")
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        passed, report, path = check_run(Path(args.run_root), Path(args.output) if args.output else None)
        print(json.dumps({"status": report["status"], "failedChecks": report["failedChecks"], "report": str(path) if path else None}, ensure_ascii=False))
        return 0 if passed else 1
    except HarnessError as exc:
        print(json.dumps({"status": "ERROR", "error": exc.code, "message": exc.message}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


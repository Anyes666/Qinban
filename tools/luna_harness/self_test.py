from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .checker import check_run
from .common import HarnessError, atomic_write_json, load_json_strict, sha256_file, write_json_once
from .controller import HarnessConfig, HarnessController


def _metadata(title: str = "fixture") -> dict[str, Any]:
    return {"title": title, "artists": [], "languages": [], "version": None, "identityStatus": "candidate", "evidencePaths": []}


def _write_task(path: Path, task: dict[str, Any]) -> None:
    write_json_once(path, task)


def run_self_test(output: Path | None = None) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []

    def case(name: str, fn, *, allow_skip: bool = False) -> None:
        try:
            details = fn()
            cases.append({"name": name, "status": "PASS", "details": details})
        except _Skip as exc:
            if allow_skip:
                cases.append({"name": name, "status": "SKIP", "details": str(exc)})
            else:
                cases.append({"name": name, "status": "FAIL", "details": str(exc)})
        except Exception as exc:
            cases.append({"name": name, "status": "FAIL", "details": {"type": type(exc).__name__, "message": str(exc)}})

    with tempfile.TemporaryDirectory(prefix="luna-g0-") as raw:
        temp = Path(raw)
        workspace = temp / "workspace"
        repo = workspace / "AutoMidiPlayer"
        repo.mkdir(parents=True)
        actual_repo = Path(__file__).resolve().parents[2]
        shutil.copytree(actual_repo / "tools" / "luna_harness", repo / "tools" / "luna_harness")
        contract = repo / "catalog-intake" / "luna-harness-v1"
        contract.mkdir(parents=True)
        for name in ("policy.json", "task.schema.json", "result.schema.json"):
            shutil.copy2(actual_repo / "catalog-intake" / "luna-harness-v1" / name, contract / name)
        fixture = repo / "catalog-intake" / "fixture.json"
        fixture.write_text('{"fixture":true,"notes":[]}', encoding="utf-8")
        cfg = HarnessConfig(workspace, repo, contract, repo / ".validation" / "luna-score-runs", None, False, {"freeDiskGiB": 100, "freeRamGiB": 8})
        controller = HarnessController.create(cfg, run_id="selftest-positive")
        task = controller.build_task(task_id="task-positive", batch_id="batch-g0", action="batch_audit", data_kind="control_task", metadata=_metadata(), artifacts=[{"kind": "test_report", "path": "AutoMidiPlayer/catalog-intake/fixture.json"}])
        task_file = temp / "task-positive.json"
        _write_task(task_file, task)

        def positive_run():
            controller.submit_task_file(task_file)
            state = controller.run_task("task-positive")
            if state["status"] != "SUCCEEDED":
                raise AssertionError(state)
            passed, report, _ = check_run(controller.run_root)
            if not passed:
                raise AssertionError(report)
            return {"state": state["status"], "checkerFailed": report["failedChecks"]}
        case("positive_run_and_independent_checker", positive_run)

        def duplicate_submission():
            try:
                controller.submit_task_file(task_file)
            except HarnessError as exc:
                if exc.code == "TASK_EXISTS":
                    return exc.code
                raise
            raise AssertionError("duplicate task was accepted")
        case("duplicate_task_rejected", duplicate_submission)

        def fake_pass_rejected():
            result_path = controller.run_root / controller._load_state("task-positive")["resultPath"]
            data = load_json_strict(result_path)
            data["validations"][0]["nativeKeySendAttempts"] = 1
            atomic_write_json(result_path, data)
            passed, report, _ = check_run(controller.run_root)
            if passed or report["failedChecks"] == 0:
                raise AssertionError("checker accepted tampered native-input evidence")
            return {"failedChecks": report["failedChecks"]}
        case("native_input_tamper_rejected", fake_pass_rejected)

        def bad_hash_rejected():
            bad = dict(task)
            bad["taskId"] = "task-bad-hash"
            bad["outputRoot"] = "batches/batch-g0/tasks/task-bad-hash"
            bad["inputArtifacts"] = [dict(task["inputArtifacts"][0], sha256="0" * 64)]
            bad_file = temp / "task-bad-hash.json"
            _write_task(bad_file, bad)
            try:
                controller.submit_task_file(bad_file)
            except HarnessError as exc:
                if exc.code == "INPUT_HASH_MISMATCH":
                    return exc.code
                raise
            raise AssertionError("bad input hash was accepted")
        case("bad_input_hash_rejected", bad_hash_rejected)

        def forged_approval_rejected():
            bad = dict(task)
            bad["taskId"] = "task-approval"
            bad["reviewAuthority"] = "human-approved"
            bad_file = temp / "task-approval.json"
            _write_task(bad_file, bad)
            try:
                controller.submit_task_file(bad_file)
            except HarnessError as exc:
                if exc.code == "TASK_SCHEMA_INVALID":
                    return exc.code
                raise
            raise AssertionError("forged approval was accepted")
        case("worker_cannot_create_human_approval", forged_approval_rejected)

        def path_traversal_rejected():
            bad = dict(task)
            bad["taskId"] = "task-path"
            bad["outputRoot"] = "../../Songs"
            bad_file = temp / "task-path.json"
            _write_task(bad_file, bad)
            try:
                controller.submit_task_file(bad_file)
            except HarnessError as exc:
                if exc.code == "TASK_SCHEMA_INVALID":
                    return exc.code
                raise
            raise AssertionError("path traversal was accepted")
        case("path_traversal_rejected", path_traversal_rejected)

        def resource_pause_rejected():
            limited_cfg = HarnessConfig(workspace, repo, contract, repo / ".validation" / "luna-score-runs", None, False, {"freeDiskGiB": 1, "freeRamGiB": 1})
            limited = HarnessController.create(limited_cfg, run_id="selftest-resource")
            limited_task = limited.build_task(task_id="task-resource", batch_id="batch-g0", action="batch_audit", data_kind="control_task", metadata=_metadata(), artifacts=[])
            limited_file = temp / "task-resource.json"
            _write_task(limited_file, limited_task)
            limited.submit_task_file(limited_file)
            try:
                limited.run_task("task-resource")
            except HarnessError as exc:
                if exc.code == "RESOURCE_PAUSE":
                    return exc.code
                raise
            raise AssertionError("resource pause was not enforced")
        case("resource_budget_pause", resource_pause_rejected)

        def lease_recovery():
            recovery = HarnessController.create(cfg, run_id="selftest-recovery")
            recovery_task = recovery.build_task(task_id="task-recovery", batch_id="batch-g0", action="batch_audit", data_kind="control_task", metadata=_metadata(), artifacts=[])
            recovery_file = temp / "task-recovery.json"
            _write_task(recovery_file, recovery_task)
            recovery.submit_task_file(recovery_file)
            lease = recovery._task_dir("task-recovery") / "lease-attempt-1.json"
            write_json_once(lease, {"schemaVersion": 1, "taskId": "task-recovery", "attempt": 1, "pid": 999999, "startedEpoch": 0})
            try:
                recovery.run_task("task-recovery")
            except HarnessError as exc:
                if exc.code != "LEASE_CONFLICT":
                    raise
            else:
                raise AssertionError("active lease was ignored")
            state = recovery.run_task("task-recovery", recover=True)
            if state["status"] != "SUCCEEDED":
                raise AssertionError(state)
            return {"state": state["status"], "recovered": True}
        case("orphaned_lease_recovery", lease_recovery)

        def symlink_rejected():
            outside = temp / "outside-dir"
            outside.mkdir()
            (outside / "payload.txt").write_text("outside", encoding="utf-8")
            link = repo / "catalog-intake" / "link-dir"
            try:
                os.symlink(outside, link, target_is_directory=True)
            except (OSError, NotImplementedError):
                completed = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True, text=True, check=False)
                if completed.returncode != 0:
                    raise _Skip(f"symlink/junction creation unavailable: {completed.stderr or completed.stdout}")
            try:
                controller.build_task(task_id="task-link", batch_id="batch-g0", action="batch_audit", data_kind="control_task", metadata=_metadata(), artifacts=[{"kind": "test_report", "path": "AutoMidiPlayer/catalog-intake/link-dir/payload.txt"}])
            except HarnessError as exc:
                if exc.code in {"REPARSE_COMPONENT", "PATH_RESOLVE_FAILED", "PATH_OUTSIDE_ROOT"}:
                    return exc.code
                raise
            raise AssertionError("symlink/junction boundary was accepted")
        case("symlink_boundary_rejected", symlink_rejected, allow_skip=True)

        summary = {
            "schemaVersion": 1,
            "reportType": "G0_HARNESS_SELF_TEST",
            "status": "PASS" if all(item["status"] in {"PASS", "SKIP"} for item in cases) else "FAIL",
            "createdAt": controller.manifest["createdAt"],
            "cases": cases,
            "passedCases": sum(item["status"] == "PASS" for item in cases),
            "skippedCases": sum(item["status"] == "SKIP" for item in cases),
            "failedCases": sum(item["status"] == "FAIL" for item in cases),
            "nativeKeySendAttempts": 0,
            "scoresDownloadedOrGenerated": 0,
            "liveCatalogWrites": 0,
            "boundary": "G0 control fixtures only; no musical correctness, human review, game review, deployment, or model success claim.",
        }
    if output is not None:
        write_json_once(output, summary)
    return summary


class _Skip(Exception):
    pass


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="G0 deterministic harness negative/positive self-test")
    parser.add_argument("--output")
    args = parser.parse_args()
    summary = run_self_test(Path(args.output).resolve() if args.output else None)
    print(json.dumps({"status": summary["status"], "passedCases": summary["passedCases"], "skippedCases": summary["skippedCases"], "failedCases": summary["failedCases"], "output": args.output}, ensure_ascii=False))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

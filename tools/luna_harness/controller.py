from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

from . import __version__
from .common import (
    HarnessError,
    SAFE_ID,
    assert_schema,
    atomic_write_json,
    canonical_input_snapshot,
    contract_hashes,
    is_reparse_point,
    load_json_strict,
    now_local_iso,
    pid_is_alive,
    relative_posix,
    resolve_contained,
    sha256_bytes,
    sha256_file,
    write_json_once,
)


@dataclass(frozen=True)
class HarnessConfig:
    workspace_root: Path
    repository_root: Path
    contract_root: Path
    runs_root: Path
    baseline_path: Path | None
    verify_baseline: bool = True
    resource_overrides: Mapping[str, float] | None = None

    @classmethod
    def from_repository(cls, repository_root: Path | None = None) -> "HarnessConfig":
        repo = (repository_root or Path(__file__).resolve().parents[2]).resolve()
        workspace = repo.parent
        contract = repo / "catalog-intake" / "luna-harness-v1"
        return cls(workspace, repo, contract, repo / ".validation" / "luna-score-runs", contract / "baseline.json")


TERMINAL_STATES = {"SUCCEEDED", "QUARANTINED", "BLOCKED", "FAILED", "CANCELLED"}


class HarnessController:
    """Single-controller deterministic-worker harness.

    This is not an OS sandbox.  It is the required fallback when restricted
    production agents are unavailable: strict paths/hashes, one writer, exact
    worker command, immutable evidence, leases, and an independent checker.
    """

    def __init__(self, config: HarnessConfig, run_root: Path, manifest: dict[str, Any]):
        self.config = config
        self.run_root = run_root.resolve()
        self.manifest = manifest
        self.policy = load_json_strict(config.contract_root / "policy.json")
        self.task_schema_path = config.contract_root / "task.schema.json"
        self.result_schema_path = config.contract_root / "result.schema.json"
        self.baseline = load_json_strict(config.baseline_path) if config.baseline_path and config.baseline_path.is_file() else None

    @classmethod
    def create(cls, config: HarnessConfig | None = None, *, run_id: str | None = None) -> "HarnessController":
        raw_cfg = config or HarnessConfig.from_repository()
        cfg = HarnessConfig(raw_cfg.workspace_root.resolve(), raw_cfg.repository_root.resolve(), raw_cfg.contract_root.resolve(), raw_cfg.runs_root.resolve(), raw_cfg.baseline_path.resolve() if raw_cfg.baseline_path else None, raw_cfg.verify_baseline, raw_cfg.resource_overrides)
        cfg.runs_root.mkdir(parents=True, exist_ok=True)
        if is_reparse_point(cfg.runs_root):
            raise HarnessError("REPARSE_RUNS_ROOT", f"runs root is a symlink/junction: {cfg.runs_root}")
        if run_id is None:
            run_id = time.strftime("%Y%m%dT%H%M%S", time.localtime()) + "-" + uuid.uuid4().hex[:8]
        if not SAFE_ID.fullmatch(run_id):
            raise HarnessError("BAD_RUN_ID", run_id)
        run_root = cfg.runs_root / run_id
        try:
            run_root.mkdir(parents=False, exist_ok=False)
            for name in ("tasks", "batches", "checkpoints", "reports"):
                (run_root / name).mkdir()
        except FileExistsError as exc:
            raise HarnessError("RUN_EXISTS", f"refusing to reuse run directory: {run_root}") from exc
        baseline = cls._verify_live_baseline(cfg)
        write_json_once(run_root / "baseline-check.json", baseline)
        if cfg.verify_baseline and not baseline["passed"]:
            raise HarnessError("BASELINE_CHANGED", f"protected baseline differs; see {run_root / 'baseline-check.json'}")
        hashes = contract_hashes(cfg.contract_root)
        manifest = {
            "schemaVersion": 1,
            "controllerVersion": __version__,
            "runId": run_id,
            "createdAt": now_local_iso(),
            "status": "ACTIVE",
            "runRoot": str(run_root),
            "workspaceRoot": str(cfg.workspace_root),
            "repositoryRoot": str(cfg.repository_root),
            "contractRoot": str(cfg.contract_root),
            "policySha256": hashes["policySha256"],
            "taskSchemaSha256": hashes["taskSchemaSha256"],
            "resultSchemaSha256": hashes["resultSchemaSha256"],
            "baselineCheckPath": "baseline-check.json",
            "baselineProtectedFilesChecked": baseline["protectedFilesChecked"],
            "baselinePolicySha256AtCapture": baseline.get("baselinePolicySha256"),
            "gates": {gate: "PENDING" for gate in cls._policy_gates(cfg.contract_root)},
            "execution": {
                "mode": "single-controller-and-deterministic-workers",
                "cloudAgents": 0,
                "cpuWorkers": 1,
                "gpuWorkers": 0,
                "catalogWriters": 1,
                "nativeKeySendAttempts": 0,
                "externalCalls": 0,
                "automaticDeployment": False,
            },
            "worker": {
                "module": "luna_harness.worker",
                "pythonExecutable": str(Path(sys.executable).resolve()),
                "network": "not-used-by-worker",
                "toolRestriction": "not-claimed-os-sandbox; deterministic fallback",
            },
        }
        write_json_once(run_root / "manifest.json", manifest)
        controller = cls(cfg, run_root, manifest)
        controller._checkpoint("RUN_CREATED", {"manifestSha256": sha256_file(run_root / "manifest.json")})
        return controller

    @classmethod
    def load(cls, run_root: Path, config: HarnessConfig | None = None) -> "HarnessController":
        cfg = config or HarnessConfig.from_repository()
        run_root = run_root.resolve()
        try:
            rel = run_root.relative_to(cfg.runs_root.resolve())
        except ValueError as exc:
            raise HarnessError("RUN_OUTSIDE_ROOT", str(run_root)) from exc
        resolve_contained(cfg.runs_root, rel, label="run root", must_exist=False)
        if not run_root.is_dir():
            raise HarnessError("RUN_NOT_DIRECTORY", str(run_root))
        manifest_path = run_root / "manifest.json"
        if not manifest_path.is_file():
            raise HarnessError("RUN_MANIFEST_MISSING", str(manifest_path))
        manifest = load_json_strict(manifest_path)
        if manifest.get("runRoot") != str(run_root):
            raise HarnessError("RUN_MANIFEST_BINDING", "manifest runRoot does not match selected run")
        return cls(cfg, run_root, manifest)

    @staticmethod
    def _policy_gates(contract_root: Path) -> list[str]:
        return list(load_json_strict(contract_root / "policy.json").get("gates", []))

    @staticmethod
    def _verify_live_baseline(config: HarnessConfig) -> dict[str, Any]:
        if not config.baseline_path or not config.baseline_path.is_file():
            return {"passed": True, "mode": "NO_BASELINE_CONFIGURED", "protectedFilesChecked": 0, "changed": [], "checkedAt": now_local_iso()}
        baseline = load_json_strict(config.baseline_path)
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
        return {
            "passed": not changed,
            "mode": "LIVE_HASH_RECHECK",
            "protectedFilesChecked": checked,
            "changed": changed,
            "checkedAt": now_local_iso(),
            "baselinePath": str(config.baseline_path),
            "baselinePolicySha256": baseline.get("policySha256"),
            "currentPolicySha256": contract_hashes(config.contract_root)["policySha256"],
        }

    def _checkpoint(self, event: str, data: Mapping[str, Any]) -> Path:
        directory = self.run_root / "checkpoints"
        existing = sorted(directory.glob("checkpoint-*.json"))
        previous = sha256_file(existing[-1]) if existing else None
        sequence = len(existing) + 1
        payload = {"schemaVersion": 1, "sequence": sequence, "event": event, "createdAt": now_local_iso(), "previousSha256": previous, "data": dict(data)}
        path = directory / f"checkpoint-{sequence:06d}.json"
        write_json_once(path, payload)
        return path

    def _update_manifest(self, **updates: Any) -> None:
        self.manifest.update(updates)
        atomic_write_json(self.run_root / "manifest.json", self.manifest)

    def mark_gate(self, gate: str, status: str, details: Mapping[str, Any] | None = None) -> None:
        gates = dict(self.manifest.get("gates", {}))
        if gate not in gates:
            raise HarnessError("UNKNOWN_GATE", gate)
        gates[gate] = status
        self._update_manifest(gates=gates)
        self._checkpoint("GATE_UPDATED", {"gate": gate, "status": status, "details": details or {}})

    # ---------- task validation and queue ----------

    def _task_dir(self, task_id: str) -> Path:
        if not SAFE_ID.fullmatch(task_id):
            raise HarnessError("BAD_TASK_ID", task_id)
        resolve_contained(self.run_root / "tasks", task_id, label="task directory", must_exist=False)
        return self.run_root / "tasks" / task_id

    def _load_task(self, task_id: str) -> dict[str, Any]:
        path = self._task_dir(task_id) / "task.json"
        if not path.is_file():
            raise HarnessError("TASK_NOT_FOUND", task_id)
        value = load_json_strict(path)
        assert_schema(value, self.task_schema_path, "TASK_SCHEMA_INVALID")
        return value

    def _load_state(self, task_id: str) -> dict[str, Any]:
        path = self._task_dir(task_id) / "state.json"
        if not path.is_file():
            raise HarnessError("TASK_STATE_MISSING", task_id)
        return load_json_strict(path)

    def _write_state(self, task_id: str, state: Mapping[str, Any]) -> None:
        atomic_write_json(self._task_dir(task_id) / "state.json", dict(state))

    def _approved_input_path(self, relative: str) -> Path:
        path = resolve_contained(self.config.workspace_root, relative, label="input artifact", must_exist=True)
        protected = [self.config.repository_root / "Songs"]
        runtime_raw = self.policy.get("paths", {}).get("runtime")
        if runtime_raw:
            protected.append(Path(runtime_raw))
        for root in protected:
            try:
                if path.is_relative_to(root.resolve()):
                    raise HarnessError("PROTECTED_INPUT", f"input artifact is inside protected runtime/catalog: {path}")
            except (OSError, ValueError):
                pass
        approved = [
            self.config.repository_root / "catalog-intake",
            self.config.repository_root / "tools",
            self.config.repository_root / ".validation",
            self.config.workspace_root / ".Codex",
        ]
        if not any(path.is_relative_to(root.resolve()) for root in approved if root.exists()):
            raise HarnessError("INPUT_ROOT_NOT_APPROVED", f"input artifact is outside approved read roots: {path}")
        return path

    def _resolve_output_root(self, task: Mapping[str, Any]) -> Path:
        rel = task["outputRoot"]
        expected = f"batches/{task['batchId']}/tasks/{task['taskId']}"
        if rel != expected:
            raise HarnessError("OUTPUT_ROOT_BINDING", f"outputRoot must be exactly {expected}")
        return resolve_contained(self.run_root, rel, label="task output root", must_exist=False)

    def _validate_task_semantics(self, task: Mapping[str, Any]) -> list[dict[str, str]]:
        assert_schema(task, self.task_schema_path, "TASK_SCHEMA_INVALID")
        hashes = contract_hashes(self.config.contract_root)
        if task["policySha256"].upper() != hashes["policySha256"]:
            raise HarnessError("POLICY_HASH_MISMATCH", "task policy hash is not current")
        if task["reviewAuthority"] != "none":
            raise HarnessError("REVIEW_AUTHORITY_FORBIDDEN", "worker tasks cannot carry human approval")
        if task["mayWriteLiveCatalog"] is not False:
            raise HarnessError("LIVE_CATALOG_WRITE_FORBIDDEN", "mayWriteLiveCatalog must be false")
        if task["budget"]["maxExternalCalls"] != 0:
            raise HarnessError("EXTERNAL_CALLS_FORBIDDEN", "G0 deterministic worker requires maxExternalCalls=0")
        if task["attempt"] != 1:
            raise HarnessError("INITIAL_ATTEMPT_REQUIRED", "new task must start at attempt 1")
        self._resolve_output_root(task)
        actual: list[dict[str, str]] = []
        for artifact in task["inputArtifacts"]:
            path = self._approved_input_path(artifact["path"])
            actual_hash = sha256_file(path)
            expected_hash = str(artifact["sha256"]).upper()
            if actual_hash != expected_hash:
                raise HarnessError("INPUT_HASH_MISMATCH", f"{artifact['path']}: expected {expected_hash}, got {actual_hash}")
            actual.append({"kind": artifact["kind"], "path": artifact["path"], "sha256": actual_hash})
        expected_snapshot = sha256_bytes(
            json.dumps(
                canonical_input_snapshot(task, actual),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        )
        if task["inputSnapshotSha256"].upper() != expected_snapshot:
            raise HarnessError("INPUT_SNAPSHOT_MISMATCH", "inputSnapshotSha256 does not bind current inputs")
        if task["metadata"]["identityStatus"] == "evidence_verified":
            for evidence in task["metadata"]["evidencePaths"]:
                self._approved_input_path(evidence)
        if task["dataKind"] == "candidate_score" and task["action"] in {"normalize", "instrument_validate"}:
            if not any(a["kind"] == "source_score" for a in task["inputArtifacts"]):
                raise HarnessError("SOURCE_SCORE_REQUIRED", "candidate score processing requires source_score")
        return actual

    def build_task(
        self,
        *,
        task_id: str,
        batch_id: str,
        action: str,
        data_kind: str,
        metadata: Mapping[str, Any],
        artifacts: Iterable[Mapping[str, str]],
        budget: Mapping[str, int] | None = None,
    ) -> dict[str, Any]:
        if not SAFE_ID.fullmatch(task_id) or not SAFE_ID.fullmatch(batch_id):
            raise HarnessError("BAD_TASK_ID", "taskId and batchId must use contract identifier format")
        actual: list[dict[str, str]] = []
        for item in artifacts:
            path = self._approved_input_path(item["path"])
            actual.append({"kind": item["kind"], "path": item["path"], "sha256": sha256_file(path)})
        task: dict[str, Any] = {
            "schemaVersion": 1,
            "taskId": task_id,
            "batchId": batch_id,
            "action": action,
            "dataKind": data_kind,
            "workId": None,
            "editionId": None,
            "metadata": dict(metadata),
            "inputArtifacts": actual,
            "outputRoot": f"batches/{batch_id}/tasks/{task_id}",
            "attempt": 1,
            "policySha256": contract_hashes(self.config.contract_root)["policySha256"],
            "inputSnapshotSha256": "0" * 64,
            "reviewAuthority": "none",
            "mayWriteLiveCatalog": False,
            "budget": dict(budget or {"wallTimeSeconds": 60, "maxExternalCalls": 0, "maxNewOutputMiB": 10}),
        }
        snapshot = canonical_input_snapshot(task, actual)
        task["inputSnapshotSha256"] = sha256_bytes(
            json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        )
        assert_schema(task, self.task_schema_path, "TASK_SCHEMA_INVALID")
        return task

    def submit_task_file(self, task_file: Path) -> dict[str, Any]:
        task = load_json_strict(task_file.resolve(strict=True))
        actual = self._validate_task_semantics(task)
        task_id = task["taskId"]
        task_dir = self._task_dir(task_id)
        try:
            task_dir.mkdir(parents=False, exist_ok=False)
        except FileExistsError as exc:
            raise HarnessError("TASK_EXISTS", f"refusing duplicate task submission: {task_id}") from exc
        stored = task_dir / "task.json"
        write_json_once(stored, task)
        receipt = {
            "schemaVersion": 1,
            "taskId": task_id,
            "batchId": task["batchId"],
            "submittedAt": now_local_iso(),
            "taskSha256": sha256_file(stored),
            "inputArtifacts": actual,
            "inputSnapshotSha256": task["inputSnapshotSha256"],
            "outputRoot": task["outputRoot"],
        }
        write_json_once(task_dir / "submission-receipt.json", receipt)
        write_json_once(
            task_dir / "state.json",
            {
                "schemaVersion": 1,
                "taskId": task_id,
                "status": "QUEUED",
                "nextAttempt": 1,
                "attempts": [],
                "resultPath": None,
                "error": None,
                "updatedAt": now_local_iso(),
            },
        )
        self._checkpoint("TASK_SUBMITTED", {"taskId": task_id, "taskSha256": receipt["taskSha256"]})
        return receipt

    def cancel_task(self, task_id: str, reason: str) -> dict[str, Any]:
        if not reason.strip():
            raise HarnessError("CANCEL_REASON_REQUIRED", "cancel reason is required")
        state = self._load_state(task_id)
        if state["status"] in TERMINAL_STATES:
            return state
        write_json_once(self._task_dir(task_id) / "cancel.json", {"schemaVersion": 1, "taskId": task_id, "cancelledAt": now_local_iso(), "reason": reason})
        state = dict(state)
        state.update({"status": "CANCELLED", "error": {"code": "CANCELLED", "message": reason}, "updatedAt": now_local_iso()})
        self._write_state(task_id, state)
        self._checkpoint("TASK_CANCELLED", {"taskId": task_id, "reason": reason})
        return state

    # ---------- execution ----------

    def _resource_admission(self, task: Mapping[str, Any]) -> dict[str, Any]:
        limits = self.policy["resourceBudgets"]
        disk_free = shutil.disk_usage(self.run_root).free / (1024**3)
        ram_free = None if psutil is None else psutil.virtual_memory().available / (1024**3)
        overrides = self.config.resource_overrides or {}
        disk_free = float(overrides.get("freeDiskGiB", disk_free))
        if ram_free is not None:
            ram_free = float(overrides.get("freeRamGiB", ram_free))
        admission = {
            "freeDiskGiB": round(disk_free, 3),
            "freeRamGiB": None if ram_free is None else round(ram_free, 3),
            "requiredFreeDiskGiB": limits["pauseAcquisitionBelowFreeDiskGiB"],
            "requiredFreeRamGiB": limits["pauseNewJobsBelowFreeRamGiB"],
            "passed": disk_free >= limits["pauseAcquisitionBelowFreeDiskGiB"] and (ram_free is None or ram_free >= limits["pauseNewJobsBelowFreeRamGiB"]),
        }
        if not admission["passed"]:
            raise HarnessError("RESOURCE_PAUSE", json.dumps(admission, ensure_ascii=False, sort_keys=True))
        return admission

    def _expected_command(self, task_path: Path, result_path: Path, output_root: Path) -> list[str]:
        return [
            str(Path(sys.executable).resolve()), "-m", "luna_harness.worker",
            "--run-root", str(self.run_root), "--task", str(task_path),
            "--result", str(result_path), "--output-root", str(output_root),
        ]

    @staticmethod
    def _same_command(actual: Any, expected: list[str]) -> bool:
        if not isinstance(actual, list) or len(actual) != len(expected):
            return False
        for index, (left, right) in enumerate(zip(actual, expected)):
            if index == 0:
                if os.path.normcase(str(left)) != os.path.normcase(str(right)):
                    return False
            elif str(left) != str(right):
                return False
        return True

    def _acquire_lease(self, task_id: str, attempt: int, *, recover: bool) -> tuple[Path, Path]:
        task_dir = self._task_dir(task_id)
        lease = task_dir / f"lease-attempt-{attempt}.json"
        release = task_dir / f"lease-release-attempt-{attempt}.json"
        if lease.exists() and not release.exists():
            old = load_json_strict(lease)
            age = time.time() - float(old.get("startedEpoch", time.time()))
            if not recover or (pid_is_alive(old.get("pid")) and age < 300):
                raise HarnessError("LEASE_CONFLICT", f"task attempt already leased: {task_id} attempt {attempt}")
            write_json_once(
                task_dir / f"lease-recovered-attempt-{attempt}.json",
                {"schemaVersion": 1, "taskId": task_id, "attempt": attempt, "recoveredAt": now_local_iso(), "reason": "orphaned_or_expired_lease", "previousLeaseSha256": sha256_file(lease)},
            )
            lease = task_dir / f"lease-attempt-{attempt}-recovered.json"
            release = task_dir / f"lease-release-attempt-{attempt}-recovered.json"
        if lease.exists() and release.exists():
            raise HarnessError("ATTEMPT_EVIDENCE_EXISTS", f"attempt evidence already exists: {lease}")
        write_json_once(lease, {"schemaVersion": 1, "taskId": task_id, "attempt": attempt, "pid": os.getpid(), "startedEpoch": time.time(), "startedAt": now_local_iso()})
        return lease, release

    def _release_lease(self, task_id: str, attempt: int, release: Path, *, exit_code: int | None, status: str) -> None:
        write_json_once(release, {"schemaVersion": 1, "taskId": task_id, "attempt": attempt, "releasedAt": now_local_iso(), "exitCode": exit_code, "status": status})

    def _validate_result(self, task: Mapping[str, Any], result_path: Path, attempt_root: Path, exit_code: int) -> dict[str, Any]:
        if not result_path.is_file():
            raise HarnessError("RESULT_MISSING", str(result_path))
        result = load_json_strict(result_path)
        assert_schema(result, self.result_schema_path, "RESULT_SCHEMA_INVALID")
        for field in ("taskId", "batchId", "dataKind", "policySha256", "inputSnapshotSha256"):
            expected = task[field].upper() if field.endswith("Sha256") else task[field]
            if result[field] != expected:
                raise HarnessError("RESULT_BINDING", f"result {field} does not match task")
        if result["formalAcceptanceClaim"] is not False:
            raise HarnessError("FORMAL_ACCEPTANCE_FORBIDDEN", "worker result cannot claim formal acceptance")
        for artifact in result["artifacts"]:
            rel = artifact["path"]
            path = resolve_contained(self.run_root, rel, label="result artifact", must_exist=True)
            if sha256_file(path) != str(artifact["sha256"]).upper():
                raise HarnessError("RESULT_ARTIFACT_HASH", f"hash mismatch: {rel}")
        for validation in result["validations"]:
            if validation["nativeKeySendAttempts"] != 0:
                raise HarnessError("NATIVE_INPUT_NONZERO", f"validation {validation['checkId']} reports native input")
            if validation["status"] == "PASS":
                if validation["exitCode"] != 0 or validation["reportPath"] is None or validation["reportSha256"] is None:
                    raise HarnessError("FAKE_PASS", f"validation {validation['checkId']} has incomplete PASS evidence")
                report = resolve_contained(self.run_root, validation["reportPath"], label="validation report", must_exist=True)
                if sha256_file(report) != str(validation["reportSha256"]).upper():
                    raise HarnessError("VALIDATION_REPORT_HASH", f"validation report hash mismatch: {validation['reportPath']}")
        if result["status"] == "SUCCEEDED":
            if not result["validations"] or any(v["status"] != "PASS" for v in result["validations"]):
                raise HarnessError("SUCCESS_WITHOUT_GATES", "SUCCEEDED requires all validations PASS")
            if result["stopReasons"]:
                raise HarnessError("SUCCESS_WITH_STOP_REASON", "SUCCEEDED cannot contain stopReasons")
        elif not result["stopReasons"]:
            raise HarnessError("NON_SUCCESS_WITHOUT_REASON", "non-success result requires stopReasons")
        worker_report = attempt_root / "worker-report.json"
        if not worker_report.is_file():
            raise HarnessError("WORKER_REPORT_MISSING", str(worker_report))
        worker = load_json_strict(worker_report)
        if worker.get("nativeKeySendAttempts") != 0 or worker.get("externalCalls") != 0:
            raise HarnessError("WORKER_SIDE_EFFECTS", "worker report records forbidden side effects")
        if exit_code != 0:
            raise HarnessError("CHILD_EXIT_NONZERO", str(exit_code))
        return result

    def _record_failure(self, task_id: str, state: dict[str, Any], attempt: int, code: str, message: str, retryable: bool) -> dict[str, Any]:
        status = "RETRYABLE_FAILURE" if retryable and attempt < self.policy["retries"]["maximumTaskAttempts"] else "FAILED"
        updated = dict(state)
        updated["status"] = status
        updated["nextAttempt"] = attempt + 1
        updated["error"] = {"code": code, "message": message}
        updated["attempts"] = list(updated.get("attempts", [])) + [{"attempt": attempt, "status": status, "error": updated["error"]}]
        updated["updatedAt"] = now_local_iso()
        self._write_state(task_id, updated)
        self._checkpoint("TASK_FAILED", {"taskId": task_id, "attempt": attempt, "retryable": retryable, "code": code})
        return updated

    def run_task(self, task_id: str, *, recover: bool = False) -> dict[str, Any]:
        task = self._load_task(task_id)
        state = self._load_state(task_id)
        if state["status"] in TERMINAL_STATES:
            return state
        attempt = int(state.get("nextAttempt", 1))
        if attempt > int(self.policy["retries"]["maximumTaskAttempts"]):
            return self._record_failure(task_id, state, attempt, "ATTEMPTS_EXHAUSTED", "maximum task attempts exceeded", False)
        self._validate_task_semantics(task)
        admission = self._resource_admission(task)
        output_base = self._resolve_output_root(task)
        output_base.mkdir(parents=True, exist_ok=True)
        attempt_root = output_base / f"attempt-{attempt}"
        lease, release = self._acquire_lease(task_id, attempt, recover=recover)
        if attempt_root.exists():
            self._release_lease(task_id, attempt, release, exit_code=None, status="OUTPUT_EXISTS")
            return self._record_failure(task_id, state, attempt, "OUTPUT_EXISTS", f"refusing to overwrite {attempt_root}", False)
        attempt_root.mkdir()
        task_path = self._task_dir(task_id) / "task.json"
        result_path = attempt_root / "result.json"
        state = dict(state)
        state["status"] = "RUNNING"
        state["updatedAt"] = now_local_iso()
        state["attempts"] = list(state.get("attempts", [])) + [{"attempt": attempt, "status": "RUNNING", "admission": admission}]
        self._write_state(task_id, state)
        command = self._expected_command(task_path, result_path, attempt_root)
        env = os.environ.copy()
        env.update({"QINBAN_LUNA_OFFLINE": "1", "QINBAN_LUNA_NATIVE_INPUT": "0", "PYTHONHASHSEED": "0"})
        start = time.perf_counter()
        exit_code: int | None = None
        error: HarnessError | None = None
        try:
            try:
                completed = subprocess.run(command, cwd=str(self.config.repository_root / "tools"), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=int(task["budget"]["wallTimeSeconds"]), check=False)
                exit_code = int(completed.returncode)
                (attempt_root / "stdout.txt").write_text(completed.stdout or "", encoding="utf-8")
                (attempt_root / "stderr.txt").write_text(completed.stderr or "", encoding="utf-8")
            except subprocess.TimeoutExpired as exc:
                (attempt_root / "stdout.txt").write_text(str(exc.stdout or ""), encoding="utf-8")
                (attempt_root / "stderr.txt").write_text(str(exc.stderr or ""), encoding="utf-8")
                error = HarnessError("CHILD_TIMEOUT", f"worker exceeded {task['budget']['wallTimeSeconds']} seconds")
            receipt = {
                "schemaVersion": 1, "taskId": task_id, "attempt": attempt, "command": command,
                "expectedCommand": self._expected_command(task_path, result_path, attempt_root),
                "allowlisted": self._same_command(command, self._expected_command(task_path, result_path, attempt_root)),
                "exitCode": exit_code, "elapsedMs": round((time.perf_counter() - start) * 1000, 3),
                "stdoutSha256": sha256_file(attempt_root / "stdout.txt"), "stderrSha256": sha256_file(attempt_root / "stderr.txt"), "createdAt": now_local_iso(),
            }
            write_json_once(attempt_root / "child-receipt.json", receipt)
            if not receipt["allowlisted"]:
                error = HarnessError("COMMAND_NOT_ALLOWLISTED", "child command differs from deterministic worker command")
            if error is None and exit_code != 0:
                error = HarnessError("CHILD_EXIT_NONZERO", str(exit_code))
            if error is None:
                try:
                    result = self._validate_result(task, result_path, attempt_root, exit_code or 0)
                except HarnessError as exc:
                    error = exc
                    result = None
                if error is None and result is not None:
                    final = dict(state)
                    final["status"] = result["status"]
                    final["nextAttempt"] = attempt + 1
                    final["resultPath"] = relative_posix(result_path, self.run_root)
                    final["error"] = None
                    final["updatedAt"] = now_local_iso()
                    final["attempts"][-1].update({"status": result["status"], "resultPath": final["resultPath"]})
                    self._write_state(task_id, final)
                    self._release_lease(task_id, attempt, release, exit_code=exit_code, status=result["status"])
                    self._checkpoint("TASK_COMPLETED", {"taskId": task_id, "attempt": attempt, "status": result["status"], "resultPath": final["resultPath"]})
                    return final
            if error is None:
                error = HarnessError("UNKNOWN_WORKER_FAILURE", "worker did not produce a valid result")
            retryable = error.code in {"CHILD_TIMEOUT", "CHILD_EXIT_NONZERO", "RESULT_MISSING"}
            self._release_lease(task_id, attempt, release, exit_code=exit_code, status="FAILED")
            return self._record_failure(task_id, state, attempt, error.code, error.message, retryable)
        except Exception:
            if not release.exists():
                try:
                    self._release_lease(task_id, attempt, release, exit_code=exit_code, status="CONTROLLER_EXCEPTION")
                except Exception:
                    pass
            raise

    def run_queue(self, *, recover: bool = False) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for task_dir in sorted((self.run_root / "tasks").iterdir(), key=lambda p: p.name):
            if not task_dir.is_dir():
                continue
            state = self._load_state(task_dir.name)
            if state["status"] in TERMINAL_STATES:
                continue
            try:
                results.append(self.run_task(task_dir.name, recover=recover))
            except HarnessError as exc:
                results.append({"taskId": task_dir.name, "status": "BLOCKED", "error": {"code": exc.code, "message": exc.message}})
        return results

    def close_run(self, status: str = "COMPLETE") -> None:
        if status not in {"COMPLETE", "PARTIAL", "BLOCKED"}:
            raise HarnessError("BAD_RUN_STATUS", status)
        self._update_manifest(status=status, closedAt=now_local_iso())
        self._checkpoint("RUN_CLOSED", {"status": status})


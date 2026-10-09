from __future__ import annotations

import argparse
import json
from pathlib import Path

from .checker import check_run
from .controller import HarnessController, HarnessError


def main() -> int:
    parser = argparse.ArgumentParser(description="QinBan Luna score harness G0 controller")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-run")
    create.add_argument("--run-id")
    create.add_argument("--no-baseline-check", action="store_true")
    submit = sub.add_parser("submit")
    submit.add_argument("--run-root", required=True)
    submit.add_argument("--task", required=True)
    run = sub.add_parser("run-task")
    run.add_argument("--run-root", required=True)
    run.add_argument("--task-id", required=True)
    run.add_argument("--recover", action="store_true")
    queue = sub.add_parser("run-queue")
    queue.add_argument("--run-root", required=True)
    queue.add_argument("--recover", action="store_true")
    cancel = sub.add_parser("cancel")
    cancel.add_argument("--run-root", required=True)
    cancel.add_argument("--task-id", required=True)
    cancel.add_argument("--reason", required=True)
    gate = sub.add_parser("mark-gate")
    gate.add_argument("--run-root", required=True)
    gate.add_argument("--gate", required=True)
    gate.add_argument("--status", required=True)
    check = sub.add_parser("check-run")
    check.add_argument("--run-root", required=True)
    check.add_argument("--output")
    close = sub.add_parser("close-run")
    close.add_argument("--run-root", required=True)
    close.add_argument("--status", default="COMPLETE", choices=["COMPLETE", "PARTIAL", "BLOCKED"])
    args = parser.parse_args()
    try:
        if args.command == "create-run":
            from .controller import HarnessConfig
            cfg = HarnessConfig.from_repository()
            if args.no_baseline_check:
                cfg = HarnessConfig(cfg.workspace_root, cfg.repository_root, cfg.contract_root, cfg.runs_root, cfg.baseline_path, False, cfg.resource_overrides)
            controller = HarnessController.create(cfg, run_id=args.run_id)
            print(json.dumps({"status": "PASS", "runRoot": str(controller.run_root), "runId": controller.manifest["runId"]}, ensure_ascii=False))
            return 0
        if args.command == "submit":
            controller = HarnessController.load(Path(args.run_root))
            print(json.dumps(controller.submit_task_file(Path(args.task)), ensure_ascii=False))
            return 0
        if args.command == "run-task":
            controller = HarnessController.load(Path(args.run_root))
            print(json.dumps(controller.run_task(args.task_id, recover=args.recover), ensure_ascii=False))
            return 0
        if args.command == "run-queue":
            controller = HarnessController.load(Path(args.run_root))
            print(json.dumps(controller.run_queue(recover=args.recover), ensure_ascii=False))
            return 0
        if args.command == "cancel":
            controller = HarnessController.load(Path(args.run_root))
            print(json.dumps(controller.cancel_task(args.task_id, args.reason), ensure_ascii=False))
            return 0
        if args.command == "mark-gate":
            controller = HarnessController.load(Path(args.run_root))
            controller.mark_gate(args.gate, args.status)
            print(json.dumps({"status": "PASS", "gate": args.gate, "value": args.status}, ensure_ascii=False))
            return 0
        if args.command == "check-run":
            passed, report, path = check_run(Path(args.run_root), Path(args.output) if args.output else None)
            print(json.dumps({"status": report["status"], "failedChecks": report["failedChecks"], "report": str(path) if path else None}, ensure_ascii=False))
            return 0 if passed else 1
        if args.command == "close-run":
            controller = HarnessController.load(Path(args.run_root))
            controller.close_run(args.status)
            print(json.dumps({"status": "PASS", "runRoot": str(controller.run_root), "runStatus": args.status}, ensure_ascii=False))
            return 0
        raise HarnessError("UNKNOWN_COMMAND", args.command)
    except HarnessError as exc:
        print(json.dumps({"status": "ERROR", "error": exc.code, "message": exc.message}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

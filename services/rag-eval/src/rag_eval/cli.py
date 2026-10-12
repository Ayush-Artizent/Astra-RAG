"""``rag-eval run`` / ``rag-eval gate``."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from astra_rag_sdk import AstraRagClient
from rag_core.schemas import CallerInfo
from rag_eval import dataset, harness


async def _evaluate(args: argparse.Namespace, cases: list[dataset.EvalCase]) -> harness.Report:
    caller = CallerInfo(platform="rag-eval", agent_run_id=args.run_id)
    async with AstraRagClient(args.api_url, args.token, caller=caller, timeout=60) as client:
        return await harness.run(client, cases)


def _run(args: argparse.Namespace) -> int:
    report = asyncio.run(_evaluate(args, dataset.load(Path(args.dataset))))
    Path(args.out).write_text(report.model_dump_json(indent=2), encoding="utf-8")
    for k, v in sorted(report.aggregate.items()):
        print(f"{k:>22}: {v:.4f}")
    return 0


def _gate(args: argparse.Namespace) -> int:
    base = harness.Report.model_validate_json(Path(args.baseline).read_text(encoding="utf-8"))
    cand = harness.Report.model_validate_json(Path(args.candidate).read_text(encoding="utf-8"))
    failures = harness.gate(base, cand, args.max_drop)
    for f in failures:
        print(f"REGRESSION {f}", file=sys.stderr)
    print("eval gate:", "FAIL" if failures else "PASS")
    return 1 if failures else 0


def main() -> None:
    p = argparse.ArgumentParser(prog="rag-eval")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run a dataset against a rag-api instance")
    r.add_argument("--dataset", default="eval/datasets/smoke.jsonl")
    r.add_argument("--api-url", default=os.environ.get("ASTRA_API_URL", "http://localhost:8080"))
    r.add_argument("--token", default=os.environ.get("ASTRA_API_TOKEN", "dev-key-tenant-a"))
    r.add_argument("--out", default="eval-report.json")
    r.add_argument("--run-id", default=None)

    g = sub.add_parser("gate", help="fail if candidate regresses vs baseline")
    g.add_argument("--baseline", required=True)
    g.add_argument("--candidate", required=True)
    g.add_argument("--max-drop", type=float, default=0.02)

    args = p.parse_args()
    sys.exit(_run(args) if args.cmd == "run" else _gate(args))


if __name__ == "__main__":
    main()

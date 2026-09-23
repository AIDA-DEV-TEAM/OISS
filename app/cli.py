"""Command line entry point: ``python -m app.cli build``."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.config import DB_PATH, ROOT


def _venv_hint(missing: ModuleNotFoundError) -> str:
    """What to do when the interpreter running this has no dependencies."""
    windows = sys.platform == "win32"
    venv = ROOT / ".venv" / ("Scripts" if windows else "bin") / ("python.exe" if windows else "python")
    lines = [
        f"{missing.name!r} is not installed for {sys.executable}.",
        "",
        "This is the interpreter, not the code: `python` on your PATH is not the",
        "project virtualenv. Run the build with the virtualenv's interpreter:",
        "",
        f"    {venv} -m app.cli build",
    ]
    if not venv.exists():
        lines += [
            "",
            "There is no .venv here yet. Create one and install the pinned",
            "dependencies first:",
            "",
            "    python -m venv .venv",
            f"    {venv} -m pip install -r requirements.txt",
        ]
    return "\n".join(lines)


def _print_summary(summary: dict) -> None:
    print(f"\nrun_id : {summary['run_id']}")
    print(f"status : {summary['status']}")
    print(f"database: {summary['database']}")

    print("\nRows per table")
    print("-" * 64)
    for table, count in summary["row_counts"].items():
        print(f"  {table:<48} {count:>10,}")

    print("\nFindings per rule")
    print("-" * 100)
    rows = summary.get("finding_summary") or []
    if not rows:
        print("  (none)")
    else:
        print(f"  {'rule_code':<22} {'severity':<8} {'count':>7} {'datasets':>9}  sample")
        for row in rows:
            sample = (row["sample_row_ref"] or "")[:44]
            print(
                f"  {row['rule_code']:<22} {row['severity']:<8} "
                f"{row['finding_count']:>7,} {row['dataset_count']:>9}  {sample}"
            )
        by_severity: dict[str, int] = {}
        for row in rows:
            by_severity[row["severity"]] = (
                by_severity.get(row["severity"], 0) + row["finding_count"]
            )
        totals = "  ".join(f"{k}={v:,}" for k, v in sorted(by_severity.items()))
        print(f"  {'':<22} {'':<8} {sum(by_severity.values()):>7,}            {totals}")

    print("\nReconciliation checks")
    print("-" * 64)
    for check in summary["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"  [{mark}] {check['check_code']}")
        if not check["passed"]:
            print(f"         expected {check['expected']}, observed {check['observed']}")

    failed = [c for c in summary["checks"] if not c["passed"]]
    print("\n" + "-" * 64)
    print(f"{len(summary['checks']) - len(failed)}/{len(summary['checks'])} checks passed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli", description="OISS PoC data layer")
    sub = parser.add_subparsers(dest="command", required=True)

    build_parser = sub.add_parser("build", help="rebuild data/oiss.duckdb from scratch")
    build_parser.add_argument("--db", type=Path, default=DB_PATH)
    build_parser.add_argument("--json", action="store_true", help="emit the summary as JSON")

    seed_parser = sub.add_parser(
        "seed-assistant", help="record the starter questions into the shipped LLM cache"
    )
    seed_parser.add_argument("--db", type=Path, default=DB_PATH)

    args = parser.parse_args(argv)

    if args.command == "build":
        try:
            from app.ingest.loaders import build
        except ModuleNotFoundError as missing:
            # Almost always the project virtualenv is not on PATH, and a bare
            # ModuleNotFoundError sends people looking for a bug in the code.
            print(_venv_hint(missing), file=sys.stderr)
            return 2

        summary = build(args.db)
        if args.json:
            print(json.dumps(summary, indent=2, default=str))
        else:
            _print_summary(summary)
        return 0 if summary["status"] == "succeeded" else 1

    if args.command == "seed-assistant":
        from app import db
        from app.assistant.seed import seed
        from app.config import LLM_CACHE_DIR

        con = db.connect(args.db)
        try:
            for item in seed(con, LLM_CACHE_DIR):
                print(f"{item['status']:>9}  {item['question_id']}")
        finally:
            con.close()
        print(f"cache: {LLM_CACHE_DIR}")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())

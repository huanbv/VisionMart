"""Entry point for `python -m visionmart <command>`.

  doctor      Run all deployment-validation checks and print a report
              (Part 6). Exits non-zero if any check FAILed.
  readiness   Print the Production Readiness Report (Part 5) as JSON --
              the same data monitoring/server.py's GET /api/readiness
              serves; provided here too for scripting/CI use without
              needing the monitoring service to be reachable over HTTP.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="visionmart", description="VisionMart deployment validation & production readiness.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="Run deployment-validation checks (Part 6).")
    subparsers.add_parser("readiness", help="Print the Production Readiness Report as JSON (Part 5).")

    args = parser.parse_args(argv)

    if args.command == "doctor":
        from visionmart.doctor import main as doctor_main
        return doctor_main()

    if args.command == "readiness":
        from visionmart.readiness import build_readiness_report

        report = asyncio.run(build_readiness_report())
        print(json.dumps(report, indent=2, default=str))
        return 1 if report["overall_status"] == "FAIL" else 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())

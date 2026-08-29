#!/usr/bin/env python3
"""Manual backup command.

    python -m backup.cli run              # run one backup now + apply retention
    python -m backup.cli list              # list existing backups
    python -m backup.cli verify <zip>      # check integrity + checksum of one backup
    python -m backup.cli cleanup           # apply retention policy only (no new backup)
    python -m backup.cli schedule          # run the cron-scheduled daemon in the foreground

Exit codes: 0 on success, 1 if the requested operation failed or found a
problem (e.g. `verify` on a corrupt archive). This command never mutates
production data — `run`/`cleanup`/`verify`/`list` only touch the backup
output directory and read from production sources.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from backup.archive import build_backup, verify_archive
from backup.config import get_backup_config
from backup.logging_config import configure_logging
from backup.retention import cleanup_old_backups


def _cmd_run(args: argparse.Namespace) -> int:
    cfg = get_backup_config()
    configure_logging(cfg)
    manifest = build_backup(cfg)
    print(json.dumps(manifest, indent=2))
    if not args.skip_cleanup:
        cleanup = cleanup_old_backups(cfg.output_dir, cfg.retention_days)
        print(f"Retention cleanup: kept={len(cleanup.kept)} deleted={len(cleanup.deleted)} errors={cleanup.errors}")
    return 0 if manifest.get("overall_ok") else 1


def _cmd_list(args: argparse.Namespace) -> int:
    cfg = get_backup_config()
    root = Path(cfg.output_dir)
    if not root.exists():
        print(f"Backup directory does not exist yet: {root}")
        return 0
    zips = sorted(root.glob("visionmart-backup-*.zip"))
    if not zips:
        print(f"No backups found in {root}")
        return 0
    for z in zips:
        checksum_file = z.with_suffix(z.suffix + ".sha256")
        size_mb = z.stat().st_size / (1024 * 1024)
        has_checksum = "yes" if checksum_file.exists() else "no"
        print(f"{z.name}\t{size_mb:.1f} MB\tchecksum={has_checksum}")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    ok, detail = verify_archive(Path(args.path))
    print(f"{'PASS' if ok else 'FAIL'}: {detail}")
    return 0 if ok else 1


def _cmd_cleanup(args: argparse.Namespace) -> int:
    cfg = get_backup_config()
    result = cleanup_old_backups(cfg.output_dir, cfg.retention_days)
    print(json.dumps(vars(result), indent=2))
    return 0 if not result.errors else 1


def _cmd_schedule(args: argparse.Namespace) -> int:
    from backup.scheduler import BackupScheduler

    cfg = get_backup_config()
    configure_logging(cfg)

    async def _run_forever() -> None:
        scheduler = BackupScheduler(cfg)
        scheduler.start()
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            await scheduler.stop()
            raise

    try:
        asyncio.run(_run_forever())
    except KeyboardInterrupt:
        pass
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="visionmart-backup", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Run one backup now and apply retention.")
    p_run.add_argument("--skip-cleanup", action="store_true", help="Only back up, don't apply retention afterwards.")
    p_run.set_defaults(func=_cmd_run)

    p_list = sub.add_parser("list", help="List existing backups.")
    p_list.set_defaults(func=_cmd_list)

    p_verify = sub.add_parser("verify", help="Verify a backup archive's integrity and checksum.")
    p_verify.add_argument("path", help="Path to a visionmart-backup-*.zip file.")
    p_verify.set_defaults(func=_cmd_verify)

    p_cleanup = sub.add_parser("cleanup", help="Apply the retention policy without creating a new backup.")
    p_cleanup.set_defaults(func=_cmd_cleanup)

    p_schedule = sub.add_parser("schedule", help="Run the cron-scheduled backup daemon in the foreground.")
    p_schedule.set_defaults(func=_cmd_schedule)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()

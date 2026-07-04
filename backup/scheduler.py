"""Optional cron-scheduled backup daemon.

Most VPS deployments are well served by host cron calling
`python -m backup.cli run` once a day (documented in
docs/43_BACKUP_RECOVERY.md, mirroring the pattern already used for the
Let's Encrypt renewal hook in docs/DEPLOY_VPS.md). This module exists
for operators who prefer an in-stack scheduled service instead
(`docker compose --profile backup up -d backup`) — it computes the next
run time from a standard cron expression (`BACKUP_CRON_SCHEDULE`,
default daily at 02:00) using `croniter`, sleeps until then, runs a
backup + retention cleanup, and repeats. A single bad run is logged and
never crashes the loop, same fault-tolerance pattern as
`monitoring/scheduler.py`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from backup.archive import build_backup
from backup.config import BackupConfig
from backup.retention import cleanup_old_backups

logger = logging.getLogger("backup.scheduler")


def _seconds_until_next_run(cron_expr: str) -> float:
    from croniter import croniter

    now = datetime.now(timezone.utc)
    itr = croniter(cron_expr, now)
    next_run = itr.get_next(datetime)
    return max(1.0, (next_run - now).total_seconds())


class BackupScheduler:
    def __init__(self, cfg: BackupConfig) -> None:
        self.cfg = cfg
        self._task: asyncio.Task | None = None
        self._stopping = False
        self.last_run_ts: float | None = None
        self.last_result: dict | None = None
        self.last_error: str | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while not self._stopping:
            try:
                wait_s = _seconds_until_next_run(self.cfg.cron_schedule)
                logger.info("Next backup scheduled in %.0f seconds (cron=%s)", wait_s, self.cfg.cron_schedule)
                await asyncio.sleep(wait_s)
                await self._run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — one bad cycle must never kill the loop
                self.last_error = str(exc)
                logger.exception("Backup scheduler cycle failed: %s", exc)
                await asyncio.sleep(60)

    async def _run_once(self) -> None:
        loop = asyncio.get_running_loop()
        manifest = await loop.run_in_executor(None, build_backup, self.cfg)
        cleanup = await loop.run_in_executor(None, cleanup_old_backups, self.cfg.output_dir, self.cfg.retention_days)
        self.last_run_ts = time.time()
        self.last_result = {"manifest": manifest, "cleanup": vars(cleanup)}
        self.last_error = None if manifest.get("overall_ok") else "See manifest for per-source failures."
        logger.info(
            "Backup run complete: id=%s ok=%s deleted=%d kept=%d",
            manifest.get("backup_id"), manifest.get("overall_ok"), len(cleanup.deleted), len(cleanup.kept),
        )

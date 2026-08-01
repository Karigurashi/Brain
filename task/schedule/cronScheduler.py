"""CronScheduler —— 基于 croniter 的秒级 cron 调度器（纯调度引擎，不涉及持久化）。"""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Callable

from croniter import croniter

from common.logger import Logger

if TYPE_CHECKING:
    from .taskSpec import TaskSpec

FireCallback = Callable[["TaskSpec"], None]


@dataclass(slots=True)
class CronJob:
    """单个 cron 任务的运行时状态。"""

    jobId: str
    expression: str
    callback: Callable[[], None]
    nextFire: datetime


class CronScheduler:
    """基于 croniter 的纯 cron 调度引擎。

    仅负责 job 的注册、取消与 ticker 驱动，不涉及任何持久化操作。
    JSON 读写等 Agent 专有操作由上层 ScheduleRegistry 包装。
    """

    _MAX_FIRE_CATCHUP: float = 60.0
    """注册任务时，若 cron.get_prev() 距现在 <= 该值，nextFire 置为 now 立即触发。"""

    def __init__(self) -> None:
        self._jobs: dict[str, CronJob] = {}
        self._specToJob: dict[int, str] = {}
        self._tickerTask: asyncio.Task | None = None
        self._running: bool = False

    # ---- 生命周期 ----

    def EnsureStarted(self) -> None:
        """若尚未运行则启动 ticker（同步，要求当前有 running loop）。"""
        if self._running:
            return
        self._running = True
        self._tickerTask = asyncio.create_task(self._TickAsync())

    async def StopAsync(self) -> None:
        """停止调度器。"""
        self._running = False
        if self._tickerTask is not None:
            self._tickerTask.cancel()
            try:
                await self._tickerTask
            except asyncio.CancelledError:
                pass
            self._tickerTask = None

    def Clear(self) -> None:
        """清空所有 job 及 spec 映射。"""
        self._jobs.clear()
        self._specToJob.clear()

    # ---- Spec 级 API ----

    def ArmSpec(self, spec: TaskSpec, onFire: FireCallback) -> None:
        """按 spec 注册 cron job，重复 arm 不报错。"""
        if spec.specId in self._specToJob:
            return
        jobId = self.AddJob(spec.expression, lambda s=spec: onFire(s))
        self._specToJob[spec.specId] = jobId
        self.EnsureStarted()

    def DisarmSpec(self, specId: int) -> bool:
        """按 specId 移除 cron job。"""
        jobId = self._specToJob.pop(specId, None)
        if jobId is None:
            return False
        return self.RemoveJob(jobId)

    # ---- Job 管理 ----

    def AddJob(self, expression: str, callback: Callable[[], None]) -> str:
        """注册一个 cron job，返回 jobId。"""
        now = datetime.now()
        cron = croniter(expression, now)
        prevFire = cron.get_prev(datetime)
        nextFire = cron.get_next(datetime)

        # 注册时间在触发窗口边缘：立即触发而非等到下一周期
        delta = (now - prevFire).total_seconds()
        if 0 <= delta <= self._MAX_FIRE_CATCHUP:
            nextFire = now

        jobId = self._GenerateJobId()
        self._jobs[jobId] = CronJob(
            jobId=jobId,
            expression=expression,
            callback=callback,
            nextFire=nextFire,
        )
        return jobId

    def RemoveJob(self, jobId: str) -> bool:
        """按 jobId 删除 job。"""
        if jobId in self._jobs:
            del self._jobs[jobId]
            return True
        return False

    # ---- Ticker ----

    async def _TickAsync(self) -> None:
        """每秒扫描到期 job 并触发。"""
        while self._running:
            try:
                now = datetime.now()
                for jobId, job in list(self._jobs.items()):
                    if now >= job.nextFire:
                        try:
                            job.callback()
                        except Exception as exc:
                            Logger.Error(f"CronScheduler: job {jobId} callback failed: {exc}")
                        if jobId in self._jobs:
                            cron = croniter(job.expression, datetime.now())
                            job.nextFire = cron.get_next(datetime)
            except Exception as exc:
                Logger.Error(f"CronScheduler: tick error: {exc}")
            await asyncio.sleep(1)

    @staticmethod
    def _GenerateJobId() -> str:
        """生成 8 字符 jobId。"""
        return hashlib.md5(str(time.time_ns()).encode()).hexdigest()[:8]

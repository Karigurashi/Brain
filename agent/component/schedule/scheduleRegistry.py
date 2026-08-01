"""ScheduleRegistry —— 包装 CronScheduler + JSON 持久化，统一提供 Agent 层定时任务管理。"""

from __future__ import annotations

import os
import tempfile
import time
from datetime import datetime
from typing import Optional

from croniter import croniter

from common import SerializeUtil
from task.schedule.cronScheduler import CronScheduler, FireCallback
from task.schedule.taskSpec import TaskSpec

SCHEDULES_FILENAME = "schedules.json"


def _ToPersistDict(spec: TaskSpec) -> dict:
    """将 TaskSpec 转为可持久化的 dict，时间戳转为 int。"""
    d = SerializeUtil.ToDict(spec)
    d["createdAt"] = int(spec.createdAt)
    d["lastFiredAt"] = int(spec.lastFiredAt)
    return d


class ScheduleRegistry:
    """定时任务注册表：包装 CronScheduler 并附加 JSON 持久化。

    CronScheduler 是框架底层的纯调度引擎；
    ScheduleRegistry 在其上增加了 spec 管理、校验和 JSON 读写。
    """

    def __init__(self, tasksDir: str) -> None:
        self._cron = CronScheduler()
        self._tasksDir: str = tasksDir
        self._filePath: str = os.path.join(tasksDir, SCHEDULES_FILENAME)
        self._specs: dict[int, TaskSpec] = {}
        self._nextSpecId: int = 1

    # ---- 生命周期 ----

    def Load(self) -> list[TaskSpec]:
        """从 JSON 载入全部 spec 定义，返回加载列表。"""
        maxId = 0
        loaded: list[TaskSpec] = []
        for raw in self._LoadAll():
            spec = SerializeUtil.FromDict(raw, TaskSpec)
            if spec.specId <= 0 or not spec.expression:
                continue
            self._specs[spec.specId] = spec
            loaded.append(spec)
            if spec.specId > maxId:
                maxId = spec.specId
        self._nextSpecId = maxId + 1
        return loaded

    def Persist(self) -> None:
        """落盘全部 spec 到 JSON 文件（原子写入）。"""
        os.makedirs(self._tasksDir, exist_ok=True)
        tasks = [_ToPersistDict(s) for s in self._specs.values()]
        payload = {"version": 1, "tasks": tasks}
        content = SerializeUtil.ToJson(payload, indent=2)
        dirName = os.path.dirname(self._filePath) or "."
        fd, tmpPath = tempfile.mkstemp(dir=dirName, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmpPath, self._filePath)
        except Exception:
            if os.path.isfile(tmpPath):
                os.remove(tmpPath)
            raise

    def RestoreAll(self, onFire: FireCallback) -> None:
        """恢复所有已持久化 spec 并 arm。"""
        for spec in self.Load():
            self._cron.ArmSpec(spec, onFire)

    def Clear(self) -> None:
        """清空所有 spec 及底层 cron job。"""
        self._cron.Clear()
        self._specs.clear()
        self._nextSpecId = 1

    # ---- Spec 管理 ----

    def CreateAgentWake(
        self,
        name: str,
        expression: str,
        prompt: str,
        onFire: FireCallback,
    ) -> TaskSpec:
        """校验 cron 表达式，创建 Spec 并 arm。

        Args:
            name: 任务名称。
            expression: 5 字段 cron 表达式。
            prompt: 注入 Agent 的指令文本。
            onFire: 触发回调。

        Returns:
            新创建的 TaskSpec。
        """
        croniter(expression, datetime.now())

        specId = self._AllocSpecId()
        spec = TaskSpec(
            specId=specId,
            name=name or "AgentWake",
            expression=expression,
            prompt=prompt,
            createdAt=time.time(),
        )
        self._specs[spec.specId] = spec
        self.Persist()
        self._cron.ArmSpec(spec, onFire)
        return spec

    def RemoveSpec(self, specId: int) -> bool:
        """删除 spec 定义并 disarm job。"""
        self._cron.DisarmSpec(specId)
        if specId not in self._specs:
            return False
        del self._specs[specId]
        self.Persist()
        return True

    def GetSpec(self, specId: int) -> Optional[TaskSpec]:
        return self._specs.get(specId)

    def ListSpecs(self) -> list[TaskSpec]:
        return list(self._specs.values())

    # ---- 内部 ----

    def _AllocSpecId(self) -> int:
        specId = self._nextSpecId
        self._nextSpecId += 1
        return specId

    def _LoadAll(self) -> list[dict]:
        """加载全部 spec 原始字典；文件不存在返回空列表。"""
        if not os.path.isfile(self._filePath):
            return []
        with open(self._filePath, "r", encoding="utf-8") as f:
            data = SerializeUtil.FromJson(f.read())
        return data.get("tasks", [])

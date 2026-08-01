"""LOD 五级分级枚举 —— 控制上下文内容的压缩与丢弃策略。"""

from enum import IntEnum


class EContextLodLevel(IntEnum):
    """上下文内容分级 —— 决定压缩策略、丢弃权限、注入行为。

    Attributes:
        RESIDENT (0): 常驻不压缩，不可丢弃（System Prompt、核心指令）。
        SUMMARIZABLE (1): 可压缩为摘要，不可丢弃（用户偏好、重要决策）。
        DISCARDABLE (2): 可落盘为路径引用，不参与 LLM 摘要（旧工具结果、思考过程）。
        LATEST_ONLY (3): 卸载时删光只留最后 1 条（如 StatusBar）。
        EXTERNAL_ONLY (4): 当轮注入、次轮全部丢弃（Skill ref、超大工具结果）。
    """

    RESIDENT = 0
    SUMMARIZABLE = 1
    DISCARDABLE = 2
    LATEST_ONLY = 3
    EXTERNAL_ONLY = 4

    def CanCompress(self) -> bool:
        """是否可 LLM 摘要。仅 LOD 1 可摘要，LOD 2 走落盘。"""
        return self == EContextLodLevel.SUMMARIZABLE

    def CanDiscard(self) -> bool:
        """是否可在 token 不足时丢弃。LOD 2/3/4 可丢弃。"""
        return self in (
            EContextLodLevel.DISCARDABLE,
            EContextLodLevel.LATEST_ONLY,
            EContextLodLevel.EXTERNAL_ONLY,
        )

    def IsTurnScoped(self) -> bool:
        """是否为当轮注入、次轮丢弃。仅 LOD 4。"""
        return self == EContextLodLevel.EXTERNAL_ONLY

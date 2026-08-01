"""飞书消息表情反应管理。

提供表情反应的添加、删除、列表查询，以及飞书表情类型常量。
对齐 openclaw-lark-main src/messaging/outbound/reactions.ts。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.feishu.core.apiError import ExtractLarkApiCode
from app.feishu.core.larkClient import LarkClient
from common.cancellationToken import CancellationToken

# ---------------------------------------------------------------------------
# FeishuReaction
# ---------------------------------------------------------------------------


@dataclass
class FeishuReaction:
    """飞书消息上的一条表情反应。"""

    reactionId: str = ""
    """平台分配的唯一 reaction ID。"""
    emojiType: str = ""
    """表情类型字符串（如 "THUMBSUP", "HEART"）。"""
    operatorType: str = ""
    """操作者类型："app" 或 "user"。"""
    operatorId: str = ""
    """操作者的 Open ID。"""


# ---------------------------------------------------------------------------
# Feishu emoji constants
# ---------------------------------------------------------------------------


class FeishuEmoji:
    """常用飞书表情类型常量。

    这是一个便利映射，避免硬编码字符串。非穷举 —— 飞书支持更多
    表情类型，任意合法的 emoji_type 字符串均可直接传入 API 函数。
    """

    THUMBSUP = "THUMBSUP"
    THUMBSDOWN = "THUMBSDOWN"
    HEART = "HEART"
    SMILE = "SMILE"
    JOYFUL = "JOYFUL"
    FROWN = "FROWN"
    BLUSH = "BLUSH"
    OK = "OK"
    CLAP = "CLAP"
    FIREWORKS = "FIREWORKS"
    PARTY = "PARTY"
    MUSCLE = "MUSCLE"
    FIRE = "FIRE"
    EYES = "EYES"
    THINKING = "THINKING"
    PRAISE = "PRAISE"
    PRAY = "PRAY"
    ROCKET = "ROCKET"
    DONE = "DONE"
    SKULL = "SKULL"
    HUNDREDPOINTS = "HUNDREDPOINTS"
    FACEPALM = "FACEPALM"
    CHECK = "CHECK"
    CROSSMARK = "CrossMark"
    COOL = "COOL"
    TYPING = "Typing"
    SPEECHLESS = "SPEECHLESS"


# ---------------------------------------------------------------------------
# Valid Feishu emoji types (complete set)
# ---------------------------------------------------------------------------


VALID_FEISHU_EMOJI_TYPES: frozenset[str] = frozenset(
    {
        # Gestures / actions
        "OK",
        "THUMBSUP",
        "THANKS",
        "MUSCLE",
        "FINGERHEART",
        "APPLAUSE",
        "FISTBUMP",
        "JIAYI",
        "DONE",
        # Faces / expressions
        "SMILE",
        "BLUSH",
        "LAUGH",
        "SMIRK",
        "LOL",
        "FACEPALM",
        "LOVE",
        "WINK",
        "PROUD",
        "WITTY",
        "SMART",
        "SCOWL",
        "THINKING",
        "SOB",
        "CRY",
        "ERROR",
        "NOSEPICK",
        "HAUGHTY",
        "SLAP",
        "SPITBLOOD",
        "TOASTED",
        "GLANCE",
        "DULL",
        "INNOCENTSMILE",
        "JOYFUL",
        "WOW",
        "TRICK",
        "YEAH",
        "ENOUGH",
        "TEARS",
        "EMBARRASSED",
        "KISS",
        "SMOOCH",
        "DROOL",
        "OBSESSED",
        "MONEY",
        "TEASE",
        "SHOWOFF",
        "COMFORT",
        "CLAP",
        "PRAISE",
        "STRIVE",
        "XBLUSH",
        "SILENT",
        "WAVE",
        "WHAT",
        "FROWN",
        "SHY",
        "DIZZY",
        "LOOKDOWN",
        "CHUCKLE",
        "WAIL",
        "CRAZY",
        "WHIMPER",
        "HUG",
        "BLUBBER",
        "WRONGED",
        "HUSKY",
        "SHHH",
        "SMUG",
        "ANGRY",
        "HAMMER",
        "SHOCKED",
        "TERROR",
        "PETRIFIED",
        "SKULL",
        "SWEAT",
        "SPEECHLESS",
        "SLEEP",
        "DROWSY",
        "YAWN",
        "SICK",
        "PUKE",
        "BETRAYED",
        "HEADSET",
        "EatingFood",
        "MeMeMe",
        "Sigh",
        "Typing",
        "SLIGHT",
        "TONGUE",
        "EYESCLOSED",
        "RoarForYou",
        "CALF",
        "BEAR",
        "BULL",
        "RAINBOWPUKE",
        # Objects / food / drinks
        "Lemon",
        "ROSE",
        "HEART",
        "PARTY",
        "LIPS",
        "BEER",
        "CAKE",
        "GIFT",
        "CUCUMBER",
        "Drumstick",
        "Pepper",
        "CANDIEDHAWS",
        "BubbleTea",
        "Coffee",
        # Symbols / marks
        "Get",
        "LGTM",
        "OnIt",
        "OneSecond",
        "VRHeadset",
        "YouAreTheBest",
        "SALUTE",
        "SHAKE",
        "HIGHFIVE",
        "UPPERLEFT",
        "ThumbsDown",
        "Yes",
        "No",
        "OKR",
        "CheckMark",
        "CrossMark",
        "MinusOne",
        "Hundred",
        "AWESOMEN",
        "Pin",
        "Alarm",
        "Loudspeaker",
        "Trophy",
        "Fire",
        "BOMB",
        "Music",
        # Holidays / seasons
        "XmasTree",
        "Snowman",
        "XmasHat",
        "FIREWORKS",
        "2022",
        "REDPACKET",
        "FORTUNE",
        "LUCK",
        "FIRECRACKER",
        "StickyRiceBalls",
        # Miscellaneous
        "HEARTBROKEN",
        "POOP",
        "StatusFlashOfInspiration",
        "18X",
        "CLEAVER",
        "Soccer",
        "Basketball",
        # Status
        "GeneralDoNotDisturb",
        "Status_PrivateMessage",
        "GeneralInMeetingBusy",
        "StatusReading",
        "StatusInFlight",
        "GeneralBusinessTrip",
        "GeneralWorkFromHome",
        "StatusEnjoyLife",
        "GeneralTravellingCar",
        "StatusBus",
        "GeneralSun",
        "GeneralMoonRest",
        # Holiday extras
        "MoonRabbit",
        "Mooncake",
        "JubilantRabbit",
        "TV",
        "Movie",
        "Pumpkin",
        # Newer additions
        "BeamingFace",
        "Delighted",
        "ColdSweat",
        "FullMoonFace",
        "Partying",
        "GoGoGo",
        "ThanksFace",
        "SaluteFace",
        "Shrug",
        "ClownFace",
        "HappyDragon",
    }
)

# ---------------------------------------------------------------------------
# AddReactionFeishuAsync
# ---------------------------------------------------------------------------


async def AddReactionFeishuAsync(
    client: LarkClient,
    messageId: str,
    emojiType: str,
    cancellationToken: Optional[CancellationToken] = None,
) -> str:
    """给飞书消息添加表情反应，返回 reaction_id。

    若 emojiType 不合法（飞书返回 231001），抛出带有合法表情列表
    的 ValueError，方便调用方报告给用户。

    Args:
        client: LarkClient 实例。
        messageId: 目标消息 ID。
        emojiType: 表情类型字符串（如 "THUMBSUP"）。
        cancellationToken: 可选的取消令牌。

    Returns:
        平台分配的 reaction_id。

    Raises:
        ValueError: emojiType 不在飞书合法表情列表中（code=231001）。
    """
    try:
        reactionId = await client.AddReactionAsync(
            messageId,
            emojiType,
            cancellationToken=cancellationToken,
        )
        if not reactionId:
            raise RuntimeError(
                f"Failed to add reaction \"{emojiType}\" to message {messageId}: "
                "no reaction_id returned"
            )
        return reactionId
    except Exception as err:
        code = ExtractLarkApiCode(err)
        if code == 231001:
            validList = ", ".join(sorted(VALID_FEISHU_EMOJI_TYPES))
            raise ValueError(
                f"Emoji type \"{emojiType}\" is not a valid Feishu reaction. "
                f"Valid types: {validList}"
            ) from err
        raise


# ---------------------------------------------------------------------------
# RemoveReactionFeishuAsync
# ---------------------------------------------------------------------------


async def RemoveReactionFeishuAsync(
    client: LarkClient,
    messageId: str,
    reactionId: str,
    cancellationToken: Optional[CancellationToken] = None,
) -> None:
    """删除消息上的指定表情反应（按 reaction_id 精确删除）。

    区别于 typing.py 中的 RemoveTypingIndicatorAsync —— 本函数不关心
    是否已反应、不做静默吞错，由调用方决定错误策略。

    Args:
        client: LarkClient 实例。
        messageId: 消息 ID。
        reactionId: 要删除的 reaction_id。
        cancellationToken: 可选的取消令牌。
    """
    await client.DeleteReactionAsync(
        messageId,
        reactionId,
        cancellationToken=cancellationToken,
    )


# ---------------------------------------------------------------------------
# ListReactionsFeishuAsync
# ---------------------------------------------------------------------------


async def ListReactionsFeishuAsync(
    client: LarkClient,
    messageId: str,
    emojiType: Optional[str] = None,
    cancellationToken: Optional[CancellationToken] = None,
) -> list[FeishuReaction]:
    """列出消息上的所有表情反应（自动翻页）。

    Args:
        client: LarkClient 实例。
        messageId: 消息 ID。
        emojiType: 可选的表情类型过滤。
        cancellationToken: 可选的取消令牌。

    Returns:
        符合筛选条件的所有 FeishuReaction 对象列表。
    """
    reactions: list[FeishuReaction] = []
    pageToken: str | None = None
    hasMore = True

    while hasMore:
        result = await client.ListReactionsAsync(
            messageId,
            emojiType=emojiType,
            pageToken=pageToken,
            pageSize=50,
            cancellationToken=cancellationToken,
        )

        items = result.get("items") or []
        for item in items:
            if not isinstance(item, dict):
                continue
            reactionType = item.get("reaction_type")
            if isinstance(reactionType, dict):
                emoji = str(reactionType.get("emoji_type") or "")
            else:
                emoji = ""

            operator = item.get("operator")
            if isinstance(operator, dict):
                opType = "app" if operator.get("operator_type") == "app" else "user"
                opId = str(operator.get("operator_id") or "")
            else:
                opType = ""
                opId = ""

            reactions.append(
                FeishuReaction(
                    reactionId=str(item.get("reaction_id") or ""),
                    emojiType=emoji,
                    operatorType=opType,
                    operatorId=opId,
                )
            )

        pageToken = result.get("page_token")
        hasMore = result.get("has_more") is True and bool(pageToken)

    return reactions

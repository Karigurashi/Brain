"""序列化/反序列化工具类。

四种转换，覆盖对象 ↔ JSON ↔ dict 全路径：
- ToJson:   对象 → JSON 字符串
- ToDict:   对象 → dict
- FromJson: JSON 字符串 → 对象
- FromDict: dict → 对象
"""

from __future__ import annotations

import json

import orjson
from dataclasses import fields, is_dataclass
from enum import Enum, IntEnum
from typing import Any, Optional, Type, TypeVar, Union, get_args, get_origin, get_type_hints

T = TypeVar("T")

_TYPE_HINTS_CACHE: dict[type, dict[str, Any]] = {}


def _GetTypeHints(cls: type) -> dict[str, Any]:
    """缓存 get_type_hints 结果，避免重复解析字符串注解。

    get_type_hints 在大量 dataclass 反序列化时是主要性能瓶颈
    （如在会话恢复时逐条消息调用），缓存后可消除 99%+ 的调用。
    """
    hints = _TYPE_HINTS_CACHE.get(cls)
    if hints is not None:
        return hints
    try:
        hints = get_type_hints(cls)
    except Exception:
        hints = {}
    _TYPE_HINTS_CACHE[cls] = hints
    return hints


class SerializeUtil:
    """序列化静态工具类，提供对象 ↔ JSON ↔ dict 四种转换。"""

    # ==================== 公开 API ====================

    @staticmethod
    def ToJson(obj: Any, indent: Optional[int] = None) -> str:
        """对象 → JSON 字符串。

        Args:
            obj: 任意 Python 对象（dataclass / Pydantic / 普通对象等）。
            indent: 可选，缩进空格数，None 表示紧凑输出。

        Example:
            jsonStr = SerializeUtil.ToJson(config, indent=2)
        """
        option = orjson.OPT_INDENT_2 if indent is not None else 0
        try:
            return orjson.dumps(obj, default=SerializeUtil._Default, option=option).decode("utf-8")
        except TypeError as exc:
            # orjson 不支持 64 位以上整数（如 uuid.uuid4().int 的 128 位值），
            # 回退到标准库 json 处理
            if "Integer exceeds 64-bit range" not in str(exc):
                raise
            return json.dumps(obj, default=SerializeUtil._Default, indent=indent, ensure_ascii=False)

    @staticmethod
    def ToDict(obj: Any) -> Any:
        """对象 → dict / list，直接递归转换，不走 JSON 往返。

        Example:
            d = SerializeUtil.ToDict(config)
        """
        if obj is None or isinstance(obj, (bool, float, str)):
            return obj
        if isinstance(obj, IntEnum):
            return int(obj)
        if isinstance(obj, Enum):
            return obj.value
        if isinstance(obj, int):
            return obj
        if is_dataclass(obj) and not isinstance(obj, type):
            return {f.name: SerializeUtil.ToDict(getattr(obj, f.name)) for f in fields(obj) if f.init}
        if isinstance(obj, (list, tuple)):
            return [SerializeUtil.ToDict(item) for item in obj]
        if isinstance(obj, dict):
            return {k: SerializeUtil.ToDict(v) for k, v in obj.items()}
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        return obj

    @staticmethod
    def FromJson(jsonStr: str, targetType: Optional[Type[T]] = None) -> Any:
        """JSON 字符串 → 对象。

        自动移除 JSON 中的 // 和 /* */ 注释后再解析。

        Args:
            jsonStr: JSON 字符串（支持注释）。
            targetType: 可选，目标类型（Pydantic BaseModel / dataclass / 普通类）。
                       传入时返回强类型实例，不传则返回 dict/list。

        Example:
            config = SerializeUtil.FromJson(jsonStr, ModelConfig)
        """
        cleaned = SerializeUtil._StripJsonComments(jsonStr)
        if targetType is None:
            return orjson.loads(cleaned)
        return SerializeUtil._DeserializeTyped(cleaned, targetType)

    @staticmethod
    def FromDict(data: dict[str, Any], targetType: Type[T]) -> T:
        """dict → 对象。

        自动识别类型：Pydantic BaseModel > dataclass > 普通类。

        Example:
            config = SerializeUtil.FromDict(agentData, AgentConfig)
        """
        if hasattr(targetType, "model_validate"):
            return targetType.model_validate(data)
        if hasattr(targetType, "__dataclass_fields__"):
            return SerializeUtil._DataclassFromDict(targetType, data)
        return targetType(**data)

    # ==================== 内部实现 ====================

    @staticmethod
    def _DeserializeTyped(jsonStr: str, targetType: Type[T]) -> T:
        """JSON 字符串 → 指定类型实例（内部，由 FromJson 调用）。

        注意：调用方应已提前移除注释再传入。
        """
        if hasattr(targetType, "model_validate"):
            return targetType.model_validate_json(jsonStr)

        data = orjson.loads(jsonStr)

        if hasattr(targetType, "__dataclass_fields__"):
            return SerializeUtil._DataclassFromDict(targetType, data)

        if isinstance(data, dict):
            return targetType(**data)
        return targetType(data)

    @staticmethod
    def _DataclassFromDict(
        cls: type,
        data: dict[str, Any],
        fieldGroups: Optional[dict[str, Optional[str]]] = None,
        overrideDefaults: Optional[dict[str, Any]] = None,
    ) -> Any:
        """dict → dataclass 实例（内部使用）。

        每个字段按优先级取值：
        1. data[group][fieldName] — fieldGroups 指定的嵌套分组
        2. data[fieldName] — 顶层扁平键
        3. field.default — dataclass 声明的默认值
        4. overrideDefaults[fieldName] — 调用方覆盖默认值

        支持递归反序列化嵌套 dataclass 和 list[Dataclass]。
        """
        if fieldGroups is None:
            fieldGroups = {}
        if overrideDefaults is None:
            overrideDefaults = {}

        hints = _GetTypeHints(cls)

        kwargs: dict[str, Any] = {}
        for f in fields(cls):
            if not f.init:
                continue
            group = fieldGroups.get(f.name)
            default = overrideDefaults.get(f.name, f.default)

            if group is not None:
                groupData = data.get(group, {})
                if not isinstance(groupData, dict):
                    groupData = data
                value = groupData.get(f.name, data.get(f.name, default))
            else:
                value = data.get(f.name, default)

            fieldType = hints.get(f.name, f.type)
            kwargs[f.name] = SerializeUtil._DeserializeField(fieldType, value)

        return cls(**kwargs)

    @staticmethod
    def _DeserializeField(fieldType: Any, value: Any) -> Any:
        """递归反序列化字段值，处理嵌套 dataclass、Optional[list[Dataclass]]。"""
        if value is None:
            return None

        origin = get_origin(fieldType)

        # list[Dataclass]
        if origin is list:
            args = get_args(fieldType)
            if args and is_dataclass(args[0]):
                return [SerializeUtil._DataclassFromDict(args[0], item) for item in value]
            return value

        # Optional[list[Dataclass]] / Optional[Dataclass]
        if origin is Union:
            args = get_args(fieldType)
            nonNoneTypes = [a for a in args if a is not type(None)]
            if len(nonNoneTypes) == 1:
                innerType = nonNoneTypes[0]
                return SerializeUtil._DeserializeField(innerType, value)
            return value

        # 直接嵌套 dataclass
        if is_dataclass(fieldType) and isinstance(value, dict):
            return SerializeUtil._DataclassFromDict(fieldType, value)

        # 枚举类型（IntEnum / StrEnum 等），反序列化时从原始值还原
        if isinstance(fieldType, type) and issubclass(fieldType, Enum):
            return fieldType(value)

        return value

    @staticmethod
    def _StripJsonComments(jsonStr: str) -> str:
        """移除 JSON 字符串中的 // 和 /* */ 注释，保留字符串字面量内的内容。

        Args:
            jsonStr: 原始 JSON 字符串。

        Returns:
            移除注释后的纯净 JSON 字符串。
        """
        result: list[str] = []
        i = 0
        n = len(jsonStr)
        while i < n:
            ch = jsonStr[i]
            # 字符串字面量 — 逐字符原样保留（含内部转义）
            if ch == '"':
                result.append('"')
                i += 1
                while i < n:
                    if jsonStr[i] == '\\':
                        result.append(jsonStr[i:i + 2])
                        i += 2
                    elif jsonStr[i] == '"':
                        result.append('"')
                        i += 1
                        break
                    else:
                        result.append(jsonStr[i])
                        i += 1
            # // 单行注释
            elif i + 1 < n and jsonStr[i] == '/' and jsonStr[i + 1] == '/':
                i += 2
                while i < n and jsonStr[i] != '\n':
                    i += 1
            # /* */ 多行注释
            elif i + 1 < n and jsonStr[i] == '/' and jsonStr[i + 1] == '*':
                i += 2
                while i + 1 < n:
                    if jsonStr[i] == '*' and jsonStr[i + 1] == '/':
                        i += 2
                        break
                    i += 1
            else:
                result.append(ch)
                i += 1
        return ''.join(result)

    @staticmethod
    def _Default(obj: Any) -> Any:
        """orjson 序列化失败时的回落回调。

        orjson 原生支持 datetime / UUID / dataclass（需 OPT_SERIALIZE_DATACLASS），
        此处处理 IntEnum 等自定义类型。
        """
        if is_dataclass(obj) and not isinstance(obj, type):
            return {f.name: getattr(obj, f.name) for f in fields(obj) if f.init}
        if isinstance(obj, IntEnum):
            return int(obj)
        if isinstance(obj, Enum):
            return obj.value
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        raise TypeError(f"Type not JSON serializable: {type(obj).__name__}")

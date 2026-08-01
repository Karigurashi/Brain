"""飞书 API 错误处理工具。"""

from __future__ import annotations

from typing import Any, Optional


class LarkApiError(Exception):
    """带飞书业务 code 的 API 错误，供限流/表格超限等分支识别。"""

    def __init__(self, code: int, msg: str, api: str = "") -> None:
        prefix = f"{api} " if api else ""
        super().__init__(f"{prefix}FAILED: code={code}, msg={msg}")
        self.code = code
        self.msg = msg
        self.api = api


def _CoerceCode(value: Any) -> Optional[int]:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            parsed = int(value)
            return parsed
        except ValueError:
            return None
    return None


def ExtractLarkApiCode(err: Any) -> Optional[int]:
    if err is None:
        return None
    if isinstance(err, LarkApiError):
        return err.code
    if hasattr(err, "code"):
        code = _CoerceCode(getattr(err, "code"))
        if code is not None:
            return code
    if not isinstance(err, dict):
        if hasattr(err, "response"):
            response = getattr(err, "response")
            if isinstance(response, dict):
                data = response.get("data")
                if isinstance(data, dict):
                    return _CoerceCode(data.get("code"))
        return None

    code = _CoerceCode(err.get("code"))
    if code is not None:
        return code
    data = err.get("data")
    if isinstance(data, dict):
        code = _CoerceCode(data.get("code"))
        if code is not None:
            return code
    response = err.get("response")
    if isinstance(response, dict):
        responseData = response.get("data")
        if isinstance(responseData, dict):
            return _CoerceCode(responseData.get("code"))
    return None


def AssertLarkOk(res: dict[str, Any], api: str = "") -> None:
    code = res.get("code", 0)
    if not code or code == 0:
        return
    msg = str(res.get("msg") or f"Feishu API error (code: {code})")
    raise LarkApiError(int(code), msg, api=api)


def FormatLarkError(err: Any) -> str:
    if err is None:
        return "None"
    if isinstance(err, BaseException):
        code = ExtractLarkApiCode(err)
        msg = getattr(err, "msg", None)
        if code is not None and msg:
            return str(msg)
        return str(err)
    if isinstance(err, dict):
        code = ExtractLarkApiCode(err)
        msg = err.get("msg")
        if code is not None and msg:
            return str(msg)
        return str(err.get("message", err))
    return str(err)

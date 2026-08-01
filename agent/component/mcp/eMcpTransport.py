"""MCP 传输协议枚举 —— 对标 Claude Code MCP 的三种传输方式。"""

from enum import IntEnum

# IntEnum ↔ 字符串标签映射表（供序列化使用）
_TRANSPORT_LABELS: dict[int, str] = {0: "stdio", 1: "http", 2: "sse"}
_TRANSPORT_LOOKUP: dict[str, int] = {"stdio": 0, "http": 1, "sse": 2}


class EMcpTransport(IntEnum):
    """MCP Server 通信的传输协议。

    使用 IntEnum 而非 str 基类，遵循项目枚举规范。
    对外序列化（.mcp.json）时通过 ToLabel / FromLabel 完成整型↔字符串映射。

    Attributes:
        STDIO: 本地子进程，通过 stdin/stdout 通信（最常用）。
        HTTP: 远程服务，通过 streamable HTTP 通信（推荐用于远程）。
        SSE: 远程服务，通过 Server-Sent Events 通信（已废弃，向后兼容）。
    """

    STDIO = 0
    HTTP = 1
    SSE = 2

    def ToLabel(self) -> str:
        """返回 .mcp.json 兼容的字符串标签。"""
        return _TRANSPORT_LABELS[self.value]

    @staticmethod
    def FromLabel(label: str) -> "EMcpTransport":
        """从字符串标签反查枚举，未知标签回退 STDIO。"""
        return EMcpTransport(_TRANSPORT_LOOKUP.get(label, 0))

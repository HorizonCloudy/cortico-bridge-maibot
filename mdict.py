"""CBP msg 帧 → 宿主 MessageDict 造形。十七键逐字钉自
`src/plugin_runtime/host/message_utils.py:45-62 @478f671e6`（安装件与仓库件等价，r-maibot §0）。

桥规约（蓝图 L84 + r-maibot §9/§10）：
- 只交裸 dict，不构造 `MaiMessages`（顶层 `maibot_sdk` 根本没有该名，ImportError 实测；
  旧 dataclass 的 `raw_message` 与宿主 `MessageDict.raw_message`＝段列表同名不同义，禁混）。
- 「dict 只增不改」：本件产出的键集合恒等于十七键；下游任何腿不得改写既有键。
- raw_message = CBP segments 原样（data 值全字符串，v11 同构形），语义与 SDK 旧
  MaiMessages.raw_message 不同，不做转换。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

MESSAGE_DICT_KEYS = (
    "message_id", "timestamp", "received_at", "platform", "account_id", "scope",
    "message_info", "raw_message", "is_mentioned", "is_at", "is_emoji", "is_picture",
    "is_command", "is_notify", "session_id", "reply_to", "processed_plain_text",
)

_SEG_BOOLS = {"at": "is_at", "face": "is_emoji", "image": "is_picture"}


def _seg_text(segments: list[dict[str, Any]]) -> str:
    return "".join(
        str(seg.get("data", {}).get("text", ""))
        for seg in segments if isinstance(seg, dict) and seg.get("type") == "text"
    )


def frame_to_message_dict(
    frame: dict[str, Any],
    *,
    platform: str = "cortico",
    account_id: str | None = None,
    scope: str = "",
) -> dict[str, Any]:
    """CBP msg 帧 → 十七键 MessageDict。ts（float 秒）按宿主写法拆两份。"""
    segments = [s for s in (frame.get("segments") or []) if isinstance(s, dict)]
    text = _seg_text(segments)
    ts = float(frame.get("ts", 0.0))
    sender = frame.get("sender") or {}
    kind = str(frame.get("kind") or "other")
    user_info: dict[str, Any] = {
        "user_id": str(sender.get("id", "")),
        "user_nickname": str(sender.get("name", "")),
    }
    group_info = (
        {"group_id": str(frame.get("conv", "")), "group_name": ""} if kind == "group" else None
    )
    md: dict[str, Any] = {
        "message_id": str(frame.get("id", "")),
        "timestamp": str(ts),  # 宿主写法：str(float 秒)（message_utils.py:431）
        "received_at": datetime.fromtimestamp(ts).isoformat(timespec="microseconds"),  # :451
        "platform": platform,
        "account_id": account_id,
        "scope": scope,
        "message_info": {
            "user_info": user_info,
            "group_info": group_info,
            "additional_config": {"cbp_kind": kind, "cbp_conv": str(frame.get("conv", ""))},
        },
        "raw_message": segments,
        "is_mentioned": kind == "mention",
        "is_at": any(s.get("type") == "at" for s in segments),
        "is_emoji": any(s.get("type") == "face" for s in segments),
        "is_picture": any(s.get("type") == "image" for s in segments),
        "is_command": text.startswith("/"),
        "is_notify": False,
        "session_id": str(frame.get("conv", "")),  # conv 即会话键（§3.2 表：conv=stream_id 口径由宿主路由）
        "reply_to": None,
        "processed_plain_text": text or None,
    }
    extra = {k for k in md if k not in MESSAGE_DICT_KEYS}
    missing = [k for k in MESSAGE_DICT_KEYS if k not in md]
    if extra or missing:  # 键表自检：任何一侧漂移立刻炸，不带病上线
        raise AssertionError(f"MessageDict 键集漂移 extra={extra} missing={missing}")
    return md


def route_kwargs(frame: dict[str, Any]) -> dict[str, Any]:
    """ctx.gateway.route_message 的星号后入参，kwargs 形（r-maibot §3 别名签名逐字）。"""
    return {
        "route_metadata": None,
        "external_message_id": str(frame.get("id", "")),
        "dedupe_key": str(frame.get("conv", "")) + ":" + str(frame.get("id", "")),
    }

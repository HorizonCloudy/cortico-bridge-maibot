"""ON_MESSAGE 镜像腿。形状铁证（r-maibot §9/§10，由 INFERENCE 升 FACT）：

宿主派发旧/新 handler 收到的是裸 dict —— `legacy_adapter.py:370` 实测 kwargs 分支
原样传 dict；对 dict 做属性访问（`message.plain_text`）必 `AttributeError`。
所以本件唯一读法 = 键访问。镜像只观察、不拦截（intercept_message=False），
不改宿主任何消息，也不发 RPC（第一切片出站腿 sender.py 不在范围）。
"""
from __future__ import annotations

from typing import Any, Callable

from maibot_sdk import EventHandler
from maibot_sdk.types import EventType

#: 桥注入的镜像出口：接 (frame_dict)；None 时静默计数（骨架期 Cortico 侧不在场属常态）
Sink = Callable[[dict[str, Any]], Any]

MIRROR_FIELDS = ("message_id", "session_id", "platform", "processed_plain_text")


@EventHandler(
    "cortico_mirror",
    description="CBP 镜像腿：宿主消息按 dict 键读，转发给桥客户端",
    event_type=EventType.ON_MESSAGE,
    intercept_message=False,
)
async def mirror_on_message(self: Any, message: Any, **_: Any) -> None:
    """@EventHandler 组件腿。宿主送来的 message 一律按 dict 读；非 dict 直接丢。

    注意本函数不 import compat、不构造 MaiMessages、不做属性访问。
    """
    if not isinstance(message, dict):
        return
    sink = getattr(self, "_mirror_sink", None)
    if sink is None:
        self._mirror_seen = int(getattr(self, "_mirror_seen", 0)) + 1
        return
    view = {k: message.get(k) for k in MIRROR_FIELDS}
    view["raw_message"] = message.get("raw_message") or []
    sink(view)


def demo_attribute_trap(message: dict[str, Any]) -> bool:
    """自检辅助：证明 dict 属性访问必炸（r-maibot §9 实测口径的仓内留档）。"""
    try:
        _ = message.plain_text  # type: ignore[attr-defined]
    except AttributeError:
        return True
    return False

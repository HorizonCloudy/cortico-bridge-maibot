"""CBP WS 客户端：外拨 Cortico 侧 maibot world 监听口（端口只从 pins.json 取）。

骨架边界：不监听、不起宿主、不自建 RPC 服务——MaiBot Runner 子进程只有三个原始 RPC
（cap.call / host.route_message / host.update_message_gateway_state，context.py:137-143
@f9984673d），从模型上就没打算让插件开服务，所以桥=纯外拨客户端（蓝图 §2.2 MaiBot 卡）。
入站链：CBP `msg` → mdict.frame_to_message_dict → ctx.gateway.route_message（kwargs 形）。
出站链（send 腿）阶段二再开，本件只把帧送到 host_to_world 队列。
"""
from __future__ import annotations

import asyncio
from typing import Any

from . import cbp, mdict, pins as pins_mod
from .caps import BRIDGE_CAPS

AGENT_NAME = "cortico-bridge-maibot"
AGENT_VERSION = "0.1.0"
AGENT_SHA = "unpinned"  # 由 fleet pins 流程回填（G1）

# 重连参数照内核表（driver.ts 先例 @4725feee6，蓝图 §2.1）：base 1000ms×2、封顶 30000ms
_BACKOFF_BASE_S, _BACKOFF_CAP_S = 1.0, 30.0
# hello 之后 Cortico 侧 ready 握手等待上限（world start() 12s 放行口径，§2.3 硬规则 2）
_HANDSHAKE_TIMEOUT_S = 12.0


class BridgeClient:
    def __init__(self, plugin: Any, *, enabled: bool = False) -> None:
        self.plugin = plugin
        self.enabled = enabled
        self.connected = False
        self._rx: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._seen = 0
        self._ws: Any | None = None  # 当前连接；run() 维护，供 reply 出帧

    def uri(self) -> str:
        return pins_mod.bridge_ws_uri(pins_mod.load_pins(), "cortico_world_maibot_ws")

    def hello(self) -> dict[str, Any]:
        # F1（SECURITY-CBP.md:74，:91 指派落点即本函数）：握手首帧必须带 self。
        # 实证口结论：internal_chat.identity 返回常量聊天室坐标 {platform:"internal",
        # user_id:"owner"}（MaiBot 1.4.5 安装源 src/plugin_runtime/capabilities/
        # internal_chat.py:16-19 ← src/core/internal_chat.py:3-6），user_id 是主人、
        # bot 自己的键 "self" 不在返回值里——MaiBot 拿不到自身机器人账号主键。
        # 按 §2 规则 4 显式降级：honest 空 self + proven:false（不许拿报不了当不带 self，
        # 也不许拿常量主人坐标冒充实证）。后果：本腿自回声抑制不可用，Cortico 侧走
        # self-unknown 降级；self_echo cap 已在 caps.py 不宣（SECURITY-CBP.md:77）。
        # shortcut: 升级时机=宿主实证口给出 bot 自身账号主键后，填 id/name 改
        # proven:true，且 self_echo cap 须两侧同批再宣。
        return cbp.hello_frame(
            AGENT_NAME, AGENT_VERSION, AGENT_SHA,
            caps=list(BRIDGE_CAPS),
            # call 腿未接线（发信腿属阶段二 sender.py 工单，见 README「欠账」），
            # 零可达工具就零申报——申报调不通的 maibot_send/maibot_streams 是谎言。
            tools=[],
            self_decl=cbp.make_self_decl(),
        )

    async def route_frame(self, frame: dict[str, Any]) -> bool:
        """CBP msg → 宿主 route_message。返回宿主 accepted 位；False=未接收
        （错误约定：重试一次仍 False 即向 Cortico 侧报 60007，蓝图 §3.4-2）。"""
        if frame.get("t") != "msg":
            return False
        md = mdict.frame_to_message_dict(frame)
        kw = mdict.route_kwargs(frame)
        ctx = self.plugin.ctx  # 链根必须落 `ctx`：manifest_scan 只认 ctx/self.ctx/plugin.ctx 三根
        route = ctx.gateway.route_message
        return await route("cbp_gateway", md, **kw)

    async def feed(self, raw: str | bytes) -> None:
        """收帧入口。坏帧吞掉（硬规则）；tick 只刷新连接活性。"""
        frame = cbp.decode(raw)
        if frame is None:
            self._seen += 1
            return
        if frame["t"] in ("hello", "ready", "catalog"):
            self.connected = True
            return
        if frame["t"] == "msg":
            await self.route_frame(frame)
            return
        if frame["t"] == "call":
            # 最小 call 腿：桥零可达工具（tools 申报为空），到货的 call 一律回
            # 60002 capability_unavailable——不许静默，静默会被内核 30s 相关超时
            # 译成 60007（CBP-v1.json:545）。码与 neko 同（__init__.py:173）。
            await self._send(cbp.make_frame(
                "reply", rid=frame["rid"], ok=False,
                error={"code": 60002, "message": "cortico-bridge-maibot: 本桥零申报工具，发信腿属阶段二工单"},
            ))

    async def _send(self, frame: dict[str, Any]) -> None:
        """出帧唯一口；没连接（_ws None）就丢，异常只断链、不抛穿 run 语义。"""
        if self._ws is None:
            return
        try:
            await self._ws.send(cbp.encode(frame))
        except Exception:
            pass

    async def run(self) -> None:
        """外拨循环；永不抛出（start 语义照内核 driver）。enabled 缺省关，误启不联网。"""
        if not self.enabled:
            return
        try:
            import websockets
        except ImportError:  # 环境缺依赖只降级，不崩宿主
            return
        delay = _BACKOFF_BASE_S
        while True:
            try:
                async with websockets.connect(self.uri(), open_timeout=12) as ws:
                    self._ws = ws
                    await ws.send(cbp.encode(self.hello()))
                    self.connected = True
                    delay = _BACKOFF_BASE_S
                    async for raw in ws:
                        await self.feed(raw)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            self.connected = False
            self._ws = None
            await asyncio.sleep(delay)
            delay = min(delay * 2, _BACKOFF_CAP_S)

    def start(self) -> None:
        if self.enabled and self._task is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
            self._task = loop.create_task(self.run())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
        self.connected = False

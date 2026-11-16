"""CBP WS 客户端：外拨 Cortico 侧 maibot world 监听口（端口只从 pins.json 取）。

骨架边界：不监听、不起宿主、不自建 RPC 服务——MaiBot Runner 子进程只有三个原始 RPC
（cap.call / host.route_message / host.update_message_gateway_state，context.py:137-143
@f9984673d），从模型上就没打算让插件开服务，所以桥=纯外拨客户端（蓝图 §2.2 MaiBot 卡）。
入站链：CBP `msg` → mdict.frame_to_message_dict → ctx.gateway.route_message（kwargs 形）。
出站链：call → sender.handle_call → reply；turn 账本记 route_frame 见过的入站 msg 帧 id（F3/G-K1-C6）。
"""
from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Any

from . import cbp, mdict, pins as pins_mod, sender
from .caps import BRIDGE_CAPS

AGENT_NAME = "cortico-bridge-maibot"
AGENT_VERSION = "0.1.0"
AGENT_SHA = "unpinned"  # 由 fleet pins 流程回填（G1）

# 重连参数照内核表（driver.ts 先例 @4725feee6，蓝图 §2.1）：base 1000ms×2、封顶 30000ms
_BACKOFF_BASE_S, _BACKOFF_CAP_S = 1.0, 30.0
# hello 之后 Cortico 侧 ready 握手等待上限（world start() 12s 放行口径，§2.3 硬规则 2）
_HANDSHAKE_TIMEOUT_S = 12.0
# turn 账本窗（G-K1-C6，§5.1 rid 缓存口径先例 cortico-bridge-neko/turns.py:24-25）
_TURN_TTL_S, _TURN_CAP = 300.0, 200

# hello.tools 申报面 = sender.handle_call 真实现的两支（形状照 neko __init__.py:25-29）。
# 改名/删工具必须与 sender.py 同批，且 fleet world.ts PEER_CAPABILITIES 同批镜像
# （hello-authority 闸；SECURITY-CBP §7 N3「申报=可达」）。
# 不写类型注解：fleet hello-authority.test.ts:33 按文本回读本常量，注解里的 `]` 会截断它的正则。
_BRIDGE_TOOLS = [
    {"name": "maibot_send", "risk": "write", "confirm_required": True},
    {"name": "chat.get_all_streams", "risk": "read", "confirm_required": False},
]


class BridgeClient:
    def __init__(self, plugin: Any, *, enabled: bool = False) -> None:
        self.plugin = plugin
        self.enabled = enabled
        self.connected = False
        self._rx: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._seen = 0
        self._ws: Any | None = None  # 当前连接；run() 维护，供 reply 出帧
        # F3 turn 账本（G-K1-C6）：route_frame 见过的入站 msg 帧 id → 失效时刻。
        self._turns: "OrderedDict[str, float]" = OrderedDict()

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
            # 发信腿已接线（sender.py，工单 K1）：申报面必须等于真可达面，
            # fleet world.ts PEER_CAPABILITIES 同批镜像（SECURITY-CBP §7 N3）。
            tools=list(_BRIDGE_TOOLS),
            self_decl=cbp.make_self_decl(),
        )

    def _record_turn(self, frame: dict[str, Any]) -> None:
        fid = frame.get("id")
        if not isinstance(fid, str) or not fid:
            return
        self._turns.pop(fid, None)
        self._turns[fid] = time.monotonic() + _TURN_TTL_S
        while len(self._turns) > _TURN_CAP:
            self._turns.popitem(last=False)

    def _turn_seen(self, turn: Any) -> bool:
        if not isinstance(turn, str):
            return False
        exp = self._turns.get(turn)
        if exp is None or time.monotonic() > exp:
            self._turns.pop(turn, None)
            return False
        return True

    async def route_frame(self, frame: dict[str, Any]) -> bool:
        """CBP msg → 宿主 route_message。返回宿主 accepted 位；False=未接收
        （错误约定：重试一次仍 False 即向 Cortico 侧报 60007，蓝图 §3.4-2）。"""
        if frame.get("t") != "msg":
            return False
        self._record_turn(frame)  # G-K1-C6：call.turn 的权威来源=这张入站记录
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
            rid = frame["rid"]
            if not self._turn_seen(frame.get("turn")):
                # F3：turn 查无入站记录拒执行（CBP-v1.json:499；neko __init__.py:140-143 先例）。
                await self._send(cbp.make_frame(
                    "reply", rid=rid, ok=False,
                    error={"code": 60004, "message": f"unknown_session: turn={frame.get('turn')!r} 无对应入站记录"},
                ))
                return
            ctx = self.plugin.ctx if self.plugin is not None else None
            await self._send(await sender.handle_call(ctx, frame))

    async def _send(self, frame: dict[str, Any]) -> bool:
        """出帧唯一口；没连接（_ws None）就丢并回报 False——cbp_gateway 的送达回执读这个位。"""
        if self._ws is None:
            return False
        try:
            await self._ws.send(cbp.encode(frame))
            return True
        except Exception:
            return False

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

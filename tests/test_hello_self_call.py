"""工单 M2：hello 的 self 申报口径 + call 处理腿。

事实源（优先级 CBP-v1.json/spec/pins.json/实测 > 手抄）：
- SECURITY-CBP.md:74：桥拨出侧第一个握手帧必带 self；SECURITY-CBP.md:91 指派落点
  = `cortico-bridge-maibot/client.py:39-44` 填 internal_chat.identity 结果。
- 宿主实证（读 MaiBot==1.4.5 安装源，非起宿主）：internal_chat.identity 返回常量
  聊天室坐标 {platform:"internal", user_id:"owner"}
  （site-packages/src/plugin_runtime/capabilities/internal_chat.py:16-19 ←
  site-packages/src/core/internal_chat.py:3-6）。user_id 是主人、不是 bot 自己；
  bot 在 internal 平台的键 "self"（internal_chat.py:6）根本不在返回值里。
  → MaiBot 侧拿不到自己的机器人账号主键，按 §2 规则 4 显式降级：honest 空 self +
  proven:false，本腿自回声抑制不可用（README「self 申报」节同口径）。
- SECURITY-CBP.md:77：self_echo cap 不得与 proven:true 之外同现——proven:false 时
  报该 cap 即 caps-lie，闸在本文件钉死。
- call 腿：K1（sender.py）已接线，hello.tools 申报两支真可达面（`maibot_send`、
  `chat.get_all_streams`）；申报不可达工具=对模型撒谎（SECURITY-CBP §7 N3），
  本文件 `test_hello_advertises_only_reachable_tools` 是它的镜像闸。到货 call
  不得静默——静默会被内核 30s 相关超时译成 60007（CBP-v1.json:545）。先例 neko
  `__init__.py:173` 回 60002 capability_unavailable，本仓同码。
"""
from __future__ import annotations

import asyncio
import inspect

SELF_HONEST = {"id": "", "name": "", "proven": False}  # hello_proven_false 逐字（conformance.json）

ACTOR = {"platform": "onebot", "conv": "c1", "member": {"id": "u1", "name": "n"},
         "anon": "identified"}  # call_full_actor_bound 形（F3）


def test_hello_self_declared_downgrade_explicitly(pkg):
    """self 必须是显式诚实降级值，且 proven:false 时绝不宣 self_echo（SECURITY-CBP:77）。"""
    h = pkg.client.BridgeClient(plugin=None).hello()
    assert h["self"] == SELF_HONEST, f"self 不再是诚实降级值：{h['self']!r}"
    assert "self_echo" not in h["caps"], "proven:false 同报 self_echo = caps-lie（SECURITY-CBP:77）"
    assert pkg.cbp.decode(pkg.cbp.encode(h)) is not None, "hello 出帧必须过同一 codec 校验"


def test_hello_advertises_only_reachable_tools(pkg):
    """申报面 = sender.handle_call 真分支（SECURITY-CBP §7 N3）。

    K1 接线后 tools 不再为空。本测试是 N3 的镜像闸：在 client._BRIDGE_TOOLS
    加名却没在 sender 落分支，或反过来，这里立刻红。fleet 侧
    hello-authority.test.ts 按文本回读同一常量，两闸同批改。
    """
    h = pkg.client.BridgeClient(plugin=None).hello()
    declared = [t["name"] for t in h["tools"]]
    src = inspect.getsource(pkg.sender.handle_call)
    wired = [n for n in declared if f'tool == "{n}"' in src]
    assert declared == wired, f"申报却未接线的工具：{set(declared) - set(wired)}"
    assert declared == ["maibot_send", "chat.get_all_streams"], f"申报面漂移：{declared}"


def test_inbound_call_gets_error_reply_not_silence(pkg):
    """到货 call：回 reply{ok:false, code:60002, rid 回填}，不拖成内核 60007。

    工具名取未申报也未接线的 `chat.open_session`：`maibot_send` 自 K1 起走真腿，
    拿它测 60002 会测成 60008。turn 先由入站 msg 帧记账（C6），否则先撞 60004。
    """
    client = pkg.client.BridgeClient(plugin=None)
    sent: list[str] = []

    class FakeWs:
        async def send(self, data: str) -> None:
            sent.append(data)

    client._ws = FakeWs()
    # 先让 turn="m1" 在账本里存在（C6 的权威来源=入站 msg 帧记录）。端到端的
    # 「入站 msg → call 可用」链路由 cortico-bridge-maibot/tests/test_sender.py
    # 的 test_client_records_inbound_msg_turn_and_call_flows_to_sender 钉，
    # 本例只测 60002 一支，不重复拽宿主注入面。
    client._record_turn({"t": "msg", "id": "m1"})
    pre = len(sent)
    call = pkg.cbp.make_frame("call", id="cl1", ts=1.0, rid="q9", tool="chat.open_session",
                              args={}, turn="m1", actor=dict(ACTOR))
    asyncio.run(client.feed(pkg.cbp.encode(call)))
    fresh = sent[pre:]
    assert len(fresh) == 1, "call 被吞：桥静默会被内核 30s 超时译成 60007（CBP-v1.json:545）"
    reply = pkg.cbp.decode(fresh[0])
    assert reply is not None and reply["t"] == "reply", reply
    assert reply["rid"] == "q9" and reply["ok"] is False
    assert reply["error"]["code"] == 60002, "60002=capability_unavailable，与 neko 同码（__init__.py:173）"


def test_call_reply_without_ws_never_raises(pkg):
    """没连接（无 _ws）时帧无处发也不许抛——run 循环语义=永不抛出。"""
    client = pkg.client.BridgeClient(plugin=None)
    call = pkg.cbp.make_frame("call", id="cl2", ts=1.0, rid="q10", tool="x",
                              args={}, turn="m1", actor=dict(ACTOR))
    asyncio.run(client.feed(pkg.cbp.encode(call)))

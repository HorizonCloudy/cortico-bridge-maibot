"""工单 K1-maibot-sender 验收：`PY312M -I -m pytest tests/test_sender.py -q`。

锁契约审议条件（gate.md §4，G-K1-C1..C6）：
- C1 到货 call 永远回 reply（成功 ok:true＋可选 text，失败 ok:false＋error），任何分支不静默。
- C4 cbp_gateway 成功回 {success:True,external_message_id:...}、失败回 {success:False,error:...}，
  不许 None（plugin_driver.py:221-227 @478f671e6 把 None 判 SENT 假成功）。
- C5 确认失败码收进单一常量（U1 未裁，起点 60008）；60007 绝不表达确认失败。
- C6 turn 查无入站记录 → 60004（CBP-v1.json:499；neko __init__.py:140-143 先例）。
- stream_id 解析＝conv 恒等直通（gate §1.8：message_utils.py:564/446、data.py:261-275 @478f671e6）。
全程本地 FakeCtx，零宿主、零网络。
"""
from __future__ import annotations

import asyncio
import json

import support


class FakeChat:
    def __init__(self, streams):
        self.streams = streams
        self.calls = 0

    async def get_all_streams(self, platform="qq"):
        self.calls += 1
        return self.streams


class FakeGateway:
    def __init__(self):
        self.routed = []

    async def route_message(self, name, md, **kw):
        self.routed.append((name, md))
        return True


class FakeCtx:
    """记录 cap.call 原始载荷（层1 失败要读 error 文本就得走这条，context.py:137-143 @f9984673d）。"""

    def __init__(self, *, raw=None, exc=None, streams=None):
        self.raw = raw
        self.exc = exc
        self.cap_calls = []
        self.chat = FakeChat(streams if streams is not None else [])
        self.gateway = FakeGateway()

    async def call_host_method(self, method, *, plugin_id="", payload=None, timeout_ms=None):
        self.cap_calls.append((method, payload))
        if self.exc is not None:
            raise self.exc
        return self.raw


def call_frame(tool, args, *, rid="q1", turn="t1"):
    return {"v": 1, "t": "call", "id": "c1", "ts": 1.0, "rid": rid,
            "tool": tool, "args": args, "turn": turn,
            "actor": {"platform": "onebot", "conv": "c1", "member": {"id": "u1", "name": "n"}, "anon": "identified"}}


def handle(pkg, ctx, tool, args, **kw):
    reply = asyncio.run(pkg.sender.handle_call(ctx, call_frame(tool, args, **kw)))
    assert pkg.cbp.decode(pkg.cbp.encode(reply)) is not None, f"reply 过不了同一 codec：{reply!r}"
    return reply


def test_send_success_replies_ok_true_with_message_id(pkg):
    ctx = FakeCtx(raw={"success": True, "sent": True, "message_id": "m9"})
    reply = handle(pkg, ctx, "maibot_send", {"conv": "s1", "text": "hi"})
    assert reply["ok"] is True and reply["rid"] == "q1"
    assert "m9" in reply.get("text", "")


def test_send_resolution_is_conv_identity(pkg):
    """conv==stream_id 直通：载荷逐字带 capability/args（宿主 core.py:450-451 @478f671e6 读这两个键）。"""
    ctx = FakeCtx(raw={"success": True, "sent": True, "message_id": "m1"})
    handle(pkg, ctx, "maibot_send", {"conv": "sess-42", "text": "yo"})
    method, payload = ctx.cap_calls[0]
    assert method == "cap.call" and payload["capability"] == "send.text"
    assert payload["args"]["stream_id"] == "sess-42" and payload["args"]["text"] == "yo"


def test_send_business_failure_keeps_host_error_text(pkg):
    """代理折叠丢 error（context.py:309-334 @f9984673d）→ 走原始层必须把宿主 error 文本带回 reply。"""
    ctx = FakeCtx(raw={"success": False, "error": "未找到聊天流"})
    reply = handle(pkg, ctx, "maibot_send", {"conv": "gone", "text": "hi"})
    assert reply["ok"] is False
    assert "未找到聊天流" in reply["error"]["message"]
    assert reply["error"]["code"] == pkg.sender.CONFIRMED_FAILED_CODE


def test_send_confirmed_failure_code_is_single_constant_not_60007(pkg):
    assert pkg.sender.CONFIRMED_FAILED_CODE == 60008, "U1 未裁：起点 60008（conformance.json:92），单点收敛"
    assert 60007 not in (pkg.sender.CONFIRMED_FAILED_CODE,), "60007=send_uncertain，绝不表达确认失败"


def test_send_transport_error_still_replies_never_silent(pkg):
    """层2 RuntimeError（授权硬拒/传输，runner_main.py:950-951 @478f671e6）不许掀翻帧泵。"""
    ctx = FakeCtx(exc=RuntimeError("未获授权能力: send.text"))
    reply = handle(pkg, ctx, "maibot_send", {"conv": "s1", "text": "hi"})
    assert reply["ok"] is False and reply["error"]["code"] == pkg.sender.CONFIRMED_FAILED_CODE


def test_unknown_tool_gets_60002(pkg):
    ctx = FakeCtx(raw={"success": True})
    reply = handle(pkg, ctx, "maibot_nope", {})
    assert reply["ok"] is False and reply["error"]["code"] == 60002


def test_streams_tool_returns_json_and_caches(pkg):
    streams = [{"stream_id": "a1", "platform": "qq"}, {"stream_id": "a2", "platform": "qq"}]
    ctx = FakeCtx(streams=streams)
    r1 = handle(pkg, ctx, "chat.get_all_streams", {})
    assert r1["ok"] is True and json.loads(r1["text"]) == streams
    assert ctx.chat.calls == 1
    r2 = handle(pkg, ctx, "chat.get_all_streams", {})
    assert json.loads(r2["text"]) == streams
    assert ctx.chat.calls == 1, "缓存表没咬住：TTL 窗内不得逐次打宿主"


def test_streams_host_failure_not_disguised_as_ok_and_not_cached(pkg):
    """宿主读腿失败回 {"success":False,"error"}、没有 streams 键（data.py:286-293 @478f671e6）；
    SDK 只在命中 result 键时拆列表（context.py:63/320-334 @f9984673d），失败字典原样透传。
    不判这层就伪装 ok:true，还把脏值缓存 300 秒（G-K1-C1 在读腿的落点）。"""
    ctx = FakeCtx(streams={"success": False, "error": "宿主炸了"})
    r1 = handle(pkg, ctx, "chat.get_all_streams", {"platform": "qqfail"}, rid="qf1")
    assert r1["ok"] is False, f"宿主失败被伪装成成功：{r1!r}"
    assert "宿主炸了" in r1["error"]["message"]
    assert r1["error"]["code"] == pkg.sender.CONFIRMED_FAILED_CODE
    handle(pkg, ctx, "chat.get_all_streams", {"platform": "qqfail"}, rid="qf2")
    assert ctx.chat.calls == 2, "失败结果不许进缓存表：TTL 窗内不得复用脏值"


def test_gateway_frame_shape_and_invalid_conv(pkg):
    md = {"session_id": "s-1", "account_id": "bot-9",
          "raw_message": [{"type": "text", "data": {"text": "yo"}}],
          "message_info": {"group_info": None}}
    frame = pkg.sender.gateway_msg_frame(md)
    assert frame is not None
    assert frame["t"] == "msg" and frame["conv"] == "s-1"
    assert frame["sender"]["id"] == "bot-9", "world 回声判据 sender.id==raw.account_id（README:64）"
    assert pkg.cbp.decode(pkg.cbp.encode(frame)) is not None
    assert frame["segments"] == [{"type": "text", "data": {"text": "yo"}}]
    assert pkg.sender.gateway_msg_frame({"session_id": "", "raw_message": []}) is None


def test_gateway_frame_stringifies_seg_values(pkg):
    """CBP seg 值全字符串（$defs/seg @CBP-v1.json:165 区）；宿主段 data 可能是 int。"""
    md = {"session_id": "s", "account_id": "b",
          "raw_message": [{"type": "at", "data": {"qq": 12345}}], "message_info": {}}
    frame = pkg.sender.gateway_msg_frame(md)
    assert frame["segments"] == [{"type": "at", "data": {"qq": "12345"}}]


def test_cbp_gateway_success_receipt_and_never_none(pkg):
    sent = []

    class FakeClient:
        async def _send(self, frame):
            sent.append(frame)
            return True

    plugin = pkg.create_plugin()
    plugin._client = FakeClient()
    res = asyncio.run(plugin.cbp_gateway(
        {"session_id": "s", "account_id": "a", "raw_message": [{"type": "text", "data": {"text": "t"}}],
         "message_info": {}}))
    assert res is not None and res["success"] is True
    assert res["external_message_id"] == sent[0]["id"]


def test_cbp_gateway_failure_receipts(pkg):
    plugin = pkg.create_plugin()
    res = asyncio.run(plugin.cbp_gateway({"session_id": "s", "account_id": "a", "raw_message": [], "message_info": {}}))
    assert res["success"] is False and res["error"], "空段回包不许假 SENT"
    plugin._client = type("C", (), {"_send": staticmethod(lambda f: asyncio.sleep(0, result=False))})()
    res2 = asyncio.run(plugin.cbp_gateway(
        {"session_id": "s", "account_id": "a", "raw_message": [{"type": "text", "data": {"text": "t"}}],
         "message_info": {}}))
    assert res2["success"] is False and res2["error"]


def test_client_call_unknown_turn_replies_60004(pkg):
    client = pkg.client.BridgeClient(plugin=None)
    sent = []

    class W:
        async def send(self, data):
            sent.append(data)

    client._ws = W()
    asyncio.run(client.feed(pkg.cbp.encode(call_frame("maibot_send", {"conv": "c", "text": "x"}, turn="nope"))))
    assert len(sent) == 1
    reply = pkg.cbp.decode(sent[0])
    assert reply["ok"] is False and reply["error"]["code"] == 60004, "turn 查无入站记录 → 60004（C6）"


def test_client_records_inbound_msg_turn_and_call_flows_to_sender(pkg):
    plugin = type("P", (), {})()
    plugin.ctx = FakeCtx(raw={"success": True, "sent": True, "message_id": "z"}, streams=[{"stream_id": "a"}])
    client = pkg.client.BridgeClient(plugin)
    sent = []

    class W:
        async def send(self, data):
            sent.append(data)

    client._ws = W()
    msg = pkg.cbp.make_frame("msg", id="t-1", ts=1.0, conv="c", sender={"id": "u", "name": "n"},
                             kind="direct", segments=[{"type": "text", "data": {"text": "hi"}}], raw={})
    asyncio.run(client.feed(pkg.cbp.encode(msg)))
    assert pkg.client.__name__ and plugin.ctx.gateway.routed, "msg 腿仍须照常注入宿主"
    asyncio.run(client.feed(pkg.cbp.encode(call_frame("chat.get_all_streams", {}, turn="t-1"))))
    reply = pkg.cbp.decode(sent[-1])
    assert reply["ok"] is True, "入站 msg 帧 id 应可当 turn 用（C6 记账点=route_frame）"


def test_hello_announces_wired_tools(pkg):
    h = pkg.client.BridgeClient(plugin=None).hello()
    names = [t["name"] for t in h["tools"]]
    assert names == ["maibot_send", "chat.get_all_streams"], "hello.tools=桥真可达面（N3）"
    for t in h["tools"]:
        assert t["risk"] in pkg.cbp.TOOL_RISKS and isinstance(t["confirm_required"], bool)

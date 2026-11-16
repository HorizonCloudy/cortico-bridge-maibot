"""MaiBot 发信腿：CBP call → capabilities 真调 + duplex 回包造帧 + 流缓存表（工单 K1）。

硬边界（r-maibot §6）：只站 capabilities 层——compat 门面 87 个公开函数里 48 个是 silent
桩，不许依赖。stream_id「解析」实为直通：conv==session_id==stream_id 恒等
（gate.md §1.8 @478f671e6：host/message_utils.py:564/446、capabilities/data.py:261-275），
缓存表只给读工具供数与节流。失败分三层（recon §5）：层1 宿主业务失败不抛、error 被 SDK
代理折叠吞掉 → 走原始 cap.call 取 error；层2 授权/传输失败抛 RuntimeError；层3 翻成 CBP
码。任何分支永远回 reply——静默会被内核 30s 相关超时译成 60007（CBP-v1.json:545）。
"""
from __future__ import annotations

import json
import time
from collections import OrderedDict
from typing import Any

from . import cbp

# 「宿主已尝试但确认投递失败」的唯一错误码（G-K1-C5）。U1 归属未裁：CBP-v1.json:277 允许
# passthrough 宿主整数码，但 send.* envelope 无整数码可抄（core.py:423-434 只回 str error），
# 故起点取在册 60008 degraded；裁决落定时只改这一行。60007 send_uncertain 绝不挪用。
CONFIRMED_FAILED_CODE = 60008

_STREAM_TTL_S = 300.0  # shortcut: 起点值（猜），照 §5.1 rid 缓存窗量级（SECURITY-CBP.md:222），非合同数；沙箱实测后校
_STREAM_CAP = 16
_streams_cache: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()


def _reply(rid: str, *, ok: bool, text: str | None = None, error: dict[str, Any] | None = None) -> dict[str, Any]:
    fields: dict[str, Any] = {"rid": rid, "ok": ok}
    if text is not None:
        fields["text"] = text
    if error is not None:
        fields["error"] = error
    return cbp.make_frame("reply", **fields)


async def _raw_send_text(ctx: Any, text: str, stream_id: str) -> Any:
    """原始层发信：代理折叠分支丢 error（context.py:116-135/309-334 @f9984673d），
    cap.call 是允许的三个原始方法之一（context.py:137-143），失败原因只有这里拿得到。"""
    return await ctx.call_host_method(
        "cap.call",
        payload={"capability": "send.text",
                 "args": {"text": text, "stream_id": stream_id, "return_details": True}},
    )


async def _call_send(ctx: Any, rid: str, args: dict[str, Any]) -> dict[str, Any]:
    # call.args 形 = {conv, text, segments?}，required [conv,text]（_BUILD-PLAN.md:178-180，recon §3）
    env = await _raw_send_text(ctx, str(args.get("text") or ""), str(args.get("conv") or ""))
    if isinstance(env, dict) and env.get("success"):
        return _reply(rid, ok=True, text=str(env.get("message_id") or "") or "sent")
    err = env.get("error") if isinstance(env, dict) else env
    return _reply(rid, ok=False,
                  error={"code": CONFIRMED_FAILED_CODE, "message": str(err or "send.text 未送达")[:1024]})


async def _call_streams(ctx: Any, rid: str, args: dict[str, Any]) -> dict[str, Any]:
    platform = str(args.get("platform") or "qq")
    now = time.monotonic()
    hit = _streams_cache.get(platform)
    if hit is not None and hit[0] > now:
        streams = hit[1]
    else:
        streams = await ctx.chat.get_all_streams(platform)
        # 宿主失败不抛，回 {"success": False, "error": str}（data.py:286-293 @478f671e6）；SDK 只在
        # 有 "streams" 键时拆列表（context.py:63/320-322 @f9984673d），失败字典原样透传。
        # 不判这一层就会把宿主失败伪装成 ok:true，还把脏值缓存 300 秒。
        if isinstance(streams, dict) and streams.get("success") is False:
            return _reply(rid, ok=False, error={
                "code": CONFIRMED_FAILED_CODE,
                "message": str(streams.get("error") or "chat.get_all_streams 未送达")[:1024],
            })
        _streams_cache[platform] = (now + _STREAM_TTL_S, streams)
        while len(_streams_cache) > _STREAM_CAP:
            _streams_cache.popitem(last=False)
    return _reply(rid, ok=True, text=json.dumps(streams, ensure_ascii=False, default=str))


async def handle_call(ctx: Any, frame: dict[str, Any]) -> dict[str, Any]:
    """call 帧 → reply 帧。try/except 罩住每个 cap 调用（G-K1-C1），永不静默。

    工具名集合必须与 client._BRIDGE_TOOLS（hello.tools 申报面）逐字相等——
    未接线名不许进来（SECURITY-CBP §7 N3），本函数是它唯一的真实现。
    """
    rid = frame["rid"]
    tool = str(frame.get("tool") or "")
    args = frame.get("args") or {}
    try:
        if tool == "maibot_send":
            return await _call_send(ctx, rid, args)
        if tool == "chat.get_all_streams":
            return await _call_streams(ctx, rid, args)
        return _reply(rid, ok=False,
                      error={"code": 60002, "message": f"capability_unavailable: {tool} 不在申报面"})
    except Exception as exc:
        return _reply(rid, ok=False,
                      error={"code": CONFIRMED_FAILED_CODE, "message": f"send leg: {exc!r}"[:1024]})


def _segments(md: dict[str, Any]) -> list[dict[str, Any]] | None:
    """宿主 raw_message（段列表）→ CBP segments；$defs/seg 要求 data 值全字符串。"""
    out: list[dict[str, Any]] = []
    for seg in md.get("raw_message") or []:
        if not isinstance(seg, dict) or not isinstance(seg.get("data"), dict):
            continue
        out.append({"type": str(seg.get("type") or "text"),
                    "data": {str(k): ("" if v is None else str(v)) for k, v in seg["data"].items()}})
    if out:
        return out
    text = md.get("processed_plain_text")
    return [{"type": "text", "data": {"text": str(text)}}] if text else None


def gateway_msg_frame(md: dict[str, Any]) -> dict[str, Any] | None:
    """duplex 回包 MessageDict → CBP msg 帧；造不出（缺 conv 或空段）回 None 判 FAILED。

    sender.id 取宿主 account_id——world 侧回声判据就按这条对账
    （cortico-world-maibot/README.md:64「msg.sender.id === raw.account_id」）。
    """
    conv = str(md.get("session_id") or "")
    if not conv:
        return None
    segments = _segments(md)
    if segments is None:
        return None
    # shortcut: kernel 判 sender.id≥1，部署未回填 account_id 时以桥名占位（永不相等于账号，回声判定不误伤）；
    # 升级时机=配置面 account_id 落地后删占位。
    sender_id = str(md.get("account_id") or "") or "cortico-bridge-maibot"
    info = md.get("message_info") or {}
    kind = "group" if isinstance(info, dict) and info.get("group_info") else "direct"
    return cbp.make_frame("msg", conv=conv, sender={"id": sender_id, "name": ""},
                          kind=kind, segments=segments, raw=dict(md))

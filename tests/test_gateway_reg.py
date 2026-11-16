"""工单验收：`PY312M -I -m pytest tests/test_gateway_reg.py -q`。
断言装饰标记落本模块、create_plugin 工厂在位、route_message 走本地 RPC 桩真实可达。"""
from __future__ import annotations

import asyncio

import support
from maibot_sdk import MaiBotPlugin


def test_factory_and_hooks(pkg):
    plugin = pkg.create_plugin()
    assert isinstance(plugin, MaiBotPlugin)
    for hook in ("on_load", "on_unload", "on_config_update"):
        assert getattr(type(plugin), hook) is not getattr(MaiBotPlugin, hook), hook


def test_gateway_component_marks_land_here(pkg):
    plugin, _ = support.make_plugin_with_stub(pkg)
    comps = plugin.get_components()
    gw = [c for c in comps if c.get("type") == "MESSAGE_GATEWAY"]
    ev = [c for c in comps if c.get("type") == "EVENT_HANDLER"]
    assert len(gw) == 1 and len(ev) == 1
    g = gw[0]
    assert g["name"] == "cbp_gateway"
    meta = g.get("metadata", {})
    route = {k: v for d in (g, meta) for k, v in d.items()}
    assert route.get("route_type") == "duplex"
    assert route.get("platform") == "cortico" and route.get("protocol") == "cbp"
    # 标记必须落本模块（裸 @register_plugin 落 compat 模块的反例，r-maibot §9）
    owner = getattr(pkg.CorticoBridgePlugin.cbp_gateway, "__module__", "")
    assert owner.startswith("_maibot_plugin_")


def test_route_message_via_real_context_stub(pkg):
    plugin, stub = support.make_plugin_with_stub(pkg)
    frame = pkg.cbp.make_frame(
        "msg", id="f1", ts=1762000000.0, conv="conv-7",
        sender={"id": "u1", "name": "n"}, kind="direct",
        segments=[{"type": "text", "data": {"text": "hi"}}], raw={},
    )
    ok = asyncio.run(pkg.client.BridgeClient(plugin).route_frame(frame))
    assert ok is True
    routed = stub.by_method("host.route_message")
    assert len(routed) == 1
    _m, pid, payload = routed[0]
    assert payload["gateway_name"] == "cbp_gateway"
    assert pid == support.PLUGIN_ID
    assert payload["message"]["session_id"] == "conv-7"
    assert payload["external_message_id"] == "f1"
    assert payload["dedupe_key"] == "conv-7:f1"


def test_route_refused_returns_false(pkg):
    plugin, _ = support.make_plugin_with_stub(pkg, route_accepted=False)
    frame = pkg.cbp.make_frame("msg", id="f2", ts=1.0, conv="c", sender={"id": "u", "name": "x"},
                               kind="other", segments=[{"type": "text", "data": {"text": "t"}}], raw={})
    assert asyncio.run(pkg.client.BridgeClient(plugin).route_frame(frame)) is False

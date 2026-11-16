"""工单验收：`PY312M -I -m pytest tests/test_observer.py -q`。镜像腿一律按 dict 键读。"""
from __future__ import annotations

import asyncio


def test_dict_access_only(pkg):
    seen: list[dict] = []

    class Fake:
        _mirror_sink = staticmethod(lambda v: seen.append(v))

    host_dict = {
        "message_id": "h1", "session_id": "s1", "platform": "qq",
        "processed_plain_text": "宿主裸 dict", "raw_message": [{"type": "text", "data": {}}],
    }
    asyncio.run(pkg.observer.mirror_on_message(Fake(), host_dict))
    assert seen == [{
        "message_id": "h1", "session_id": "s1", "platform": "qq",
        "processed_plain_text": "宿主裸 dict", "raw_message": host_dict["raw_message"],
    }]


def test_non_dict_is_dropped_and_counter_used(pkg):
    class Fake:
        _mirror_sink = None

    inst = Fake()
    asyncio.run(pkg.observer.mirror_on_message(inst, {"a": 1}))
    assert inst._mirror_seen == 1
    asyncio.run(pkg.observer.mirror_on_message(inst, "not-a-dict"))
    assert inst._mirror_seen == 1  # 非 dict 直接丢，不计数也不抛


def test_attribute_access_trap_is_documented_fact(pkg):
    assert pkg.observer.demo_attribute_trap({"plain_text": "x"}) is True


def test_event_marker_on_mirror_method(pkg):
    comps = pkg.create_plugin().get_components()
    ev = [c for c in comps if c.get("type") == "EVENT_HANDLER"]
    assert len(ev) == 1
    meta = {**ev[0], **ev[0].get("metadata", {})}
    flat = str(meta)
    assert "ON_MESSAGE" in flat.upper() or "on_message" in flat

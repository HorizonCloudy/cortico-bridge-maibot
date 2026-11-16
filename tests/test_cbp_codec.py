"""工单验收：`PY312M -I -m pytest tests/test_cbp_codec.py -q`。
与 cortico-bridge-neko 同套向量对表：两份 vendored cbp.py 必须行为逐字节一致（G8 一次发明）。"""
from __future__ import annotations

import json

HELLO_TOOLS = [{"name": "t1", "risk": "read", "confirm_required": False}]
SELF = {"id": "", "name": "", "proven": False}  # hello_proven_false 逐字（conformance.json，F1/F2）
ACTOR = {"platform": "onebot", "conv": "c1", "member": {"id": "u1", "name": "n"},
         "anon": "identified"}  # call_full_actor_bound 形（F3）

GOOD_FRAMES = [
    {"v": 1, "t": "hello", "id": "h1", "ts": 1762000000.0,
     "agent": {"name": "cortico-bridge-maibot", "version": "0.1.0", "sha": "unpinned"},
     "v_support": [1], "caps": ["inbound_msg"], "tools": HELLO_TOOLS, "self": dict(SELF)},
    {"v": 1, "t": "ready", "id": "r1", "ts": 1.0, "caps": ["inbound_msg"], "tools": [],
     "self": dict(SELF)},
    {"v": 1, "t": "msg", "id": "m1", "ts": 2.0, "conv": "c1",
     "sender": {"id": "u1", "name": "n"}, "kind": "mention",
     "segments": [{"type": "text", "data": {"text": "hi"}}], "raw": {"x": 1}},
    {"v": 1, "t": "notice", "id": "n1", "ts": 3.0, "kind": "recall", "raw": {}},
    {"v": 1, "t": "notice", "id": "n2", "ts": 3.0, "conv": "c1", "kind": "k", "raw": {}},
    {"v": 1, "t": "ack", "id": "a1", "ts": 4.0, "rid": "m1"},
    {"v": 1, "t": "call", "id": "cl1", "ts": 5.0, "rid": "q1", "tool": "maibot_send", "args": {},
     "turn": "m1", "actor": dict(ACTOR)},
    {"v": 1, "t": "reply", "id": "rp1", "ts": 6.0, "rid": "q1", "ok": True, "text": "done"},
    {"v": 1, "t": "reply", "id": "rp2", "ts": 6.0, "rid": "q1", "ok": False,
     "error": {"code": 60005, "message": "door_closed"}},
    {"v": 1, "t": "event", "id": "e1", "ts": 7.0, "name": "degraded", "data": {"why": "pdf"}},
    {"v": 1, "t": "tick", "id": "tk1", "ts": 8.0},
    {"v": 1, "t": "catalog", "id": "cat1", "ts": 9.0, "tools": HELLO_TOOLS},
]

BAD_INPUTS = [
    "null", "[1,2]", '"str"', "12", "1.5", "true",
    json.dumps({"v": 2, "t": "tick", "id": "x", "ts": 1.0}),
    json.dumps({"v": 1, "t": "nope", "id": "x", "ts": 1.0}),
    json.dumps({"v": 1, "t": "msg", "id": "x", "ts": 1.0}),
    json.dumps({"v": 1, "t": "tick", "id": "", "ts": 1.0}),
    json.dumps({"v": 1, "t": "tick", "id": "z" * 65, "ts": 1.0}),
    json.dumps({"v": 1, "t": "tick", "id": "x"}),
    json.dumps({"v": 1, "t": "tick", "id": "x", "ts": True}),
    "{not json",
]


def test_good_vectors_roundtrip(pkg):
    for frame in GOOD_FRAMES:
        wire = pkg.cbp.encode(frame)
        assert pkg.cbp.decode(wire) == frame, frame["t"]
        assert pkg.cbp.decode(wire.encode("utf-8")) == frame


def test_bad_vectors_are_dropped(pkg):
    for raw in BAD_INPUTS:
        assert pkg.cbp.decode(raw) is None, raw


def test_encode_refuses_invalid_and_make_frame_fills_header(pkg):
    import pytest

    with pytest.raises(ValueError):
        pkg.cbp.encode({"v": 1, "t": "bogus"})
    f = pkg.cbp.make_frame("tick")
    assert f["v"] == 1 and f["t"] == "tick" and 1 <= len(f["id"]) <= 64 and f["ts"] > 0
    with pytest.raises(ValueError):
        pkg.cbp.make_frame("nope")


def test_frame_type_table_is_ten(pkg):
    assert len(pkg.cbp._REQUIRED) == 10
    assert pkg.cbp.TOOL_RISKS == ("read", "write", "speak", "act", "flow", "snapshot")


def test_hello_shape(pkg):
    h = pkg.client.BridgeClient(plugin=None).hello()
    assert h["t"] == "hello" and h["v_support"] == [1]
    assert all(t["risk"] in pkg.cbp.TOOL_RISKS for t in h["tools"])

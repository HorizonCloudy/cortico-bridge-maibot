"""工单验收：`PY312M -I -m pytest tests/test_mdict.py -q`。17 键快照 + 只增不改 + 键访问铁律。"""
from __future__ import annotations

from datetime import datetime


def _frame(cbp, kind="direct", segs=None, conv="s1", mid="f9"):
    return cbp.make_frame("msg", id=mid, ts=1762000000.25, conv=conv,
                          sender={"id": "u1", "name": "阿神"}, kind=kind,
                          segments=segs if segs is not None else
                          [{"type": "text", "data": {"text": "你好"}}],
                          raw={"origin": "x"})


def test_seventeen_keys_exact(pkg):
    md = pkg.mdict.frame_to_message_dict(_frame(pkg.cbp))
    assert isinstance(md, dict)
    assert set(md) == set(pkg.mdict.MESSAGE_DICT_KEYS) == {
        "message_id", "timestamp", "received_at", "platform", "account_id", "scope",
        "message_info", "raw_message", "is_mentioned", "is_at", "is_emoji", "is_picture",
        "is_command", "is_notify", "session_id", "reply_to", "processed_plain_text",
    }


def test_host_shapes(pkg):
    md = pkg.mdict.frame_to_message_dict(_frame(pkg.cbp))
    assert md["timestamp"] == "1762000000.25"  # str(float 秒)（message_utils.py:431）
    assert md["received_at"] == datetime.fromtimestamp(1762000000.25).isoformat(
        timespec="microseconds")
    assert md["raw_message"] == [{"type": "text", "data": {"text": "你好"}}]  # 段列表原样
    assert md["message_info"]["user_info"] == {"user_id": "u1", "user_nickname": "阿神"}
    assert md["message_info"]["group_info"] is None
    assert md["processed_plain_text"] == "你好"
    assert md["platform"] == "cortico" and md["is_notify"] is False


def test_flag_matrix(pkg):
    m, cbp = pkg.mdict.frame_to_message_dict, pkg.cbp
    assert m(_frame(cbp, kind="mention"))["is_mentioned"] is True
    md = m(_frame(cbp, kind="group", conv="g1"))
    assert md["message_info"]["group_info"] == {"group_id": "g1", "group_name": ""}
    md = m(_frame(cbp, segs=[
        {"type": "at", "data": {"qq": "all"}},
        {"type": "face", "data": {"id": "1"}},
        {"type": "image", "data": {"url": "u"}},
        {"type": "text", "data": {"text": "/go"}},
    ]))
    assert (md["is_at"], md["is_emoji"], md["is_picture"], md["is_command"]) == (True,) * 4


def test_route_kwargs_form(pkg):
    kw = pkg.mdict.route_kwargs(_frame(pkg.cbp, conv="c3", mid="m3"))
    assert kw == {"route_metadata": None, "external_message_id": "m3", "dedupe_key": "c3:m3"}


def test_no_maimessages_and_no_compat(pkg):
    import inspect
    from pathlib import Path

    src = inspect.getsource(pkg.mdict)
    assert "import MaiMessages" not in src and "MaiMessages(" not in src  # 只交裸 dict
    root = Path(support_repo_root())
    for name in ("mdict.py", "observer.py", "client.py", "plugin.py"):
        source = (root / name).read_text(encoding="utf-8")
        assert "maibot_sdk.compat" not in source and "src.plugin_system" not in source, name


def support_repo_root() -> str:
    import support

    return str(support.REPO_ROOT)

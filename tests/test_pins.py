"""端口从 pins.json 取数的验收（maibot 侧）：未指向即报错、缺键即报错、URI 只从文件来。
另扫全仓：代码零端口字面量（AST 常量级）。"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
import support

KNOWN_PORTS = {
    39701, 39702, 48911, 48912, 48913, 48914, 48915, 48916,
    38865, 38866, 38867, 48961, 48962, 48963, 39539,
    8001, 6185, 6199, 5140, 8080, 5700, 6700, 48965,
}


def test_missing_env_refuses_hard(pkg, monkeypatch):
    monkeypatch.delenv("CORTICO_PINS_JSON", raising=False)
    with pytest.raises(RuntimeError) as ei:
        pkg.pins.load_pins()
    assert "CORTICO_PINS_JSON" in str(ei.value)


def test_uri_from_fixture_file(pkg, pins_file):
    pins = pkg.pins.load_pins()
    assert pkg.pins.bridge_ws_uri(pins) == "ws://127.0.0.1:39702"  # 缺省即 maibot 键
    assert pkg.pins.bridge_ws_uri(pins, "cortico_world_neko_ws") == "ws://127.0.0.1:39701"


def test_client_uri_follows_pins(pkg, pins_file):
    import asyncio

    client = pkg.client.BridgeClient(plugin=None)
    assert client.uri() == "ws://127.0.0.1:39702"
    # enabled=False：run() 直接返回，不触网、不拨号（骨架边界）
    asyncio.run(client.run())
    assert client.connected is False


def test_bad_ports_rejected(pkg, tmp_path):
    p = tmp_path / "p.json"
    p.write_text('{"ports": {}}', encoding="utf-8")
    with pytest.raises(RuntimeError):
        pkg.pins.port_of(pkg.pins.load_pins(str(p)), "cortico_world_maibot_ws")


def test_no_port_literals_in_shipped_code():
    for py in sorted(Path(support.REPO_ROOT).glob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, int):
                assert node.value not in KNOWN_PORTS, f"{py.name}:{node.lineno}"

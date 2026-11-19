"""SECURITY-CBP §3 凭据流向（maibot 腿）：共享密钥只走 HTTP Upgrade 头，禁过 URL。

2026-11-19（10-22 / 11-13 索引仓判例）新增 fail-shut 语义：
- 缺 `CORTICO_BRIDGE_TOKEN` 时 `auth_headers()` 抛错、`BridgeClient.run()` 直接返回；
- 空 token 不再是「环回免鉴权」——浏览器 WebSocket 没有 CORS 预检；
- 帧体与 URI 都不留凭据位，日志不回显密钥值。
全程禁网：websockets 用替身。
"""
from __future__ import annotations

import asyncio
import sys

import pytest
import support

TOKEN = "s3cr3t-do-not-leak"


class _FakeWs:
    def __init__(self, sink):
        self._sink = sink

    async def send(self, raw):
        self._sink.setdefault("sent", []).append(raw)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


def _install_fake_websockets(monkeypatch, captured):
    class _Mod:
        @staticmethod
        def connect(uri, **kwargs):
            captured["uri"] = uri
            captured["kwargs"] = kwargs
            return _FakeWs(captured)

    monkeypatch.setitem(sys.modules, "websockets", _Mod)


# ---------- 取数口：只认环境变量，缺密钥 fail-shut ----------

def test_token_env_var_name_is_pinned(pkg):
    assert pkg.pins.TOKEN_ENV == "CORTICO_BRIDGE_TOKEN"  # SECURITY-CBP.md:121 逐字


def test_auth_header_is_bearer_form(pkg, monkeypatch):
    monkeypatch.setenv(pkg.pins.TOKEN_ENV, TOKEN)
    assert pkg.pins.auth_headers() == {"Authorization": f"Bearer {TOKEN}"}


def test_missing_shared_secret_refuses_dial(pkg, monkeypatch):
    monkeypatch.delenv(pkg.pins.TOKEN_ENV, raising=False)
    with pytest.raises(RuntimeError) as ei:
        pkg.pins.auth_headers()
    assert pkg.pins.TOKEN_ENV in str(ei.value)
    assert "无密钥一律不建链" in str(ei.value)


def test_config_token_is_ignored(pkg, monkeypatch):
    monkeypatch.delenv(pkg.pins.TOKEN_ENV, raising=False)
    with pytest.raises(RuntimeError):
        pkg.pins.auth_headers({"token": TOKEN})
    monkeypatch.setenv(pkg.pins.TOKEN_ENV, "from-env")
    assert pkg.pins.auth_headers({"token": TOKEN})["Authorization"] == "Bearer from-env"


# ---------- URL 面：不得带凭据 ----------

def test_uri_never_carries_the_token(pkg, pins_file, monkeypatch):
    monkeypatch.setenv(pkg.pins.TOKEN_ENV, TOKEN)
    uri = pkg.pins.bridge_ws_uri(pkg.pins.load_pins())
    assert uri == f"ws://127.0.0.1:{support.PINS_SAMPLE['ports']['cortico_world_maibot_ws']}"
    assert "token" not in uri.lower() and TOKEN not in uri and "?" not in uri


@pytest.mark.parametrize("dirty", ["ws://127.0.0.1:1?token=x", "ws://127.0.0.1:1/a?access_token=y"])
def test_clean_uri_guard_rejects_query(pkg, dirty):
    with pytest.raises(ValueError):
        pkg.pins._assert_clean_uri(dirty)


# ---------- 拨号面：密钥进 headers，不进 URL ----------

def test_run_refuses_without_shared_secret(pkg, pins_file, monkeypatch):
    """缺密钥时连 websockets.connect 都不许调用，且不进重连循环。"""
    captured: dict = {}
    _install_fake_websockets(monkeypatch, captured)
    monkeypatch.delenv(pkg.pins.TOKEN_ENV, raising=False)

    client = pkg.client.BridgeClient(plugin=None, enabled=True)
    asyncio.run(client.run())

    assert captured == {}, "空 token 不再等于免鉴权"
    assert client.connected is False


def test_run_passes_bearer_header_not_url(pkg, pins_file, monkeypatch):
    captured: dict = {}
    _install_fake_websockets(monkeypatch, captured)
    monkeypatch.setenv(pkg.pins.TOKEN_ENV, TOKEN)

    async def _stop_soon(_delay):  # 只跑一轮，不真等退避
        raise asyncio.CancelledError

    monkeypatch.setattr(pkg.client.asyncio, "sleep", _stop_soon)
    client = pkg.client.BridgeClient(plugin=None, enabled=True)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(client.run())

    assert "?" not in captured["uri"] and "token" not in captured["uri"].lower()
    assert captured["kwargs"]["additional_headers"] == {"Authorization": f"Bearer {TOKEN}"}
    hello = pkg.client.cbp.decode(captured["sent"][0])
    assert hello["t"] == "hello"
    assert "token" not in hello and "auth" not in {k.lower() for k in hello}


# ---------- 静态闸：全仓不拼 query 凭据 ----------

def test_no_query_token_concatenation_in_source(pkg):
    for name in ("pins.py", "client.py", "plugin.py", "cbp.py"):
        src = (support.REPO_ROOT / name).read_text(encoding="utf-8")
        for bad in ("?token=", "&token=", "?access_token=", "&access_token="):
            assert bad not in src, f"{name} 出现 {bad}"

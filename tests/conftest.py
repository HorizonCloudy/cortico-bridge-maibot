"""pytest 装配：tests/ 进 sys.path；暴露 pkg/plugin 夹具与凭据围栏。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR))

import support  # noqa: E402


@pytest.fixture(scope="session")
def pkg():
    return support.load_plugin_module()


@pytest.fixture()
def pins_file(tmp_path, monkeypatch):
    path = support.write_pins(tmp_path)
    monkeypatch.setenv("CORTICO_PINS_JSON", path)
    monkeypatch.delenv("MAIBOT_INSTANCE_DIR", raising=False)
    return path


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch):
    for name in ("MAIBOT_TOKEN", "BOT_TOKEN", "NEKO_TOKEN", "API_KEY", "CORTICO_BRIDGE_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    yield

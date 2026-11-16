"""测试支撑件：宿主同款动态导入配方 + 本地记录型 RPC 桩。全程不触网、不起宿主。

配方逐字对齐 plugin_loader.py:594-613 @478f671e6：
spec_from_file_location(<合成包名>, plugin.py, submodule_search_locations=[插件目录])，
合成名 = `_maibot_plugin_<id 净化>`（:407-420），先挂进 sys.modules 再 exec。
RPC 桩法 = r-maibot §3/§6：本地记录 `cap.call/host.route_message/...`，零网络出口。
"""
from __future__ import annotations

import importlib
import importlib.util
import re
import sys
import types
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ID = "io.cortico.bridge-maibot"


def load_cbp_standalone(repo_root: Path, pkg_name: str):
    """合成包命名空间下加载 cbp.py（存在时连 cbp_table.py），不碰宿主依赖。

    跨仓 parity 闸用：任何 venv 都能加载两仓的纯 stdlib 编解码层。
    """
    full = f"{pkg_name}.cbp"
    if full in sys.modules:
        return sys.modules[full]
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [str(repo_root)]
    sys.modules[pkg_name] = pkg
    if (repo_root / "cbp_table.py").exists():
        importlib.import_module(f"{pkg_name}.cbp_table")
    return importlib.import_module(f"{pkg_name}.cbp")

PINS_SAMPLE: dict[str, Any] = {
    "ports": {"cortico_world_neko_ws": 39701, "cortico_world_maibot_ws": 39702},
    "maibot": {"host": "1.4.5", "sdk": "2.23.0"},
}


def write_pins(tmp_path: Path) -> str:
    import json

    p = tmp_path / "pins.json"
    p.write_text(json.dumps(PINS_SAMPLE), encoding="utf-8")
    return str(p)


def safe_module_name(plugin_id: str) -> str:
    """复刻 _build_safe_module_name（宿主 loader :407）。"""
    norm = re.sub(r"[^0-9A-Za-z_]", "_", str(plugin_id or "").strip())
    if norm and norm[0].isdigit():
        norm = f"_{norm}"
    return f"_maibot_plugin_{norm or 'plugin'}"


def load_plugin_module():
    """宿主配方动态导入本仓 plugin.py（同目录件因此走相对导入）。"""
    name = safe_module_name(PLUGIN_ID)
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, str(REPO_ROOT / "plugin.py"), submodule_search_locations=[str(REPO_ROOT)]
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class RecordingRpc:
    """本地 RPC 桩：记录 (method, plugin_id, payload) 并按 method 返回剧本值。"""

    def __init__(self, *, route_accepted: bool = True) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.route_accepted = route_accepted

    async def __call__(self, method: str, plugin_id: str, payload: dict, **_: Any) -> Any:
        self.calls.append((method, plugin_id, payload))
        if method == "host.route_message":
            return {"accepted": self.route_accepted}
        return {"success": True, "result": None}

    def by_method(self, method: str) -> list[tuple[str, str, dict]]:
        return [c for c in self.calls if c[0] == method]


def make_plugin_with_stub(module, *, route_accepted: bool = True):
    """create_plugin() → 注入真实 PluginContext（rpc 换本地桩）→ (plugin, stub)。"""
    from maibot_sdk.context import PluginContext

    plugin = module.create_plugin()
    stub = RecordingRpc(route_accepted=route_accepted)
    plugin._set_context(PluginContext(PLUGIN_ID, rpc_call=stub))
    return plugin, stub

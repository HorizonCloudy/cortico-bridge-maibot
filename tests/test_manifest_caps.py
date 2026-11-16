"""工单验收：`PY312M -I -m pytest tests/test_manifest_caps.py -q`。

manifest_scan 双向集合相等闸（G2/R5；台账红点见 reports/_GATE-RUN-3.md:64，
`--check FAIL: 名单漂移 多报 ['gateway.route_message','gateway.update_state']`）。
两边各读各的真值，互不引用，谁漂谁红：
  申报侧 = 本仓 `_manifest.json` 的 `capabilities` 数组——宿主加载期硬执法面
           （authorization.py:58 @478f671e6：多报=超发许可，漏报=硬拒「未获授权能力」）。
  实扫侧 = fleet `tools/manifest_scan.py` 对本仓非测试源码的 AST 全集
           （universe = pins.json `vocab.maibot.capabilities` ∪ `gateway_extra_caps`）。
  第三条把申报侧钉在 universe 内（manifest_scan.py:6 的「名单⊆universe」在仓内复刻）。

shortcut: 实扫侧真值跟随 manifest_scan 的链根判定（现只认 `ctx` / `self.ctx` /
`plugin.ctx` 三根，manifest_scan.py:56-66），`client.py:54` 的 `self.plugin.ctx.…`
形态扫不到；升级时机 = fleet 补链根或调用点改写后，本闸无需改动自动收紧。
fleet 根 = 兄弟目录 ../../cortico-bridge-fleet；可用 CORTICO_FLEET_ROOT 覆盖（negctl 用）。
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FLEET_ROOT = Path(os.environ.get("CORTICO_FLEET_ROOT") or (REPO_ROOT.parent / "cortico-bridge-fleet"))
PINS_JSON = FLEET_ROOT / "spec" / "pins.json"
TOOL_PY = FLEET_ROOT / "tools" / "manifest_scan.py"


def _tool():
    spec = importlib.util.spec_from_file_location("_fleet_manifest_scan", TOOL_PY)
    assert spec is not None and spec.loader is not None, f"fleet 闸件缺失：{TOOL_PY}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def declared_caps() -> set[str]:
    """申报侧真值：_manifest.json 上交给宿主的 capabilities。"""
    text = (REPO_ROOT / "_manifest.json").read_text(encoding="utf-8")
    return set(json.loads(text)["capabilities"])


def scanned_caps() -> set[str]:
    """实扫侧真值：AST 扫出的 ctx.* 全集（口径与 manifest_scan --check 同源）。"""
    t = _tool()
    caps, extras = t.universe(PINS_JSON)
    return set(t.scan_dir(REPO_ROOT, caps, extras, set()).found)


def test_manifest_caps_equals_ast_scan_bidirectionally():
    declared, scanned = declared_caps(), scanned_caps()
    assert declared == scanned, (
        f"_manifest.json 与 AST 实扫漂移：多报={sorted(declared - scanned)} "
        f"漏报={sorted(scanned - declared)}（修复口径：名单由 manifest_scan 生成写回，manifest_scan.py:156）"
    )


def test_declared_caps_within_universe():
    caps, extras = _tool().universe(PINS_JSON)
    declared = declared_caps()
    outside = sorted(declared - (caps | extras))
    assert not outside, f"申报含 universe 外名字：{outside}"

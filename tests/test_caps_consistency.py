"""工单验收：`PY312M -I -m pytest tests/test_caps_consistency.py -q`。

双向一致性闸（台账 item 30 / SECURITY-CBP §60「副本对表、漂移即红」的落点）。
两边各读各的真值，互不引用，谁漂谁红：
  桥侧   = client.hello() 上 wire 的 caps（其唯一来源应为 caps.BRIDGE_CAPS）
  Cortico 侧 = 直接读 fleet cortico-world-maibot/src/world.ts 的 WORLD_CAPS
再核：两侧都必须在内核词表内（防两侧同步漂成假名字）。词表唯一来源 = fleet
`spec/pins.json` `vocab.cbp.caps`——内核运行时也从这一件取（pins.ts capsVocabOf），
本测试不再手抄 pins.ts 的字面数组（单源化改造后那份手抄已不存在，读它必假红）。
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FLEET_ROOT = Path(os.environ.get("CORTICO_FLEET_ROOT") or (REPO_ROOT.parent / "cortico-bridge-fleet"))
WORLD_TS = FLEET_ROOT / "packages" / "cortico-world-maibot" / "src" / "world.ts"
PINS_JSON = FLEET_ROOT / "spec" / "pins.json"

_ARR = r"\b{0}\b\s*(?::[^=]*)?=\s*\[(.*?)\]"
_PROP = r"\b{0}\b\s*:\s*\[(.*?)\]"
_ITEM = re.compile(r"['\"]([^'\"]+)['\"]")


def _ts_array(text: str, name: str) -> list[str]:
    m = re.search(_ARR.format(name), text, re.DOTALL) or re.search(_PROP.format(name), text, re.DOTALL)
    assert m, f"{name} 未在源文件里找到，读取方需同步 {name} 的形状"
    return _ITEM.findall(m.group(1))


def cortico_world_caps() -> set[str]:
    """Cortico 侧 manifest 声明的能力名单（FACT-1）。"""
    return set(_ts_array(WORLD_TS.read_text(encoding="utf-8"), "WORLD_CAPS"))


def core_vocab() -> set[str]:
    """内核能力词表（FACT-3）：只有词表内的名字能被协商接受。单源 = fleet spec/pins.json。"""
    return set(json.loads(PINS_JSON.read_text(encoding="utf-8"))["vocab"]["cbp"]["caps"])


def bridge_hello_caps(pkg) -> set[str]:
    """桥侧真正发到 wire 的 hello.caps（FACT-2 的当前落点）。"""
    return set(pkg.client.BridgeClient(plugin=None).hello()["caps"])


def test_bridge_caps_match_cortico_manifest_bidirectionally(pkg):
    """双向：桥侧集合 == Cortico 集合。任一侧多报或少报都红。"""
    bridge = bridge_hello_caps(pkg)
    cortico = cortico_world_caps()
    assert bridge == cortico, (
        f"caps 漂移：桥独有={sorted(bridge - cortico)} "
        f"Cortico 独有={sorted(cortico - bridge)}"
    )


def test_declared_caps_are_real_vocab(pkg):
    """两侧申报的能力都必须在内核词表内，否则协商会静默丢弃，'同源'就是假的。"""
    vocab = core_vocab()
    assert bridge_hello_caps(pkg) <= vocab, f"桥侧含词表外名字：{sorted(bridge_hello_caps(pkg) - vocab)}"
    assert cortico_world_caps() <= vocab, f"Cortico 侧含词表外名字：{sorted(cortico_world_caps() - vocab)}"


def test_caps_single_source_wired_to_hello(pkg):
    """单源锁：caps.py 的 BRIDGE_CAPS 是唯一来源，hello 帧 caps 必须逐字来自它。"""
    single = set(pkg.caps.BRIDGE_CAPS)
    assert single == bridge_hello_caps(pkg), (
        f"hello 帧 caps 偏离 caps.BRIDGE_CAPS：{sorted(bridge_hello_caps(pkg) ^ single)}"
    )
    assert single == cortico_world_caps()

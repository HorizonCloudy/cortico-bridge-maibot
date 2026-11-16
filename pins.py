"""pins.json 读取件。端口一律从 pins.json 取，本文件与全仓代码零端口字面量。

单一来源 = fleet 仓 `spec/pins.json`（_BUILD-PLAN §2.1、§4.4）。本仓通过环境变量
`CORTICO_PINS_JSON` 指向该文件；未指向就报错，绝不回退到内置缺省值——回退等于把
端口写死。键名约定（端口数值只存在于 pins.json，本文件与全仓代码零端口字面量）：
  ports.cortico_world_maibot_ws  Cortico 侧 maibot world 监听口（蓝图 §4.4 表钉值，本处不复述数字）
宿主侧端口不进本桥代码：MaiBot Runner 子进程只有三个原始 RPC
（cap.call / host.route_message / host.update_message_gateway_state，r-maibot §11-4），
从模型上就没打算让插件开服务或连端口；桥只外拨 Cortico 侧监听口。
"""
from __future__ import annotations

import json
import os
from typing import Any

ENV_VAR = "CORTICO_PINS_JSON"
HOST = "127.0.0.1"  # loopback：Cortico 侧监听缺省绑环回（§4.4 绑定面列）


def load_pins(path: str | None = None) -> dict[str, Any]:
    """读取 pins.json。path 缺省时取环境变量 CORTICO_PINS_JSON；两处皆空即报错。"""
    resolved = path or os.environ.get(ENV_VAR, "").strip()
    if not resolved:
        raise RuntimeError(
            f"pins.json 未指定：设 {ENV_VAR} 指向 fleet spec/pins.json（禁内置端口缺省）"
        )
    with open(resolved, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise RuntimeError(f"{resolved} 顶层不是 JSON 对象")
    return data


def port_of(pins: dict[str, Any], key: str) -> int:
    """从 pins['ports'] 取整数端口；缺键即报错，不做默认值。"""
    ports = pins.get("ports")
    if not isinstance(ports, dict) or key not in ports:
        raise RuntimeError(f"pins.json 缺 ports.{key}")
    value = ports[key]
    if isinstance(value, bool) or not isinstance(value, int) or not (1 <= value <= 65535):
        raise RuntimeError(f"pins.json ports.{key} 非有效端口: {value!r}")
    return int(value)


def bridge_ws_uri(pins: dict[str, Any], key: str = "cortico_world_maibot_ws") -> str:
    """拼 Cortico 侧 world 的 ws:// URI。"""
    return f"ws://{HOST}:{port_of(pins, key)}"

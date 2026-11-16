"""cortico-bridge-maibot 入口。MaiBot==1.4.5 + maibot-plugin-sdk==2.23.0，Python 3.12 桶。

装载配方（宿主 plugin_loader.py:594-613 @478f671e6）：宿主用 spec_from_file_location 把
本文件当「带 submodule_search_locations 的合成包」执行，模块名 =
`_maibot_plugin_<sanitized_id>`（:407-420），所以同目录件一律 `from .x import` 绝对安全，
不需要也不得依赖 sys.path 注入。

三钩子强制：on_load/on_unload/on_config_update 基类未覆写即 NotImplementedError
（r-maibot §9 冒烟实测），本文件覆写之；签名以 SDK 为准
（on_config_update(self, scope, config_data, version)，plugin.py:513 @f9984673d——
_BUILD-PLAN §3.4-2 草案写的 (new, old) 与真面不符，以 SDK 为证据源）。
注册一律带参形态：`create_plugin()` 工厂（loader :613 优先路径）。裸 @register_plugin
会把标记落到 compat 模块自身（r-maibot §9），且本桥根本不进 compat——见 README。
"""
from __future__ import annotations

from typing import Any

from maibot_sdk import MaiBotPlugin, MessageGateway
from maibot_sdk.components import collect_components

from .client import BridgeClient
from .observer import mirror_on_message


class CorticoBridgePlugin(MaiBotPlugin):
    """CBP 桥插件。骨架只做：声明 duplex 网关、挂 ON_MESSAGE 镜像、带一个外拨客户端对象。

    默认 enabled=False：不联网、不起宿主、不拨号；部署时经宿主配置显式打开。
    入站唯一口 = ctx.gateway.route_message（kwargs 形，见 mdict.route_kwargs）。
    """

    def __init__(self) -> None:
        super().__init__()
        self._bridge_enabled = False
        self._client: BridgeClient | None = None

    # ---------- 生命周期三钩子（强制覆写） ----------
    async def on_load(self) -> None:
        cfg = getattr(self, "config", None)
        if isinstance(cfg, dict):
            self._bridge_enabled = bool(cfg.get("enabled", False))
        if self._bridge_enabled:
            self._client = BridgeClient(self, enabled=True)
            self._client.start()
            self._get_logger().info("cortico-bridge-maibot: link task started")
        else:
            self._get_logger().info("cortico-bridge-maibot: loaded, link disabled (enabled=false)")

    async def on_unload(self) -> None:
        if self._client is not None:
            self._client.stop()
            self._client = None

    async def on_config_update(self, scope: str, config_data: dict[str, Any], version: str) -> None:
        if not isinstance(config_data, dict):
            return
        want = bool(config_data.get("enabled", self._bridge_enabled))
        if want == self._bridge_enabled:
            return
        self._bridge_enabled = want
        if want:
            self._client = BridgeClient(self, enabled=True)
            self._client.start()
        elif self._client is not None:
            self._client.stop()
            self._client = None

    # ---------- 组件面 ----------
    def get_components(self) -> list[dict[str, Any]]:
        return collect_components(self)

    # 镜像腿：装饰件定义在 observer.py，宿主送裸 dict，一律键访问。
    on_mirror_message = mirror_on_message

    @MessageGateway(
        route_type="duplex",
        platform="cortico",
        protocol="cbp",
        account_id="",  # 部署配置回填 self_id；代码不写死账号
        scope="",
    )
    async def cbp_gateway(self, message: Any, **_: Any) -> None:
        """duplex 网关的 send 方向腿占位（阶段二 sender.py 工单）。骨架期不发消息。

        route_type=duplex 是蓝图 §2.2 钉的唯一入站协议口形状；本方法被宿主派发时
        message 同样是 dict（r-maibot §9），不做属性访问、不碰 compat。
        """
        return None


def create_plugin() -> CorticoBridgePlugin:
    """宿主 loader 优先工厂（plugin_loader.py:613 实测路径）。"""
    return CorticoBridgePlugin()

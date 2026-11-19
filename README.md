# cortico-bridge-maibot

Cortico 与 MaiBot 之间的 CBP 帧桥（MaiBot 插件，Python 3.12 桶）。件：manifest v2、
create_plugin 工厂、duplex 网关声明（含 send 方向腿）、ON_MESSAGE 镜像、MessageDict
造形、CBP 外拨客户端、发信腿 `sender.py`。
本仓不启动宿主、不连 IM；客户端 `enabled` 缺省 False，不拨号。

## 布局

| 件 | 职责 | 证据钉 |
|---|---|---|
| `_manifest.json` | manifest_version 2、17 字段全表、capabilities 白名单 | r-maibot §7（`ManifestValidator.SUPPORTED_MANIFEST_VERSIONS=[2]`；缺字段报 11 项实测） |
| `plugin.py` | `create_plugin()` 工厂 + 三钩子覆写 + `@MessageGateway(route_type="duplex", platform="cortico", protocol="cbp", ...)` | loader :594-613 / :613 工厂优先路径 @478f671e6；§9 三钩子强制 |
| `observer.py` | `@EventHandler(event_type=EventType.ON_MESSAGE, intercept_message=False)` 镜像；消息一律按 dict 键读 | §9/§10：legacy 链路实测裸 dict；`message.plain_text` 必 AttributeError |
| `mdict.py` | CBP msg → MessageDict 十七键逐字（只增不改）；`route_message` kwargs 形入参表 | message_utils.py:45-62 @478f671e6；§3 别名签名 |
| `client.py` | WS 外拨（端口从 pins.json）+ 帧泵 + route_message 注入；永不抛 | 蓝图 L84；R7 三原始 RPC |
| `sender.py` | call → capabilities 真调（`send.text` / `chat.get_all_streams`）+ stream 缓存表 + duplex 回包造帧 | `send.py:27`、`chat.py:57-59` @f9984673d；`data.py:286-293`、`message_utils.py:564/446` @478f671e6 |
| `cbp.py` `pins.py` | 帧编解码 vendored 副本（与 neko 侧同一向量表对表）；端口取数件 | G8 |

## 为什么走 capabilities 新面，不走 compat 门面

这是工单点名要求写进 README 的决策，四条全部是运行产物级证据（r-maibot §5/§6/§9/§11）：

1. **compat 是死桩集中营。** 公开 87 个函数里 direct_forward 只有 30 个（约 34%），
   silent 48 个——`get_all_streams→[]`、`count_new_messages→0` 这类不发任何 RPC 的
   恒定假值。桥一旦依赖，症状是「静默成功、空结果」，比崩溃难查一个量级。
2. **裸 `@register_plugin` 有实测错面。** 无参装饰把 `_legacy_plugin_class` 标记落到
   `compat.apis.plugin_register_api` 模块自身（`inspect.stack()` 反例，§9），宿主
   loader 找不到标记。新面的 `create_plugin()` 是 loader 第一优先路径（:613 实测），
   没有这类坑。
3. **compat 路径常量在安装态指向错误位置。** `PROJECT_ROOT=<venv>/Lib`、
   `PLUGINS_DIR` 不存在（§9）。旧面的文件类能力在这台机器的安装形态下必错。
4. **执法点在宿主侧。** `_manifest.json` capabilities 白名单 + `authorization.py:58`
   硬拒未授权能力（拒语逐字「插件 {id} 未获授权能力: {capability}」）。声明式授权只
   在新面成立；compat 调用绕过这份账。

因此：本桥只 import 公开 SDK（`maibot_sdk` 顶层 29 名 + 子模块），入站固定用
`ctx.gateway.route_message`（旧名别名 `receive_external_message` 不进桥词表，C1-18）。
48 个 compat silent 桩一律不得依赖（§11-7 原话口径）。

## self 申报与 call 处理（SECURITY-CBP §2）

**self：显式协议降级，不是未接线。** F1 规定桥拨出侧握手首帧必带 self
（SECURITY-CBP.md:74），MaiBot 线实证口 = `internal_chat.identity`
（SECURITY-CBP.md:91）。读宿主 1.4.5 安装源实证：该能力返回常量聊天室坐标
`{platform:"internal", user_id:"owner"}`
（`src/plugin_runtime/capabilities/internal_chat.py:16-19` ←
`src/core/internal_chat.py:3-6`）——那是主人的坐标，bot 自己的键 `"self"` 根本不在
返回值里。MaiBot 拿不到自身机器人账号主键，所以 `client.hello()` 显式传
`make_self_decl()` 的诚实空声明 `{id:"", name:"", proven:false}`（SECURITY-CBP §2
规则 1 允许的合法申报）。后果：本腿自回声抑制不可用，Cortico 侧对这条腿走
`self-unknown` 降级、status 常驻 `self-echo:off`（§2 规则 4）；`self_echo` cap 因此
不宣（§2 规则 3「self_echo 只能与 proven:true 同现」，caps.py:10-12、
tests/test_hello_self_call.py 双向钉死）。升级时机：宿主实证口给出 bot 自身账号主键
后，填 id/name、改 proven:true，且 self_echo cap 须与 Cortico 侧同批再宣。

**call：处理腿已接线（工单 K1），申报面=真可达面。** `sender.py` 实现两支：
`maibot_send`（转 `send.text`，conv 直通 stream_id）与 `chat.get_all_streams`
（读腿带 TTL 缓存表）。`hello.tools` 就申报这两支——只报可达的名（SECURITY-CBP §7
N3），fleet 侧镜像在 `cortico-world-maibot/src/world.ts` 的 `PEER_CAPABILITIES`，
跨仓闸 = `tests/hello-authority.test.ts`。名字不在申报面、或本轮 turn 查无入站记录
的 `call` 帧不静默：分别回 `reply{ok:false, error:{code:60002 capability_unavailable}}`
与 `60004 unknown_session`（与 neko 桥同码，`cortico-bridge-neko/__init__.py:173`）；
静默会拖到内核 30s 相关超时译成 60007（CBP-v1.json:545）。宿主业务失败（`send.text`
回 `success:false`、`get_all_streams` 回失败字典）统一回
`sender.CONFIRMED_FAILED_CODE`——U1 归属未裁，起点 60008，单点收敛。

## 安装形态硬条件

- wheel 安装态的 MaiBot 必须带 `MAIBOT_INSTANCE_DIR` 起：`third_party_plugin_root()`
  无该 env 直接 RuntimeError（paths.py:20-21 @478f671e6，§7 实测）。桥落点 =
  `<instance>/plugins/cortico-bridge-maibot/`。
- 端口不写死：Cortico 侧 maibot world 监听口从 fleet `spec/pins.json` 读取，路径 =
  环境变量 `CORTICO_PINS_JSON`。没给就报错，不回落。
- MaiBot WebUI 8001 本轮未起宿主未实测，装机以 doctor 实扫为准（§6.3 欠账）。

## 自检

```
PY312M=C:/Users/54301/tmp/botfw-envs/maibot-py312/Scripts/python.exe
cd <本仓>
$PY312M -I -m pytest tests -q                      # 全套离线（条数随工单变，不写死）
$PY312M -I -m pytest tests/test_manifest.py -q     # 真调宿主 ManifestValidator
$PY312M -I -m pytest tests/test_sender.py -q       # 发信腿：门、码、缓存表
```

测试全部离线：宿主模块只做 import 级自省，RPC 走本地记录桩（r-maibot §3/§6 同法），
零网络、零宿主进程。

## 边界与欠账

- 出站 send 腿已接线，但**真机派发路径未起宿主实测**：`plugin.cbp_gateway` 的回执形状
  有单测（成功 + 三类失败），宿主的 `invoke_message_gateway` 实际调用只证到代码路径。
- `send.image` / `chat.open_session` 未实调，因此不进 `hello.tools` 申报面，也不进
  `_manifest.json` capabilities（申报不可达=撒谎）。
- `host.route_message` 之后的 route_key 生成与同 platform 并发未起宿主，按保守面写。
- `gateway.route_message` / `gateway.update_state` 声明沿用内置 weixin 适配器先例
  （§7：能力名声明与 cap.call 注册表是两套命名）；manifest_scan 工具接棒后以并集
  口径替换手抄 capabilities。
- EventHandler 组件 metadata 的落键形状只做了宽松断言（test_observer），真机派发
  参数面待沙箱卡回填。

---

## 安全声明（2026-11-19 · 对端能力面已收敛）

本仓是框架侧插件，**不是 Cortico 扩展**，没有 `cortico.tags`，无法在索引仓自声明
`unsafe`。对端 world 包 `cortico-world-maibot` 上一轮曾拟按 11-13 判例声明，
但该声明**从未发布即撤回**：`TAGS.md:40` 的不可撤回约束针对已发布版本；平台也没有
`safe` 标签（`TAGS.md:42`），缺席只代表「未声明且未审查」。处理方式改为收敛能力面。

本仓承担 dial 腿的鉴权收口：

- `pins.auth_headers()` 缺 `CORTICO_BRIDGE_TOKEN` 抛 `RuntimeError`，不再返回空头；
- `run()` / `_link_loop()` 入口 fail-shut：缺密钥零拨号、不进重连循环、只留一条日志；
- 凭据只走 `Authorization: Bearer` Upgrade 头，URI 判脏即拒；
- 能力面：`egress` 默认关、工具目录静态、未申报能力本地判 60002。

**迁移（破坏性）**：插件进程环境变量必须设 `CORTICO_BRIDGE_TOKEN`，值与 Cortico 侧
`ctx.secret('CORTICO_BRIDGE_TOKEN')` 逐字相同；未设时桥静默断连是设计行为。

验证：`pytest tests/ -q` 全量通过；`tests/test_credentials.py` 覆盖取数口、
URL 面、拨号面与静态闸。

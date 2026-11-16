"""本桥对外申报的 CBP 能力名单的唯一来源（single source）。

纪律：这份名单必须与 Cortico 侧 manifest（fleet
`cortico-world-maibot/src/world.ts:53` 的 `WORLD_CAPS`）集合相等，
由 `tests/test_caps_consistency.py` 双向锁死，任一侧漂移即红（SECURITY-CBP §60）。
名字都必须在内核词表内——单源是 fleet `spec/pins.json` `vocab.cbp.caps`，内核运行时同读
该件（`cortico-bridge-core/src/pins.ts` capsVocabOf）；词表外的名字协商时被
`intersectCaps` 静默丢弃，写了也不生效。
`buttons` / `audio_out` / `history_backfill` 不宣：v1 无该能力，与 Cortico 侧同断。
`files` / `self_echo` 不宣：本桥零文件附件路径、零自回声行为，与 Cortico 侧同断
（理由见 fleet `world.ts:48-49`：files=零附件路径；self_echo 只能与 proven:true 同现，
SECURITY-CBP:77，报出即超发许可）。
"""
from __future__ import annotations

BRIDGE_CAPS: tuple[str, ...] = ("images", "notices", "tools")

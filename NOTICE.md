# Attribution and third-party material

The GR III DOOM adapter, camera integration and build/verification tools are
provided under GPL-2.0-only; the full text is in LICENSE.

The following files were extracted from
[Maxwooow/Ricoh-GRMod](https://github.com/Maxwooow/Ricoh-GRMod), commit
`1f4216e4b80d737a3e670c0b6169398f57598b5e`, under GPL-2.0-only:

Extraction and the modifications listed below were made on November 1, 2026.

| Local file | Upstream source / changes |
| --- | --- |
| `vendor/grmod/container.ts` | `core/src/fw/container.ts`, unchanged apart from LF normalization |
| `vendor/grmod/types.ts` | `core/src/fw/types.ts`, unchanged apart from LF normalization |
| `vendor/grmod/identity.py` | `tools/gr3x/identity.py`, unchanged apart from LF normalization |
| `vendor/grmod/native_probe.py` | `tools/gr3x/native_probe.py`, reduced to the NativeProbe helper and its setup |
| `vendor/grmod/loader_probe.py` | `tools/gr3x/loader_probe.py`, tiny word helpers inlined to remove an unrelated module dependency; explicit UTF-8 for reports |
| `tests/fixtures/parse-fuzz.json` | `core/test/fw-helpers/parse-fuzz.json`, public synthetic parser oracles |

The port builds on the upstream GR III research into LiveViewController, the
Aspect Ratio Fn action, raw switch events, native timers and ScreenBuffer layout.
This is a separate experimental project and does not imply upstream endorsement.

PureDOOM is by Daivuk and its contributors, based on DOOM by id Software. The
pinned dependency is commit `355cfbd16fac119718879239336ee2ea408886bd` of
[Daivuk/PureDOOM](https://github.com/Daivuk/PureDOOM). Its original DOOM Source Code
License is separate from this repository's GPL. Obtain and retain the dependency's
own notices locally. The header and IWAD are not vendored here. No licence to
redistribute a combined firmware artifact is asserted.

`docs/gameplay.png` captures the actual ARM game running in an emulator. DOOM
game imagery belongs to its respective rights holders and is shown to document
the port; it is not covered by the source-code GPL grant.

RICOH and DOOM are trademarks of their respective owners. The official camera
firmware and generated candidates remain local inputs/outputs and are excluded
from this public source repository.

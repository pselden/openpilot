# ui

The user interfaces here are built with [raylib](https://www.raylib.com/).

Quick start:
* set `BIG=1` to run the comma 3X UI (comma four UI runs by default)
* set `SHOW_FPS=1` to show the FPS
* set `STRICT_MODE=1` to kill the app if it drops too much below 60fps
* set `SCALE=1.5` to scale the entire UI by 1.5x
* set `BURN_IN=1` to get a burn-in heatmap version of the UI
* set `GRID=50` to show a 50-pixel alignment grid overlay
* set `MAGIC_DEBUG=1` to show every dropped frames (only on device)
* set `RECORD=1` to record the screen, output defaults to `output.mp4` but can be set with `RECORD_OUTPUT`
* set `SUNNYPILOT_UI=0` to run the stock UI instead of the sunnypilot UI
* set `PRIME_TYPE` to preview pairing/Prime status: `-1` unpaired, `0` paired without Prime, `2` Prime Lite, `1` Prime Full
* set `PAIRING_PROVIDER` to preview the different states based on connect auth providers `google`, `github` or `apple`
* https://www.raylib.com/cheatsheet/cheatsheet.html
* https://electronstudio.github.io/raylib-python-cffi/README.html#quickstart

Style guide:
* All graphical elements should subclass [`Widget`](/openpilot/system/ui/widgets/__init__.py).
  * Prefer a stateful widget over a function for easy migration from QT
* All internal class variables and functions should be prefixed with `_`

## Odyssey startup animation

The startup spinner displays a Smoke Blue Pearl Odyssey with rotating wheels and
a scrolling road, adapted from brikowski's artwork. It retains numeric progress and startup text on both display
sizes. Preview with `BIG=1 python -m openpilot.system.ui.spinner`.

Ported from `brikowski/openpilot:ody-op-test` at
`434780d9e59b0c080d8f5212bda5f39afa7decf5`, including the matching shader-version
fix. The illustration is stored directly in Git to avoid fork-specific LFS failures.
Wheel coordinates and rendering are in `lib/odyssey_scene.py`.

The matching early-OS wrapper and firmware splash packer are in
`openpilot/tools/odyssey_boot.py`. These stages need the one-time device setup
described in [the boot-theme guide](/docs/odypilot-boot.md).

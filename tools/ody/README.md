# OdyPilot validation tools

The app development branch is `pselden/openpilot:sp-ody-dev`. Its gitlink selects
an exact commit in `pselden/opendbc`; the matching published vehicle branch is
also `sp-ody-dev`. The stable comparison branch is `pselden/openpilot:sp-ody`.

Ubuntu is not required for the focused checks. Apple Silicon macOS is a supported
build target in this checkout, and the focused app, Honda controller/HUD, and
Honda safety C tests have run on macOS. That does not replace a complete Linux
build or validation on the comma's QCOM hardware.

| Check | macOS | What remains separate |
|---|---|---|
| Focused app/controller/safety tests | Native; `prepush.sh --quick` | Complete app/opendbc suites and MISRA |
| Full host build | Darwin target supported; `build_pc.sh` | Linux/device build coverage |
| Model inference | `checks/model_e2e.py` after building/downloading models | Device inference, timing, temperature |
| Settings rendering | Requires a working graphics session | Actual comma UI/display behavior |
| Recorded-drive replay | Requires full build artifacts and full rlogs; Mac execution not yet validated | Physical vehicle response |
| Full opendbc suite/MISRA | Needs the suite's compiler/cppcheck dependencies; use Linux CI/VM if unavailable | Vehicle validation |

No helper installs code on the comma, changes AGNOS, or installs the early boot theme.

## Build and focused checks

Prerequisites: Git, git-lfs, the host compiler/toolchain, and the dependencies in
`tools/setup_dependencies.sh`. On macOS, install Xcode Command Line Tools and
Git LFS first. Use a working graphics session for rendering checks.

```bash
# Creates a separate clone of OUR repository, not Patrick's fork.
tools/ody/build_pc.sh sp-ody-dev "$HOME/odypilot-dev"
cd "$HOME/odypilot-dev"
tools/ody/prepush.sh --quick
```

An existing destination must have the expected origin and a clean working tree.
The build helper only fast-forwards existing branches; it never resets local
commits or discards files. Choose another destination if it refuses one.

`JOBS` controls parallelism (default: at most four cores). `ODY_VENV` selects an
already prepared environment instead of `.venv`; otherwise an active environment
is used when available. The scripts put this checkout's submodules first on
`PYTHONPATH` so an installed opendbc package cannot replace the pinned source.

```bash
# Existing built checkout, including this Mac's prepared environment:
ODY_VENV=/path/to/venv tools/ody/prepush.sh --quick
# Only Honda controller/HUD/safety tests, using the built app environment:
tools/ody/opendbc_test.sh --focused
```

A quick pass is explicitly a focused host result. It does not mean the build,
model inference, graphics, full suites, release migration audit, or device checks passed. If drive logs
are supplied, the quick run also attempts their replay checks.

## Complete host checks

```bash
tools/ody/prepush.sh --rlogs /path/to/rlogs --target pselden/sp-ody
# Also run the full pinned opendbc suite and stable-vs-dev Honda process replay:
tools/ody/prepush.sh --full --rlogs /path/to/rlogs --target pselden/sp-ody
```

The default run builds the tree, runs stock driving/driver-monitoring inference,
checks the live model catalog and LFS availability, scans imports/Params/services,
runs app and Honda/safety tests, renders settings, and replays a recorded drive.
It no longer suppresses locationd failures through broad deselection/retry rules;
failures need investigation. Network checks and the process-replay reference
routes need network access. The full suite may require Linux-specific tools.

Each step has its own log in the printed temporary directory. Exit 1 means a
failed check; exit 2 means required drive replay is missing. A missing comparison
ref is reported as a warning: fetch stable or provide an available `--target`.
Passing host checks still leaves device inference/timing and vehicle operation
unvalidated. Catalog/header checks alone do not prove model inference.

The stable-to-development migration audit currently flags `LastGPSPosition`
changing from STRING to BYTES in MVL/upstream. Mapd's memory-parameter writers
were adapted, but the persistent cache's old-format handling in pigeond still
needs review before advancing stable. This is retained as a release-audit failure,
not silently waived by the focused checks.

`opendbc_test.sh` without arguments tests the app's pinned checkout and does not
fetch or switch its branch. To investigate a different published vehicle branch
in a separate clone, use `opendbc_test.sh sp-ody-dev /path/to/vehicle-clone`.
The full suite uses a test-only Params shim and returns failure if `test.sh` fails.
App-integrated tests use the real Params implementation.

## Replay existing Odyssey drives

Use full `rlog.zst` files copied from the comma, rather than treating sparse qlogs
as equivalent. `--rlogs` points to a directory of segment directories containing
`rlog.zst`. The runner selects the most recently modified segment; deliberately
select representative segments for stops, hills, highway steering, and lane changes.

```bash
python tools/ody/replay_segments.py /path/to/segment /path/to/another/rlog.zst
python tools/ody/checks/factory_mode.py /path/to/segment
python tools/ody/checks/turn_lane_change.py /path/to/rlogs
python tools/ody/checks/lead_depart_chime.py /path/to/rlogs
```

`replay_segments.py` runs card and controlsd. Crashes, missing required output,
invalid messages, and nonfinite commands return failure. Reports show the
fingerprint, safety settings, delay, and command ranges. Frame counts can vary in
the replay harness; outputs are not proof of closed-loop vehicle behavior.

`replay_ab.sh` defaults to our stable `sp-ody`, using a separate baseline clone.
It checks baseline failures rather than swallowing them, preserves an existing
`ref_commit` file, and propagates the comparison exit code. Intentional differences
still require review; changing reference files is not an acceptance criterion.

## After host validation

On the parked device, confirm the exact commit pair, successful build, healthy
model/driver-monitoring processes, calibration, settings, Factory mode across an
ignition cycle, and absence of persistent CAN/Panda/radar errors. Initial checks
use the normal torque controller with NNLC and manual torque overrides off.
The 4096 normalization and its limits are documented in
[the integration audit](../../docs/odypilot-mvl-20261108.md).

Controlled vehicle checks and review of their logs follow parked checks. Inspect
steering tracking/oscillation, acceleration/braking response, disengagements,
safety TX blocks, model timing, and temperature. Check braking, CANCEL, and LKAS
separately: MADS can retain lateral control when longitudinal control disengages.
Do not deliberately force the steering ceiling as a test.

Drive-report helpers in `drive_report/` and the load simulation in
`opendbc_repo/opendbc/car/honda/tests/odyssey_load_sim.py` remain diagnostic tools;
they do not replace those checks.

## Updating upstream

Use MVL as the integration upstream for both repositories. Preserve Odyssey code
in the vehicle module and small platform hooks, and carry personal app features
separately. Do not independently merge newer comma model code without auditing
sunnypilot's runtime/model pins. Do not reintroduce DEC from Patrick's branch.
Run `freshness.sh` for an informational comparison; mirroring every MVL branch
in our fork is not required. Validate both app and vehicle commits before
advancing `sp-ody`.

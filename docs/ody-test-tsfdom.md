# TSFDOM model compatibility branch

`pselden/openpilot:ody-test` starts at Patrick's `ody-test` commit
`18e36a3a7d87a7acc98dd531bf6e8795c961c35a` and imports these sunnypilot changes:

- `4ff90ff8d074455141c8b5918131e59c9f6c2bf7`: load plain GPU artifacts and use model catalog v25 / selector version 21.
- `e6864661c986f395a92c06674dab407ba35030f9`: convert upstream artifacts and combine camera-warp kernels with model execution.
- Register the imported `ChestnutRetry` parameter with the same flags as upstream.

The tinygrad pin remains `69fd4d34d4430036378aba2b43f9d339cdd6ea73`.
Odyssey vehicle code, steering and longitudinal control, SPLC, and the settings
profile are unchanged from Patrick's base.

## Why

The previous catalog v23 TSFDOM artifact fails to unpickle with this runtime:
`AttributeError: 'pickle.PickleBuffer' object has no attribute '_base'`.
The model process exits before publishing camera odometry, leaving calibration at 0%.
The new loader and catalog use the same trained TSFDOM network in a plain artifact
format, with runtime-specific execution objects rebuilt on load.

## Select the model after switching branches

1. In the fork/branch switcher, choose `pselden/openpilot` and `ody-test`, then restart while parked.
2. Open Models, select TSFDOM for Small Model, and let the download and offroad warmup finish.

The old selector-version-20 model selection resets to Default during validation.
This is expected: selecting TSFDOM again downloads the version-21 artifact instead
of loading the old cached compilation. Existing driving preferences are preserved.

The expected TSFDOM artifact is from `recompiled44`, size 126,298,916 bytes,
SHA-256 `dad05dca91ccb2302ff421b6d0dfd4c2fe93738f0de7e230c5d93dbd55a115ae`.
The filename still ends in `.pkl`, but its format header is `SPTGPLN1`.

## Validation

The branch adds CPU regression tests for compiled-model loading, inference with
changed inputs, persistent cache reloads, reference-output verification, and
rejection of the legacy pickle format. The TSFDOM download was hash-checked and
parsed with the new loader, including both camera resolutions. All 293 installer
LFS assets were verified present on the configured host.

The focused model-download, default-model, compiler, loader, fallback, and artifact
suite passed on macOS: **152 passed, 5 skipped**. Skips cover an external-network
test, the absent big-model ONNX, and three comparisons with upstream APIs that
were removed. Lint, workflow YAML parsing, and registered-parameter checks passed.
The native parameter and messaging libraries were built for these tests. The
full Linux pre-push/vehicle-replay suite was not run.

Full TSFDOM QCOM execution, on-device timing, and calibration progress must still
be verified on the comma. Parsing the artifact and testing a small CPU model do
not validate vehicle operation.

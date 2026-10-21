import pickle

import numpy as np
import pytest
from tinygrad import Tensor, TinyJit

from openpilot.sunnypilot.modeld_v2.helpers import ArtifactMismatch, cache_is_fresh, load_model, read_parts, write_bundle
from openpilot.sunnypilot.modeld_v2.plain_artifact_compiler import capture_frame, record_kernel_linear, serialize_jit


def make_artifact(path, *, bad_reference=False):
  inputs = Tensor(np.arange(16, dtype=np.float32), device="CPU")
  model = TinyJit(lambda x: (x * 2 + 3).realize())
  with record_kernel_linear() as kernels:
    model(x=inputs)
    model(x=inputs)
  reference, _ = capture_frame(model, {"x": inputs})
  if bad_reference:
    reference["outputs"][0] += 100
  part = serialize_jit(model, kernels[-1], reference)
  write_bundle(str(path), {"run": part}, {"metadata": {"name": "loader regression"}})
  return inputs


@pytest.mark.parametrize("cache", [False, True])
def test_plain_model_runs_with_changed_inputs(tmp_path, cache):
  path = tmp_path / "model.pkl"
  inputs = make_artifact(path)
  model = load_model(str(path), cache=cache)
  assert model["metadata"]["name"] == "loader regression"

  for offset in (0, 5):
    values = np.arange(16, dtype=np.float32) + offset
    inputs.assign(Tensor(values, device="CPU")).realize()
    np.testing.assert_allclose(model["run"](x=inputs).numpy(), values * 2 + 3)

  if cache:
    assert cache_is_fresh(str(path))
    restored = load_model(str(path))
    np.testing.assert_allclose(restored["run"](x=inputs).numpy(), values * 2 + 3)


def test_plain_model_rejects_wrong_reference_output(tmp_path):
  path = tmp_path / "model.pkl"
  make_artifact(path, bad_reference=True)
  with pytest.raises(ArtifactMismatch, match="differs from the compile-time reference"):
    load_model(str(path), cache=False)


def test_legacy_pickle_requires_new_artifact(tmp_path):
  path = tmp_path / "legacy.pkl"
  path.write_bytes(pickle.dumps({"run": "legacy compiled model"}))
  with pytest.raises(ValueError, match="recompile it with compile_modeld.py"):
    read_parts(str(path))

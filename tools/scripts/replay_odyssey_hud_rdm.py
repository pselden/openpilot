#!/usr/bin/env python3
"""Audit recorded Honda HUD TX and camera faults; never transmit CAN or regenerate TX.

RDM_OFF is a HUD field, not an acknowledgement that the camera has disabled RDM.
A transmitted RDM_OFF bit must therefore be reported separately from RDM_PROBLEM.
"""
import argparse
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
import json
from pathlib import Path


HUD_SIZES = {0x33D: 5, 0x33DA: 5, 0x33DB: 8}
RADAR_DISABLE = bytes.fromhex("0328830300000000")


@dataclass(frozen=True)
class CanSample:
  time: float
  source: int
  address: int
  data: bytes


@dataclass
class HudSummary:
  samples: int = 0
  rdm_off_set: int = 0
  rdm_problem_set: int = 0
  first_problem_time: float | None = None

  def observe(self, sample: CanSample) -> None:
    self.samples += 1
    self.rdm_off_set += bool(sample.data[3] & 0x08)
    problem = bool(sample.data[2] & 0x20)
    self.rdm_problem_set += problem
    if problem and self.first_problem_time is None:
      self.first_problem_time = sample.time


@dataclass
class HudAudit:
  transmitted: dict[str, HudSummary] = field(default_factory=dict)
  rejected: dict[str, int] = field(default_factory=dict)
  camera: dict[str, HudSummary] = field(default_factory=dict)
  radar_disable_transmitted: list[float] = field(default_factory=list)

  @property
  def camera_result(self) -> str:
    if not self.camera:
      return "not_observed"
    if any(summary.rdm_problem_set for summary in self.camera.values()):
      return "fault_observed"
    return "fault_not_observed"


def audit_samples(samples: Iterable[CanSample], hud_bus: int = 1, camera_bus: int = 2) -> HudAudit:
  """Use Panda TX echoes (128 + bus); rejected echoes (192 + bus) are not TX.

  These defaults describe the non-CAN-FD Odyssey Bosch alpha-long layout.
  Decode the single-bit fields using the definitions shared by LKAS_HUD/A/B.
  Camera-origin A/B must not be combined with generated or echoed cluster HUD.
  """
  result = HudAudit()
  for sample in sorted(samples, key=lambda sample: sample.time):
    if sample.source == hud_bus + 128 and sample.address == 0x18DAB0F1 and sample.data == RADAR_DISABLE:
      result.radar_disable_transmitted.append(sample.time)
    if sample.address not in HUD_SIZES or len(sample.data) != HUD_SIZES[sample.address]:
      continue
    address = hex(sample.address)
    if sample.source == hud_bus + 128:
      result.transmitted.setdefault(address, HudSummary()).observe(sample)
    elif sample.source == hud_bus + 192:
      result.rejected[address] = result.rejected.get(address, 0) + 1
    elif sample.source == camera_bus and sample.address in (0x33DA, 0x33DB):
      result.camera.setdefault(address, HudSummary()).observe(sample)
  return result


def read_samples(rlog: Path, start: float, end: float) -> list[CanSample]:
  # Load only schemas and decompression support, not vehicle control code.
  import capnp
  import zstandard as zstd

  root = Path(__file__).resolve().parents[2]
  cereal = root / "openpilot/cereal"
  schema = capnp.load(str(cereal / "log.capnp"), imports=[str(root / "opendbc_repo/opendbc/car")])
  with rlog.open("rb") as compressed, zstd.ZstdDecompressor().stream_reader(compressed) as stream:
    data = stream.read()
  samples = []
  first_can_time = None
  for event in schema.Event.read_multiple_bytes(data):
    if event.which() != "can":
      continue
    time = event.logMonoTime / 1e9
    if first_can_time is None:
      first_can_time = time
    time -= first_can_time
    if not start <= time <= end:
      continue
    samples.extend(CanSample(time, msg.src, msg.address, bytes(msg.dat)) for msg in event.can)
  return samples


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("rlog", type=Path, help="path to a Honda Odyssey rlog.zst segment")
  parser.add_argument("--t-start", type=float, default=0.0, help="seconds from first CAN event in this segment")
  parser.add_argument("--t-end", type=float, default=float("inf"))
  args = parser.parse_args()
  if args.t_start < 0 or args.t_end < args.t_start:
    parser.error("time window must satisfy 0 <= t-start <= t-end")
  result = audit_samples(read_samples(args.rlog, args.t_start, args.t_end))
  print(json.dumps({
    **asdict(result),
    "camera_result": result.camera_result,
    "interpretation": "TX confirmation establishes bus transmission, not camera acceptance or handsfree-timer suppression.",
  }, indent=2))


if __name__ == "__main__":
  main()

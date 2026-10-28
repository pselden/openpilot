"""Readable UTC destinations; local route/file names remain unchanged."""
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import capnp
import zstandard as zstd

from openpilot.cereal import log

LABELS = {
  'fcamera.hevc': 'road-main.hevc',
  'ecamera.hevc': 'road-wide.hevc',
  'dcamera.hevc': 'cabin.hevc',
  'qcamera.ts': 'road-preview.ts',
  'rlog.zst': 'full-log.zst',
  'qlog.zst': 'quick-log.zst',
  'qlog': 'quick-log',
}
HEADER_LIMIT = 1024 * 1024


def timestamp(nanoseconds: int) -> str:
  return datetime.fromtimestamp(nanoseconds // 1_000_000_000, UTC).strftime('%Y-%m-%d_%H-%M-%S_UTC')


@lru_cache(maxsize=2048)
def log_times(path: Path, size: int, modified: int) -> tuple[int, int] | None:
  """Read the route's initData and this segment's opening sentinel, not an entire log."""
  try:
    with path.open('rb') as source:
      if path.suffix == '.zst':
        with zstd.ZstdDecompressor().stream_reader(source) as reader:
          data = reader.read(HEADER_LIMIT)
      else:
        data = source.read(HEADER_LIMIT)
    events = iter(log.Event.read_multiple_bytes(data))
    init = next(events)
    sentinel = next(events)
    if init.which() != 'initData' or sentinel.which() != 'sentinel':
      return None
    wall = int(init.initData.wallTimeNanos)
    elapsed = int(sentinel.logMonoTime) - int(init.logMonoTime)
    if not 946684800_000000000 <= wall < 4102444800_000000000 or elapsed < 0:
      return None
    return wall, wall + elapsed
  except (OSError, ValueError, StopIteration, capnp.KjException, zstd.ZstdError):
    return None


def segment_times(directory: Path) -> tuple[int, int] | None:
  for name in ('qlog.zst', 'rlog.zst', 'qlog'):
    path = directory / name
    try:
      if path.is_symlink():
        continue
      stat = path.stat()
    except FileNotFoundError:
      continue
    if result := log_times(path, stat.st_size, stat.st_mtime_ns):
      return result
  return None


def destination(path: Path, device: str, modified: int) -> str:
  route, number = path.parent.name.rsplit('--', 1)
  times = segment_times(path.parent)
  if times is None:
    # A filesystem timestamp describes when a file was saved, not a proven recording start.
    folder = f'undated-drive--{route}'
    segment_folder = f'segment-{int(number):04d}--time-unavailable'
    prefix = f'{timestamp(modified)}--saved-at'
  else:
    start, segment = times
    folder = f'{timestamp(start)}--drive-{route}'
    prefix = timestamp(segment)
    segment_folder = f'{prefix}--segment-{int(number):04d}'
  return f'/{device}/{folder}/{segment_folder}/{prefix}--{LABELS[path.name]}'

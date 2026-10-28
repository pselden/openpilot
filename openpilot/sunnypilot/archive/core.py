import hashlib
import os
import re
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

from openpilot.sunnypilot.archive.naming import destination


class ArchiveError(Exception):
  """A safe, user-visible message, without HTTP bodies, URLs, or credentials."""


class Paused(ArchiveError):
  pass


def json_object(value: object) -> dict[str, object]:
  if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
    raise ArchiveError('Invalid archive data')
  return {str(k): v for k, v in value.items()}


def text_field(value: dict[str, object], key: str) -> str:
  result = value.get(key)
  if not isinstance(result, str) or not result:
    raise ArchiveError('Invalid archive authorization data')
  return result


@dataclass(frozen=True)
class Recording:
  path: Path
  key: str
  size: int
  stamp: str
  destination: str = ''

  @property
  def remote_path(self) -> str:
    return self.destination or self.key

  @staticmethod
  def fingerprint(stat: os.stat_result) -> str:
    return f"{stat.st_dev}:{stat.st_ino}:{stat.st_size}:{stat.st_mtime_ns}"

  def unchanged(self) -> bool:
    return not self.path.is_symlink() and self.fingerprint(self.path.stat()) == self.stamp


@dataclass(frozen=True)
class Checkpoint:
  session: str = ""
  offset: int = 0
  created: float = 0.0


@dataclass(frozen=True)
class Receipt:
  revision: str
  content_hash: str


class StorageProvider(Protocol):
  identity: str

  def upload(self, recording: Recording, checkpoint: Checkpoint,
             save: Callable[[Checkpoint], None], allowed: Callable[[], bool]) -> Receipt: ...


@dataclass(frozen=True)
class ArchivePolicy:
  enabled: bool = False
  onroad: bool = False
  network: int = 0  # 0: unmetered Wi-Fi, 1: any unmetered, 2: metered allowed
  logs: bool = True
  road: bool = True
  preview: bool = False
  cabin: bool = False

  def permits(self, started: bool, connected: bool, wifi: bool, metered: bool, fresh: bool) -> bool:
    return (self.enabled and fresh and connected and (not started or self.onroad) and
            self.network in (0, 1, 2) and (self.network != 0 or wifi) and (self.network == 2 or not metered))

  def filenames(self) -> set[str]:
    return ({"rlog.zst", "qlog.zst", "qlog"} if self.logs else set()) | \
           ({"fcamera.hevc", "ecamera.hevc"} if self.road else set()) | \
           ({"qcamera.ts"} if self.preview else set()) | ({"dcamera.hevc"} if self.cabin else set())


def recordings(root: Path, device: str, policy: ArchivePolicy) -> Iterator[Recording]:
  """Only immutable, unlocked regular recordings; never follow a source symlink."""
  if not re.fullmatch(r"[A-Za-z0-9_-]+", device):
    raise ArchiveError("Device identity is not available")
  if not root.is_dir():
    return
  for segment in sorted(root.iterdir()):
    if segment.is_symlink() or not segment.is_dir() or not re.fullmatch(r"[A-Za-z0-9_.-]+--[0-9]+", segment.name):
      continue
    try:
      files = list(segment.iterdir())
      if any(p.name.endswith(".lock") for p in files):
        continue
      for path in sorted(files):
        if path.name in policy.filenames() and not path.is_symlink() and path.is_file():
          stat = path.stat()
          yield Recording(path, f"/{device}/{segment.name}/{path.name}", stat.st_size, Recording.fingerprint(stat),
                          destination(path, device, stat.st_mtime_ns))
    except FileNotFoundError:  # normal disk-pressure cleanup can race discovery
      continue


def content_hash(stream: BinaryIO) -> str:
  """Dropbox's SHA-256 of the SHA-256 digests of consecutive 4 MiB blocks."""
  result = hashlib.sha256()
  while block := stream.read(4 * 1024 * 1024):
    result.update(hashlib.sha256(block).digest())
  return result.hexdigest()


class Journal:
  def __init__(self, path: Path):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.close(os.open(path, os.O_CREAT | os.O_WRONLY, 0o600))
    path.chmod(0o600)
    self.db = sqlite3.connect(path)
    self.db.execute("PRAGMA journal_mode=WAL")
    self.db.execute("""CREATE TABLE IF NOT EXISTS uploads (
      provider TEXT, key TEXT, path TEXT, stamp TEXT, size INTEGER,
      status TEXT DEFAULT 'pending', session TEXT DEFAULT '', offset INTEGER DEFAULT 0,
      created REAL DEFAULT 0, revision TEXT DEFAULT '', digest TEXT DEFAULT '',
      PRIMARY KEY(provider, key))""")
    if 'destination' not in {row[1] for row in self.db.execute('PRAGMA table_info(uploads)')}:
      self.db.execute("ALTER TABLE uploads ADD COLUMN destination TEXT NOT NULL DEFAULT ''")
    self.db.commit()

  def discover(self, provider: str, items: Iterator[Recording]) -> None:
    with self.db:
      for item in items:
        self.db.execute("""INSERT INTO uploads(provider,key,path,stamp,size,destination) VALUES(?,?,?,?,?,?)
          ON CONFLICT(provider,key) DO UPDATE SET path=excluded.path, stamp=excluded.stamp,
          size=excluded.size,destination=excluded.destination,status='pending',session='',offset=0,created=0,revision='',digest=''
          WHERE uploads.stamp != excluded.stamp""", (provider, item.key, str(item.path), item.stamp, item.size, item.remote_path))

  def next(self, provider: str, filenames: set[str]) -> tuple[Recording, Checkpoint] | None:
    for key, path, stamp, size, session, offset, created, remote in self.db.execute(
        """SELECT key,path,stamp,size,session,offset,created,destination FROM uploads
        WHERE provider=? AND status='pending' ORDER BY COALESCE(NULLIF(destination,''),key)""", (provider,)):
      item = Recording(Path(path), key, size, stamp, remote)
      try:
        valid = item.unchanged()
      except FileNotFoundError:
        valid = False
      if not valid:
        with self.db:
          self.db.execute("UPDATE uploads SET status='missing' WHERE provider=? AND key=?", (provider, key))
      elif item.path.name in filenames:
        return item, Checkpoint(session, offset, created)
    return None

  def checkpoint(self, provider: str, key: str, checkpoint: Checkpoint) -> None:
    with self.db:
      self.db.execute("UPDATE uploads SET session=?,offset=?,created=? WHERE provider=? AND key=?",
                      (checkpoint.session, checkpoint.offset, checkpoint.created, provider, key))

  def complete(self, provider: str, key: str, receipt: Receipt) -> None:
    with self.db:
      self.db.execute("UPDATE uploads SET status='done',revision=?,digest=?,session='' WHERE provider=? AND key=?",
                      (receipt.revision, receipt.content_hash, provider, key))

  def counts(self, provider: str) -> dict[str, int]:
    return dict(self.db.execute("SELECT status,COUNT(*) FROM uploads WHERE provider=? GROUP BY status", (provider,)))

  def close(self) -> None:
    self.db.close()

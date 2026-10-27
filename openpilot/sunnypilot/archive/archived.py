"""Opt-in archives. Source deletion and existing upload marks are never modified."""
import threading
import time
from functools import partial
from pathlib import Path

import requests

from openpilot.cereal import log, messaging
from openpilot.common.hardware.hw import Paths
from openpilot.common.params import Params
from openpilot.sunnypilot.archive.auth import CredentialStore, state_root
from openpilot.sunnypilot.archive.core import ArchiveError, ArchivePolicy, Checkpoint, Journal, Paused, Recording, recordings
from openpilot.sunnypilot.archive.dropbox import DropboxError, DropboxProvider


def policy(params: Params) -> ArchivePolicy:
  return ArchivePolicy(enabled=params.get_bool('ArchiveEnabled'), onroad=params.get_bool('ArchiveOnroad'),
                       network=params.get('ArchiveNetwork', return_default=True),
                       logs=params.get_bool('ArchiveLogs', return_default=True),
                       road=params.get_bool('ArchiveRoad', return_default=True),
                       preview=params.get_bool('ArchivePreview'), cabin=params.get_bool('ArchiveCabin'))


def save_progress(journal: Journal, provider: str, recording: Recording, params: Params, checkpoint: Checkpoint) -> None:
  journal.checkpoint(provider, recording.key, checkpoint)
  percent = 100 * checkpoint.offset // max(1, recording.size)
  params.put('ArchiveStatus', f'Uploading {recording.path.name}: {percent}%')


def main(exit_event: threading.Event | None = None) -> None:
  stop = exit_event or threading.Event()
  params = Params()
  store = CredentialStore(state_root())
  journal = Journal(store.root / 'uploads.sqlite')
  sm = messaging.SubMaster(['deviceState'])
  provider = None
  last_scan = -60.0
  retry_at, backoff = 0.0, 5.0

  def permitted(filename: str | None = None) -> bool:
    sm.update(0)
    current = policy(params)
    state = sm['deviceState']
    fresh = sm.seen['deviceState'] and sm.valid['deviceState'] and time.monotonic() - sm.recv_time['deviceState'] < 10
    return (not stop.is_set() and current.permits(not params.get_bool('IsOffroad'),
            state.networkType != log.DeviceState.NetworkType.none, state.networkType == log.DeviceState.NetworkType.wifi,
            state.networkMetered, fresh) and (filename is None or filename in current.filenames()) and
            provider is not None and store.load() == provider.credentials)

  try:
    while not stop.is_set():
      try:
        credentials = store.load()
        if credentials is None:
          params.put('ArchiveStatus', 'Not connected — link Dropbox on the device')
        elif not policy(params).enabled:
          params.put('ArchiveStatus', 'Connected — backup disabled')
        else:
          if provider is None or credentials != provider.credentials:
            provider = DropboxProvider(credentials)
            last_scan, retry_at, backoff = -60.0, 0.0, 5.0
          if not permitted():
            params.put('ArchiveStatus', 'Paused — waiting for permitted network / parked state')
          elif time.monotonic() < retry_at:
            pass
          else:
            device = params.get('DongleId') or ''
            if time.monotonic() - last_scan >= 60:
              journal.discover(provider.identity, recordings(Path(Paths.log_root()), device, policy(params)))
              last_scan = time.monotonic()
            selected = journal.next(provider.identity, policy(params).filenames())
            if selected is not None:
              recording, checkpoint = selected
              params.put('ArchiveStatus', f'Backing up {recording.path.parent.name}/{recording.path.name}')
              receipt = provider.upload(recording, checkpoint,
                partial(save_progress, journal, provider.identity, recording, params),
                partial(permitted, recording.path.name))
              journal.complete(provider.identity, recording.key, receipt)
              backoff = 5.0
            counts = journal.counts(provider.identity)
            params.put('ArchiveStatus', f"Connected — {counts.get('pending', 0)} pending, {counts.get('done', 0)} backed up, " +
                       f"{counts.get('missing', 0)} unavailable locally")
      except Paused:
        params.put('ArchiveStatus', 'Backup paused')
      except (ArchiveError, OSError, ValueError, requests.RequestException) as error:
        # Do not log exception bodies or URLs: HTTP failures can contain credentials.
        message = str(error) if isinstance(error, ArchiveError) else 'Backup temporarily unavailable'
        params.put('ArchiveStatus', message)
        delay = max(backoff, error.retry_after if isinstance(error, DropboxError) else 0)
        retry_at, backoff = time.monotonic() + delay, min(backoff * 2, 300)
      stop.wait(2)
  finally:
    journal.close()


if __name__ == '__main__':
  main()

import base64
import hashlib
import io
import json
import stat
import sqlite3
from dataclasses import replace
from urllib.parse import parse_qs, urlparse

import pytest
import requests
import zstandard as zstd

from openpilot.cereal import log

from openpilot.sunnypilot.archive import dropbox
from openpilot.sunnypilot.archive.auth import CredentialStore, Credentials, begin_link, disconnect, finish_link
from openpilot.sunnypilot.archive.core import ArchiveError, ArchivePolicy, Checkpoint, Journal, Paused, content_hash, recordings
from openpilot.sunnypilot.archive.dropbox import DropboxError, DropboxProvider
from openpilot.sunnypilot.archive.naming import destination


@pytest.fixture
def recording(tmp_path):
  segment = tmp_path / 'logs' / '00000001--abcdef--0'
  segment.mkdir(parents=True)
  path = segment / 'rlog.zst'
  path.write_bytes(b'abcdefghijklm')
  return next(recordings(tmp_path / 'logs', 'device1', ArchivePolicy()))


@pytest.mark.parametrize('started,connected,wifi,metered,fresh,network,onroad,expected', [
  (False, True, True, False, True, 0, False, True),
  (True, True, True, False, True, 0, False, False),
  (True, True, True, False, True, 0, True, True),
  (False, True, False, False, True, 0, False, False),
  (False, True, False, False, True, 1, False, True),
  (False, True, True, True, True, 0, False, False),
  (False, True, False, True, True, 2, False, True),
  (False, False, True, False, True, 2, True, False),
  (False, True, True, False, False, 0, False, False),
  (False, True, True, False, True, 99, False, False),
])
def test_network_and_driving_policy(started, connected, wifi, metered, fresh, network, onroad, expected):
  policy = ArchivePolicy(enabled=True, onroad=onroad, network=network)
  assert policy.permits(started, connected, wifi, metered, fresh) is expected
  assert not ArchivePolicy().permits(started, connected, wifi, metered, fresh)


def test_discovery_excludes_locks_symlinks_and_unselected_cabin(recording):
  directory = recording.path.parent
  (directory / 'dcamera.hevc').write_bytes(b'private')
  (directory / 'fcamera.hevc').symlink_to(recording.path)
  root = directory.parent
  assert [r.path.name for r in recordings(root, 'device1', ArchivePolicy())] == ['rlog.zst']
  assert len(list(recordings(root, 'device1', ArchivePolicy(cabin=True)))) == 2
  (directory / 'rlog.zst.lock').touch()
  assert list(recordings(root, 'device1', ArchivePolicy(cabin=True))) == []


def test_journal_survives_restart_and_separates_destinations(recording, tmp_path):
  path = tmp_path / 'state' / 'queue.sqlite'
  journal = Journal(path)
  journal.discover('dropbox:a', iter([recording]))
  journal.checkpoint('dropbox:a', recording.key, Checkpoint('session', 4, 123))
  journal.close()
  journal = Journal(path)
  assert journal.next('dropbox:a', {'rlog.zst'}) == (recording, Checkpoint('session', 4, 123))
  journal.complete('dropbox:a', recording.key, dropbox.Receipt('rev', 'digest'))
  journal.discover('dropbox:b', iter([recording]))
  assert journal.next('dropbox:a', {'rlog.zst'}) is None
  assert journal.next('dropbox:b', {'rlog.zst'})[0] == recording
  recording.path.unlink()
  assert journal.next('dropbox:b', {'rlog.zst'}) is None
  assert journal.counts('dropbox:b') == {'missing': 1}
  journal.close()


def test_modified_file_requires_new_upload(recording, tmp_path):
  journal = Journal(tmp_path / 'queue.sqlite')
  journal.discover('a', iter([recording]))
  journal.complete('a', recording.key, dropbox.Receipt('old', 'digest'))
  recording.path.write_bytes(b'new recording')
  changed = next(recordings(recording.path.parent.parent, 'device1', ArchivePolicy()))
  journal.discover('a', iter([changed]))
  assert journal.next('a', {'rlog.zst'}) == (changed, Checkpoint())
  journal.close()


@pytest.mark.parametrize('name', ['qlog.zst', 'rlog.zst', 'qlog'])
def test_readable_names_use_route_and_segment_recording_times(tmp_path, name):
  route_time = 1793188800_000000000  # 2026-10-28 12:00:00 UTC
  init = log.Event.new_message(logMonoTime=1000)
  init.init('initData').wallTimeNanos = route_time
  start = log.Event.new_message(logMonoTime=60_000001000)
  start.init('sentinel').type = 'startOfSegment'
  directory = tmp_path / '00000001--abcdef--12'
  directory.mkdir()
  data = init.to_bytes() + start.to_bytes()
  (directory / name).write_bytes(zstd.compress(data) if name.endswith('.zst') else data)
  path = directory / 'ecamera.hevc'
  expected = ('/device/2026-10-28_12-00-00_UTC--drive-00000001--abcdef/' +
              '2026-10-28_12-01-00_UTC--segment-0012/2026-10-28_12-01-00_UTC--road-wide.hevc')
  assert destination(path, 'device', 0) == expected


def test_missing_or_corrupt_time_is_explicit_and_does_not_guess_recording_start(recording):
  target = recording.remote_path
  assert '/undated-drive--00000001--abcdef/segment-0000--time-unavailable/' in target
  assert target.endswith('--saved-at--full-log.zst')


def test_destination_stays_pinned_when_discovery_metadata_changes(recording, tmp_path):
  journal = Journal(tmp_path / 'queue.sqlite')
  journal.discover('a', iter([recording]))
  journal.checkpoint('a', recording.key, Checkpoint('session', 4, 123))
  journal.discover('a', iter([replace(recording, destination='/newly-available-metadata/full-log.zst')]))
  selected, checkpoint = journal.next('a', {'rlog.zst'})
  assert selected.remote_path == recording.remote_path
  assert checkpoint == Checkpoint('session', 4, 123)
  journal.complete('a', recording.key, dropbox.Receipt('rev', 'digest'))
  journal.discover('a', iter([replace(recording, destination='/another-name/full-log.zst')]))
  assert journal.counts('a') == {'done': 1}
  journal.close()


def test_older_journal_preserves_completed_files_and_pending_sessions(recording, tmp_path):
  path = tmp_path / 'old.sqlite'
  db = sqlite3.connect(path)
  db.execute("""CREATE TABLE uploads (provider TEXT,key TEXT,path TEXT,stamp TEXT,size INTEGER,
    status TEXT DEFAULT 'pending',session TEXT DEFAULT '',offset INTEGER DEFAULT 0,created REAL DEFAULT 0,
    revision TEXT DEFAULT '',digest TEXT DEFAULT '',PRIMARY KEY(provider,key))""")
  for provider, status in [('pending-account', 'pending'), ('done-account', 'done')]:
    db.execute("INSERT INTO uploads(provider,key,path,stamp,size,status,session,offset,created) VALUES(?,?,?,?,?,?,?,?,?)",
               (provider, recording.key, str(recording.path), recording.stamp, recording.size, status, 'session', 4, 123))
  db.commit()
  db.close()
  journal = Journal(path)
  for provider in ('pending-account', 'done-account'):
    journal.discover(provider, iter([recording]))
  selected, checkpoint = journal.next('pending-account', {'rlog.zst'})
  assert selected.remote_path == recording.key
  assert checkpoint == Checkpoint('session', 4, 123)
  assert journal.next('done-account', {'rlog.zst'}) is None
  assert journal.counts('done-account') == {'done': 1}
  journal.close()


def test_dropbox_block_hash():
  data = b'a' * (4 * 1024 * 1024) + b'b'
  expected = hashlib.sha256(hashlib.sha256(data[:-1]).digest() + hashlib.sha256(b'b').digest()).hexdigest()
  assert content_hash(io.BytesIO(data)) == expected
  assert content_hash(io.BytesIO()) == hashlib.sha256(b'').hexdigest()


def response(status, data=None):
  result = requests.Response()
  result.status_code = status
  result._content = json.dumps(data).encode() if data is not None else b''
  return result


@pytest.fixture
def server(monkeypatch):
  """Only the HTTP boundary is replaced; requests, files, credentials and queue are real."""
  state = {'bytes': b'', 'metadata': None, 'refreshes': 0, 'offsets': [], 'lose_append': False, 'lose_finish': False,
           'bad_hash': False, 'unauthorized': False, 'append_body': b'null'}

  def post(self, url, **kwargs):
    if url.endswith('/oauth2/token'):
      state['refreshes'] += 1
      return response(200, {'access_token': 'access', 'expires_in': 3600, 'refresh_token': 'refresh', 'account_id': 'account'})
    assert kwargs['headers']['Authorization'] == 'Bearer access'
    if url.endswith('/auth/token/revoke'):
      return response(503, {})
    if state['unauthorized']:
      return response(401, {})
    if url.endswith('/files/get_metadata'):
      return response(200, state['metadata']) if state['metadata'] else response(409, {'error': {'.tag': 'path', 'path': {'.tag': 'not_found'}}})
    args = json.loads(kwargs['headers']['Dropbox-API-Arg'])
    if url.endswith('/start'):
      state['bytes'] = b''
      return response(200, {'session_id': 'session'})
    offset = args['cursor']['offset']
    if url.endswith('/append_v2'):
      state['offsets'].append(offset)
      if offset != len(state['bytes']):
        return response(409, {'error': {'.tag': 'incorrect_offset', 'correct_offset': len(state['bytes'])}})
      state['bytes'] += kwargs['data']
      if state['lose_append']:
        state['lose_append'] = False
        raise requests.Timeout('simulated connection loss')
      result = response(200)
      result._content = state['append_body']
      return result
    if url.endswith('/finish'):
      digest = content_hash(io.BytesIO(state['bytes']))
      state['metadata'] = {'size': len(state['bytes']), 'rev': 'revision',
                           'content_hash': 'bad' if state['bad_hash'] else digest,
                           'path_lower': args['commit']['path'].lower()}
      if state['lose_finish']:
        state['lose_finish'] = False
        raise requests.Timeout('simulated commit acknowledgement loss')
      return response(200, state['metadata'])
    raise AssertionError(url)

  monkeypatch.setattr(requests.Session, 'post', post)
  monkeypatch.setattr(dropbox, 'CHUNK_SIZE', 4)
  return state


@pytest.mark.parametrize('body', [b'', b'null'])
def test_upload_accepts_successful_append_reply(server, recording, body):
  server['append_body'] = body
  provider = DropboxProvider(Credentials('app', 'refresh', 'account'))
  receipt = provider.upload(recording, Checkpoint(), lambda c: None, lambda: True)
  assert receipt.content_hash == content_hash(io.BytesIO(recording.path.read_bytes()))
  assert server['metadata']['size'] == recording.size


def test_pkce_link_private_storage_and_refresh(server, tmp_path):
  store = CredentialStore(tmp_path / 'private')
  url = begin_link(store, 'publicappkey')
  query = parse_qs(urlparse(url).query)
  pending = json.loads((store.root / 'pending.json').read_text())
  expected = base64.urlsafe_b64encode(hashlib.sha256(pending['verifier'].encode()).digest()).rstrip(b'=').decode()
  assert query['code_challenge'] == [expected]
  assert query['token_access_type'] == ['offline']
  assert 'verifier' not in url and 'client_secret' not in url
  credentials = finish_link(store, 'one-time-code')
  assert store.load() == credentials
  assert stat.S_IMODE((store.root / 'credentials.json').stat().st_mode) == 0o600
  assert stat.S_IMODE(store.root.stat().st_mode) == 0o700
  assert not (store.root / 'pending.json').exists()
  assert 'access_token' not in (store.root / 'credentials.json').read_text()


@pytest.mark.parametrize('lost', ['lose_append', 'lose_finish'])
def test_resume_after_ambiguous_network_failure(server, recording, tmp_path, lost):
  provider = DropboxProvider(Credentials('app', 'refresh', 'account'))
  path = tmp_path / 'journal.sqlite'
  journal = Journal(path)
  journal.discover(provider.identity, iter([recording]))
  server[lost] = True
  def save(c):
    journal.checkpoint(provider.identity, recording.key, c)
  with pytest.raises(requests.Timeout):
    provider.upload(recording, Checkpoint(), save, lambda: True)
  assert journal.counts(provider.identity) == {'pending': 1}
  journal.close()
  journal = Journal(path)
  item, checkpoint = journal.next(provider.identity, {'rlog.zst'})
  receipt = provider.upload(item, checkpoint, lambda c: journal.checkpoint(provider.identity, item.key, c), lambda: True)
  journal.complete(provider.identity, item.key, receipt)
  assert server['bytes'] == recording.path.read_bytes()
  assert journal.counts(provider.identity) == {'done': 1}
  assert server['refreshes'] == 1
  journal.close()


@pytest.mark.parametrize('failure', ['pause', 'unauthorized', 'bad_hash'])
def test_never_completes_unconfirmed_upload(server, recording, failure):
  provider = DropboxProvider(Credentials('app', 'refresh', 'account'))
  server[failure] = True
  error = Paused if failure == 'pause' else DropboxError if failure == 'unauthorized' else ArchiveError
  with pytest.raises(error):
    provider.upload(recording, Checkpoint(), lambda c: None, lambda: failure != 'pause')


def test_expired_link_and_disconnect_cleanup(server, tmp_path):
  store = CredentialStore(tmp_path)
  with pytest.raises(ArchiveError, match='expired'):
    finish_link(store, 'code')
  begin_link(store, 'appkey')
  pending = json.loads((store.root / 'pending.json').read_text())
  pending['created'] = 0
  store.write('pending.json', pending)
  with pytest.raises(ArchiveError, match='expired'):
    finish_link(store, 'code')
  begin_link(store, 'appkey')
  finish_link(store, 'code')
  # A failed revoke must still remove local credentials.
  with pytest.raises(ArchiveError, match="Disconnected locally"):
    disconnect(store)
  assert store.load() is None


def test_recording_change_cannot_commit(server, recording):
  provider = DropboxProvider(Credentials('app', 'refresh', 'account'))

  def changed(checkpoint):
    if checkpoint.offset:
      recording.path.write_bytes(b'changed while uploading')

  with pytest.raises(ArchiveError, match='changed'):
    provider.upload(recording, Checkpoint(), changed, lambda: True)
  assert server['metadata'] is None


@pytest.mark.parametrize('error', [401, 403, 429, 503])
def test_http_failures_never_become_receipts(monkeypatch, recording, error):
  def post(self, url, **kwargs):
    if url.endswith('/oauth2/token'):
      return response(200, {'access_token': 'access', 'expires_in': 3600})
    result = response(error, {'error': {'.tag': 'rate_limited'}})
    result.headers['Retry-After'] = '60'
    return result

  monkeypatch.setattr(requests.Session, 'post', post)
  provider = DropboxProvider(Credentials('app', 'refresh', 'account'))
  with pytest.raises(DropboxError) as raised:
    provider.upload(recording, Checkpoint(), lambda c: None, lambda: True)
  assert raised.value.status == error
  assert raised.value.retry_after == 60


@pytest.mark.parametrize('enabled,started,onroad,expected', [
  (False, False, False, False), (False, True, True, False),
  (True, False, False, True), (True, True, False, False),
  (True, False, True, True), (True, True, True, True),
])
def test_process_stays_stopped_when_disabled_or_parked_only(tmp_path, enabled, started, onroad, expected):
  from openpilot.common.params import Params
  from openpilot.system.manager.process_config import archive_ready
  from opendbc.car.structs import car

  params = Params(str(tmp_path))
  params.put_bool('ArchiveEnabled', enabled, block=True)
  params.put_bool('ArchiveOnroad', onroad, block=True)
  assert archive_ready(started, params, car.CarParams.new_message()) is expected


@pytest.mark.parametrize('selected', [None, False, True])
def test_worker_policy_reads_recording_defaults_and_saved_choices(tmp_path, selected):
  from openpilot.common.params import Params
  from openpilot.sunnypilot.archive.archived import policy

  params = Params(str(tmp_path))
  params.put_bool('ArchiveEnabled', True, block=True)
  if selected is not None:
    for key in ('ArchiveLogs', 'ArchiveRoad'):
      params.put_bool(key, selected, block=True)
  current = policy(params)
  assert current.enabled
  assert current.network == 0
  assert current.logs is (True if selected is None else selected)
  assert current.road is (True if selected is None else selected)
  assert not current.onroad and not current.preview and not current.cabin

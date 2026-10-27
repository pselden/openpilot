import hmac
import json
import os
import time
from datetime import UTC, datetime
from collections.abc import Callable

import requests

from openpilot.sunnypilot.archive.auth import Credentials, token_request
from openpilot.sunnypilot.archive.core import ArchiveError, Checkpoint, Paused, Receipt, Recording, content_hash, json_object

CHUNK_SIZE = 8 * 1024 * 1024
SESSION_MAX_AGE = 6 * 86400  # restart before Dropbox's seven-day expiry


class DropboxError(ArchiveError):
  def __init__(self, status: int, error: object = None, retry_after: int = 0):
    super().__init__(f"Dropbox request failed ({status})")
    self.status, self.error, self.retry_after = status, error, retry_after


class DropboxProvider:
  def __init__(self, credentials: Credentials, session: requests.Session | None = None):
    self.credentials = credentials
    self.identity = f'dropbox:{credentials.app_key}:{credentials.account_id}'
    self.http = session or requests.Session()
    self.access_token = ''
    self.expires = 0.0

  def token(self) -> str:
    if time.monotonic() >= self.expires:
      result = token_request(self.http, {'grant_type': 'refresh_token', 'client_id': self.credentials.app_key,
                                        'refresh_token': self.credentials.refresh_token})
      token, expires = result.get('access_token'), result.get('expires_in')
      if not isinstance(token, str) or not token or not isinstance(expires, (int, float)) or expires <= 0:
        raise ArchiveError('Invalid Dropbox refresh response')
      self.access_token, self.expires = token, time.monotonic() + max(0, expires - 60)
    return self.access_token

  def request(self, endpoint: str, args: dict[str, object], body: bytes | None = None) -> dict[str, object]:
    for attempt in range(2):
      headers = {'Authorization': f'Bearer {self.token()}'}
      if body is None:
        response = self.http.post('https://api.dropboxapi.com/2/' + endpoint, json=args, headers=headers, timeout=30)
      else:
        headers |= {'Content-Type': 'application/octet-stream', 'Dropbox-API-Arg': json.dumps(args)}
        response = self.http.post('https://content.dropboxapi.com/2/' + endpoint, data=body, headers=headers, timeout=30)
      if response.status_code == 401 and attempt == 0:
        self.expires = 0.0
        continue
      if response.status_code != 200:
        try:
          error = response.json().get('error')
        except (ValueError, AttributeError):
          error = None
        try:
          retry_after = min(600, max(0, int(response.headers.get('Retry-After', '0'))))
        except ValueError:
          retry_after = 60
        raise DropboxError(response.status_code, error, retry_after)
      if not response.content:
        return {}
      return json_object(response.json())
    raise ArchiveError('Dropbox authorization failed; link again')

  def receipt(self, metadata: dict[str, object], recording: Recording, digest: str) -> Receipt:
    remote_hash = metadata.get('content_hash')
    revision = metadata.get('rev')
    if (metadata.get('size') != recording.size or not isinstance(remote_hash, str) or
        not hmac.compare_digest(remote_hash, digest) or not isinstance(revision, str) or
        metadata.get('path_lower') != recording.key.lower()):
      raise ArchiveError('Dropbox did not confirm the complete recording')
    return Receipt(revision, digest)

  def existing(self, recording: Recording, digest: str) -> Receipt | None:
    try:
      metadata = self.request('files/get_metadata', {'path': recording.key})
    except DropboxError as error:
      if error.status == 409 and isinstance(error.error, dict) and error.error.get('.tag') == 'path':
        path = error.error.get('path')
        if isinstance(path, dict) and path.get('.tag') == 'not_found':
          return None
      raise
    try:
      return self.receipt(metadata, recording, digest)
    except ArchiveError:
      return None

  def upload(self, recording: Recording, checkpoint: Checkpoint,
             save: Callable[[Checkpoint], None], allowed: Callable[[], bool]) -> Receipt:
    def check() -> None:
      if not allowed():
        raise Paused('Backup paused')
      if not recording.unchanged() or any(p.name.endswith('.lock') for p in recording.path.parent.iterdir()):
        raise ArchiveError('Recording changed or is still being written')

    check()
    fd = os.open(recording.path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
      if Recording.fingerprint(os.fstat(stream.fileno())) != recording.stamp:
        raise ArchiveError('Recording changed before backup')
      digest = content_hash(stream)
      check()
      # Resolves an ambiguous finish (server committed before the device lost power).
      if receipt := self.existing(recording, digest):
        return receipt
      if not checkpoint.session or not 0 <= datetime.now(UTC).timestamp() - checkpoint.created < SESSION_MAX_AGE:
        result = self.request('files/upload_session/start', {'close': False}, b'')
        session = result.get('session_id')
        if not isinstance(session, str) or not session:
          raise ArchiveError('Invalid Dropbox upload session')
        checkpoint = Checkpoint(session, 0, datetime.now(UTC).timestamp())
        save(checkpoint)
      if not 0 <= checkpoint.offset <= recording.size:
        raise ArchiveError("Invalid upload position")
      corrections = 0
      while checkpoint.offset < recording.size:
        check()
        if not 0 <= checkpoint.offset <= recording.size:
          raise ArchiveError('Invalid upload position')
        stream.seek(checkpoint.offset)
        chunk = stream.read(min(CHUNK_SIZE, recording.size - checkpoint.offset))
        if not chunk:
          raise ArchiveError('Recording ended before backup completed')
        try:
          self.request('files/upload_session/append_v2', {
            'cursor': {'session_id': checkpoint.session, 'offset': checkpoint.offset}, 'close': False}, chunk)
          offset = checkpoint.offset + len(chunk)
        except DropboxError as error:
          detail = error.error
          position = detail.get('incorrect_offset', detail) if isinstance(detail, dict) else None
          if (error.status == 409 and isinstance(detail, dict) and detail.get('.tag') == 'incorrect_offset' and
              isinstance(position, dict) and isinstance(position.get('correct_offset'), int) and corrections < 3):
            offset = position['correct_offset']
            if not 0 <= offset <= recording.size:
              raise ArchiveError('Invalid Dropbox upload position') from None
            corrections += 1
          else:
            if error.status == 409 and isinstance(detail, dict) and detail.get('.tag') in ('not_found', 'closed'):
              save(Checkpoint())
            raise
        checkpoint = Checkpoint(checkpoint.session, offset, checkpoint.created)
        save(checkpoint)
      check()
      try:
        result = self.request('files/upload_session/finish', {
          'cursor': {'session_id': checkpoint.session, 'offset': checkpoint.offset},
          'commit': {'path': recording.key, 'mode': 'overwrite', 'autorename': False, 'mute': True}}, b'')
      except DropboxError as error:
        if error.status == 409:
          save(Checkpoint())
        raise
      return self.receipt(result, recording, digest)

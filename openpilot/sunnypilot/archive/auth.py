"""Dropbox PKCE and private credential storage; no shared client secret."""
import argparse
import base64
import hashlib
from getpass import getpass
import json
import os
import secrets
import tempfile
from datetime import UTC, datetime
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlencode

import requests

from openpilot.common.hardware import PC
from openpilot.common.hardware.hw import Paths
from openpilot.sunnypilot.archive.core import ArchiveError, json_object, text_field

TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"


def state_root() -> Path:
  return Path(Paths.comma_home()) / 'archive' if PC else Path('/data/odypilot-archive')


@dataclass(frozen=True)
class Credentials:
  app_key: str
  refresh_token: str
  account_id: str


class CredentialStore:
  def __init__(self, root: Path):
    self.root = root
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.chmod(0o700)

  def write(self, name: str, data: dict[str, object]) -> None:
    fd, temporary = tempfile.mkstemp(dir=self.root)
    try:
      with os.fdopen(fd, 'w') as stream:
        json.dump(data, stream)
        stream.flush()
        os.fsync(stream.fileno())
      os.replace(temporary, self.root / name)
    finally:
      if os.path.exists(temporary):
        os.unlink(temporary)

  def load(self) -> Credentials | None:
    try:
      data = json_object(json.loads((self.root / 'credentials.json').read_text()))
      return Credentials(text_field(data, 'app_key'), text_field(data, 'refresh_token'), text_field(data, 'account_id'))
    except FileNotFoundError:
      return None
    except (ValueError, KeyError, TypeError):
      raise ArchiveError("Dropbox credentials are invalid; link again") from None

  def clear(self) -> None:
    for name in ('credentials.json', 'pending.json'):
      (self.root / name).unlink(missing_ok=True)


def begin_link(store: CredentialStore, app_key: str) -> str:
  app_key = app_key.strip()
  if not app_key.isascii() or not app_key.isalnum() or len(app_key) > 128:
    raise ArchiveError("Enter a valid Dropbox app key")
  verifier = secrets.token_urlsafe(48)
  challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
  store.write('pending.json', {'app_key': app_key, 'verifier': verifier, 'created': datetime.now(UTC).timestamp()})
  return 'https://www.dropbox.com/oauth2/authorize?' + urlencode({
    'client_id': app_key, 'response_type': 'code', 'token_access_type': 'offline',
    'code_challenge_method': 'S256', 'code_challenge': challenge,
    'scope': 'files.content.write files.metadata.read',
  })


def token_request(session: requests.Session, data: dict[str, str]) -> dict[str, object]:
  response = session.post(TOKEN_URL, data=data, timeout=30)
  if response.status_code != 200:
    raise ArchiveError("Dropbox authorization failed; link again")
  return json_object(response.json())


def finish_link(store: CredentialStore, code: str, session: requests.Session | None = None) -> Credentials:
  try:
    pending = json_object(json.loads((store.root / 'pending.json').read_text()))
    created = pending.get('created')
    if not isinstance(created, (int, float)) or not 0 <= datetime.now(UTC).timestamp() - created <= 600:
      raise ValueError
    data = {'grant_type': 'authorization_code', 'code': code.strip(),
            'code_verifier': text_field(pending, 'verifier'), 'client_id': text_field(pending, 'app_key')}
  except (OSError, ValueError, KeyError, TypeError):
    raise ArchiveError("Dropbox link expired; start again") from None
  result = token_request(session or requests.Session(), data)
  credentials = Credentials(text_field(pending, 'app_key'), text_field(result, 'refresh_token'), text_field(result, 'account_id'))
  store.write('credentials.json', asdict(credentials))
  (store.root / 'pending.json').unlink(missing_ok=True)
  return credentials


def disconnect(store: CredentialStore, session: requests.Session | None = None) -> None:
  """Always remove local authorization, even if remote revocation cannot be reached."""
  http = session or requests.Session()
  try:
    credentials = store.load()
    if credentials is not None:
      result = token_request(http, {'grant_type': 'refresh_token', 'client_id': credentials.app_key,
                                   'refresh_token': credentials.refresh_token})
      token = result.get('access_token')
      if not isinstance(token, str) or not token:
        raise ArchiveError('Invalid Dropbox refresh response')
      response = http.post('https://api.dropboxapi.com/2/auth/token/revoke',
                           headers={'Authorization': f'Bearer {token}'}, timeout=30)
      if response.status_code != 200:
        raise ArchiveError('Disconnected locally; revoke app access in Dropbox connected apps')
  finally:
    store.clear()


def main() -> None:
  parser = argparse.ArgumentParser(description='Link this device to a Dropbox App Folder app; never prints tokens.')
  parser.add_argument('action', choices=['link', 'disconnect'])
  parser.add_argument('--app-key', default='')
  args = parser.parse_args()
  store = CredentialStore(state_root())
  if args.action == 'disconnect':
    disconnect(store)
    print('Dropbox disconnected.')
  else:
    print(begin_link(store, args.app_key))
    finish_link(store, getpass('Approve in your browser, then enter the one-time code: '))
    print('Dropbox connected. Enable ArchiveEnabled to start backing up.')


if __name__ == '__main__':
  main()

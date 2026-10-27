"""Device-local OAuth; ordinary archive preferences are also exposed in Sunnylink."""
import threading

import requests

from openpilot.selfdrive.ui.mici.widgets.button import BigButton, BigMultiParamToggle
from openpilot.selfdrive.ui.mici.widgets.dialog import BigDialog, BigInputDialog, SettingDescriptionDialog
from openpilot.selfdrive.ui.mici.widgets.qr import QR
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings_groups import DefaultParamControl, GroupLayout
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.sunnypilot.archive.auth import CredentialStore, begin_link, disconnect, finish_link, state_root
from openpilot.sunnypilot.archive.core import ArchiveError
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.widgets.scroller import NavScroller


class DropboxLinkPage(NavScroller):
  def __init__(self, store: CredentialStore, url: str):
    super().__init__()
    self._store = store
    self._busy = False
    self._message = 'Approve first'
    self._code = BigButton('enter Dropbox code', '')
    self._code.set_click_callback(self._enter_code)
    help_button = BigButton('setup steps', 'Scan, approve, enter code')
    help_button.set_click_callback(lambda: gui_app.push_widget(SettingDescriptionDialog('Dropbox setup',
      'Scan the QR with your phone.\nApprove access in your Dropbox browser page.\n' +
      'Enter the authorization code shown by Dropbox on this device.\nNo app secret or token needs to be pasted.')))
    self._scroller.add_widgets([QR(url, width=220), self._code, help_button])

  def _enter_code(self):
    if not ui_state.started and not self._busy:
      gui_app.push_widget(BigInputDialog('Dropbox authorization code', '', minimum_length=1, confirm_callback=self._finish))

  def _finish(self, code: str):
    if ui_state.started or self._busy:
      return
    self._busy, self._message = True, 'Connecting…'

    def run():
      try:
        finish_link(self._store, code)
        self._message = 'Dropbox connected'
      except (ArchiveError, OSError, ValueError, requests.RequestException):
        self._message = 'Link failed. Go back and start Connect Dropbox again.'
      finally:
        self._busy = False
    threading.Thread(target=run, daemon=True).start()

  def _update_state(self):
    super()._update_state()
    self._code.set_enabled(not ui_state.started and not self._busy)
    self._code.set_value(self._message)


class DropboxLayout(GroupLayout):
  def __init__(self):
    self._app_key = ''
    self._connected = False
    self._busy = False
    self._message = ''
    self._status_text = 'Not connected'
    self._key = BigButton('Dropbox app key', 'One-time setup: App Folder app, no app secret')
    self._key.set_click_callback(self._edit_key)
    self._connect = BigButton('connect Dropbox', 'Approve access using your phone')
    self._connect.set_click_callback(self._link)
    self._disconnect = BigButton('disconnect Dropbox', 'Remove authorization from this device')
    self._disconnect.set_click_callback(self._unlink)
    self._status = BigButton('backup status', '')
    self._status.set_click_callback(lambda: gui_app.push_widget(SettingDescriptionDialog('Dropbox status', self._status_text)))
    super().__init__([
      self._status, self._key, self._connect, self._disconnect,
      DefaultParamControl('Dropbox backup', 'ArchiveEnabled'),
      BigMultiParamToggle('upload network', 'ArchiveNetwork', ['Wi-Fi only', 'unmetered', 'any network']),
      DefaultParamControl('upload while driving', 'ArchiveOnroad'),
      DefaultParamControl('full + quick logs', 'ArchiveLogs'),
      DefaultParamControl('road camera videos', 'ArchiveRoad'),
      DefaultParamControl('preview video', 'ArchivePreview'),
      DefaultParamControl('cabin video', 'ArchiveCabin'),
    ])

  def show_event(self):
    super().show_event()
    self._message = ''
    try:
      credentials = CredentialStore(state_root()).load()
      self._connected = credentials is not None
      if credentials is not None:
        self._app_key = credentials.app_key
    except (ArchiveError, OSError):
      self._connected = False

  def _edit_key(self):
    if not ui_state.started:
      gui_app.push_widget(BigInputDialog('Dropbox app key (not app secret)', self._app_key, minimum_length=1,
                                        confirm_callback=self._set_key))

  def _set_key(self, value: str):
    if not ui_state.started:
      self._app_key = value.strip()

  def _link(self):
    if ui_state.started:
      return
    try:
      store = CredentialStore(state_root())
      url = begin_link(store, self._app_key)
      gui_app.push_widget(DropboxLinkPage(store, url))
    except (ArchiveError, OSError):
      gui_app.push_widget(BigDialog('Dropbox setup', 'Enter the public app key from your Dropbox App Folder app first.'))

  def _unlink(self):
    if ui_state.started or self._busy:
      return
    self._busy = True
    ui_state.params.put_bool('ArchiveEnabled', False)

    def run():
      try:
        disconnect(CredentialStore(state_root()))
        self._message = 'Dropbox disconnected'
      except (ArchiveError, OSError, ValueError, requests.RequestException):
        self._message = 'Disconnected locally; revoke app access on dropbox.com too'
      finally:
        self._busy = False
    threading.Thread(target=run, daemon=True).start()

  def _update_state(self):
    super()._update_state()
    for button in (self._key, self._connect, self._disconnect):
      button.set_enabled(not ui_state.started and not self._busy)
    self._key.set_value(self._app_key or 'Enter public app key')
    status = ui_state.params.get('ArchiveStatus') if ui_state.params.get_bool('ArchiveEnabled') else ''
    self._status_text = self._message or status or ('Connected — backup disabled' if self._connected else 'Not connected')
    self._status.set_value(self._status_text)

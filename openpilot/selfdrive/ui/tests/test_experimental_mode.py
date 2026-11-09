"""Experimental Mode settings share confirmation and preserve the onroad shortcut."""
import pytest

from openpilot.common.params import Params
from openpilot.selfdrive.ui.mici.layouts.settings import toggles


def test_first_enable_waits_for_confirmation(tmp_path, monkeypatch):
  params = Params(str(tmp_path))
  monkeypatch.setattr(toggles.ui_state, "params", params)
  pending = []
  shown = []
  # UI construction and navigation are side effects; retain the real confirmation action and Params.
  monkeypatch.setattr(toggles, "ExperimentalModeConfirmPage", lambda on_confirm: on_confirm)
  monkeypatch.setattr(toggles.gui_app, "push_widget", pending.append)

  toggles.request_experimental_mode(True, shown.append)
  assert shown == [False]
  assert not params.get_bool("ExperimentalMode")
  assert not params.get_bool("ExperimentalModeConfirmed")
  assert len(pending) == 1

  # Dismissing without accepting leaves both settings untouched; accepting enables the shortcut too.
  pending[0]()
  assert shown == [False, True]
  assert params.get_bool("ExperimentalMode")
  assert params.get_bool("ExperimentalModeConfirmed")


@pytest.mark.parametrize("confirmed, enabled", [(True, True), (True, False), (False, False)])
def test_confirmed_enable_and_any_disable_are_immediate(tmp_path, monkeypatch, confirmed, enabled):
  params = Params(str(tmp_path))
  params.put_bool("ExperimentalModeConfirmed", confirmed, block=True)
  params.put_bool("ExperimentalMode", not enabled, block=True)
  monkeypatch.setattr(toggles.ui_state, "params", params)
  pending = []
  shown = []
  monkeypatch.setattr(toggles.gui_app, "push_widget", pending.append)

  toggles.request_experimental_mode(enabled, shown.append)
  assert not pending
  assert shown == [enabled]
  assert params.get_bool("ExperimentalMode") == enabled
  assert params.get_bool("ExperimentalModeConfirmed") == confirmed

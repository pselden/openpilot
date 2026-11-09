"""OdyPilot onroad status pills: what each row says for a given state (pure logic, no window)."""
import pytest

from opendbc.car import structs
from openpilot.cereal import messaging
from openpilot.common.params import Params
from openpilot.selfdrive.ui.sunnypilot.mici.onroad.status_pills import pill_rows, PillInputs, StatusPills, gui_app, ui_state


def texts(p: PillInputs):
  return [[t for t, _ in row] for row in pill_rows(p)]


@pytest.mark.parametrize("p, want", [
  (PillInputs(op_long=False), [["STOCK ACC"]]),
  (PillInputs(op_long=True), [["OP LONG"]]),
  (PillInputs(op_long=True, experimental=True), [["OP LONG"], ["EXP"]]),
  (PillInputs(op_long=True, lead_dist=42.0, v_ego=20.0), [["2.1s", "OP LONG"]]),
  (PillInputs(op_long=True, lead_dist=5.0, v_ego=0.0), [["16ft", "OP LONG"]]),
  (PillInputs(op_long=True, lead_dist=5.0, v_ego=0.0, metric=True), [["5m", "OP LONG"]]),
  (PillInputs(op_long=True, lead_dist=42.0, v_ego=20.0, load_preset=1), [["FAMILY", "2.1s", "OP LONG"]]),
  (PillInputs(op_long=True, load_preset=2), [["LUGGAGE", "OP LONG"]]),
  (PillInputs(op_long=False, experimental=True), [["STOCK ACC"]]),
  # factory mode: op long stays set in CarParams, but the car is stock, so nothing about op long is shown
  (PillInputs(op_long=True, experimental=True, lead_dist=42.0, v_ego=20.0,
              load_preset=1, factory=True), [["FACTORY"]]),
])
def test_pill_rows(p, want):
  assert texts(p) == want


def test_home_title():
  from openpilot.selfdrive.ui.sunnypilot.mici.layouts.home import home_title
  assert home_title(False) == "OdyPilot"
  assert home_title(True) == "Factory"


def test_current_messages_show_experimental_mode_without_legacy_controller(tmp_path, monkeypatch):
  params = Params(str(tmp_path))
  sm = messaging.SubMaster(['selfdriveState', 'longitudinalPlanSP', 'radarState', 'carState'])
  state = messaging.new_message('selfdriveState')
  state.selfdriveState.experimentalMode = True
  plan = messaging.new_message('longitudinalPlanSP')
  # Historical fields are reserved in the schema but cannot select the current driving mode.
  plan.longitudinalPlanSP.deprecated.dec.enabled = True
  plan.longitudinalPlanSP.deprecated.dec.active = True
  sm.update_msgs(1.0, [state.as_reader(), plan.as_reader()])
  for name, value in {'params': params, 'sm': sm, 'CP': structs.CarParams(openpilotLongitudinalControl=True),
                      'started_frame': 0, 'is_metric': False}.items():
    monkeypatch.setattr(ui_state, name, value)
  monkeypatch.setattr(gui_app, 'font', lambda _: None)

  rows = StatusPills().current_rows()
  assert [[text for text, _ in row] for row in rows] == [['OP LONG'], ['EXP']]

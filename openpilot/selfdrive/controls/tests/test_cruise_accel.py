import numpy as np
import pytest

from opendbc.car.interfaces import ACCEL_MAX
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.controls.lib.longitudinal_planner import J_CRUISE_BP, J_CRUISE_VALS, get_cruise_accel

def jerk_step(v_ego):
  return float(np.interp(v_ego, J_CRUISE_BP, J_CRUISE_VALS)) * DT_MDL


def cruise_accel(a_cruise_prev, a_target_prev, v_cruise=20.0, v_ego=25.0, experimental=True):
  return get_cruise_accel(experimental, v_cruise, v_ego, a_cruise_prev, DT_MDL, a_target_prev)


@pytest.mark.parametrize('experimental', [False, True])
def test_lowered_set_speed_starts_from_lower_planner_output(experimental):
  # comma #39127: a_cruise sat at +0.5 while the planner was already braking for a lead (-0.3). Lowering the
  # set speed must continue from -0.3, not spend ~1 s ramping a_cruise down from +0.5 first.
  j = jerk_step(25.0)
  assert abs(cruise_accel(0.5, -0.3, experimental=experimental) - max(-0.5, -0.3 - j)) < 1e-6


def test_rise_rate_still_limited_from_a_cruise():
  # the upper bound is unchanged: speeding up is still jerk-limited from a_cruise itself
  out = cruise_accel(-0.2, -0.4, v_cruise=30.0, v_ego=20.0)
  assert out <= -0.2 + jerk_step(20.0) + 1e-6


def test_higher_planner_output_does_not_relax_the_lower_bound():
  j = jerk_step(25.0)
  assert abs(cruise_accel(0.0, 0.8) - (0.0 - j)) < 1e-6


@pytest.mark.parametrize('experimental', [False, True])
@pytest.mark.parametrize('speed,limit', [(0., 1.6), (10., 1.2), (17.5, 1.0), (25., .8), (40., .6)])
def test_cruise_acceleration_limit(experimental, speed, limit):
  accel = 0.
  for _ in range(int(5. / DT_MDL)):
    accel = cruise_accel(accel, accel, v_cruise=45., v_ego=speed, experimental=experimental)
  assert accel == pytest.approx(ACCEL_MAX if experimental else limit)


def test_disabling_experimental_mode_reduces_acceleration_gradually():
  speed = 25.
  accel = cruise_accel(ACCEL_MAX, ACCEL_MAX, v_cruise=45., v_ego=speed, experimental=False)
  assert accel == pytest.approx(ACCEL_MAX - jerk_step(speed))

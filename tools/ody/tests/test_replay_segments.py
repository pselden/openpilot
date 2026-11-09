import pytest

from openpilot.cereal import messaging
from tools.ody import replay_segments


def messages(*services):
  return [messaging.new_message(service, 0 if service == 'sendcan' else None, valid=True) for service in services]


@pytest.mark.parametrize('proc, services', [
  ('card', ('carParams', 'carState', 'sendcan')),
  ('controlsd', ('carControl',)),
])
def test_complete_valid_output_is_accepted(proc, services):
  assert replay_segments.validate_replay(proc, messages(*services)) == []


@pytest.mark.parametrize('proc, services', [('card', ('carState',)), ('controlsd', ())])
def test_missing_required_output_fails(proc, services):
  assert replay_segments.validate_replay(proc, messages(*services))


@pytest.mark.parametrize('field, value', [('accel', float('nan')), ('torque', float('inf'))])
def test_nonfinite_commands_fail(field, value):
  output = messages('carControl')
  setattr(output[0].carControl.actuators, field, value)
  assert replay_segments.validate_replay('controlsd', output) == ['nonfinite actuator output']


def test_invalid_messages_fail():
  output = messages('carControl')
  output[0].valid = False
  assert replay_segments.validate_replay('controlsd', output) == ['not enough valid output messages']


def test_child_process_crash_returns_failure(tmp_path, monkeypatch):
  from openpilot.tools.lib.logreader import save_log

  path = tmp_path / 'rlog.zst'
  save_log(str(path), [msg.as_reader() for msg in messages('carState', 'carControl')])

  def crash(*args, **kwargs):
    raise RuntimeError('replayed process exited')

  monkeypatch.setattr(replay_segments, 'replay_process_with_name', crash)
  assert replay_segments.main([str(path)]) == 1

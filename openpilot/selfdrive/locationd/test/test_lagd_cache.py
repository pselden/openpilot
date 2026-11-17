import pytest

from opendbc.car import gen_empty_fingerprint
from opendbc.car.honda.interface import CarInterface
from opendbc.car.honda.values import CAR
from openpilot.cereal import messaging
from openpilot.common.params import Params
from openpilot.selfdrive.locationd.lagd import BLOCK_NUM_NEEDED, VERSION, retrieve_initial_lag


@pytest.mark.parametrize('model', [CAR.HONDA_ODYSSEY_5G_MMR, CAR.HONDA_CITY_7G, CAR.HONDA_CRV_6G])
@pytest.mark.parametrize('previous_alpha,current_alpha', [(False, True), (True, False), (False, False), (True, True)])
def test_cached_delay_matches_steering_route(monkeypatch, tmp_path, model, previous_alpha, current_alpha):
  monkeypatch.setenv('PARAMS_ROOT', str(tmp_path))
  params = Params()
  previous, current = [CarInterface.get_params(model, gen_empty_fingerprint(), [], alpha, False, False)
                       for alpha in (previous_alpha, current_alpha)]
  message = messaging.new_message('lateralDelay')
  message.lateralDelay.lateralDelayEstimate = .4
  message.lateralDelay.validBlocks = BLOCK_NUM_NEEDED
  message.lateralDelay.status = 'estimated'
  message.lateralDelay.version = VERSION
  cache = message.to_bytes()
  params.put('LiveDelay', cache, block=True)
  params.put('CarParamsPrevRoute', previous.to_bytes(), block=True)

  saved = retrieve_initial_lag(params, current)
  route_changed = model == CAR.HONDA_ODYSSEY_5G_MMR and previous_alpha != current_alpha
  if route_changed:
    assert saved is None
    assert params.get('LiveDelay') is None
    # A short drive can replace CarParams before a fresh delay estimate is saved.
    params.put('CarParamsPrevRoute', current.to_bytes(), block=True)
    assert retrieve_initial_lag(params, current) is None
  else:
    assert saved == (message.lateralDelay.lateralDelayEstimate, BLOCK_NUM_NEEDED)
    assert params.get('LiveDelay') == cache

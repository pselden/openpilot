import unittest

from tools.scripts.replay_odyssey_hud_rdm import CanSample, audit_samples


class TestOdysseyHudAudit(unittest.TestCase):
  def test_transmitted_off_is_not_camera_success(self):
    samples = [
      CanSample(13.17, 129, 0x18DAB0F1, bytes.fromhex("0328830300000000")),
      CanSample(13.30, 129, 0x33D, bytes.fromhex("4100004813")),
      CanSample(13.37, 2, 0x33DA, bytes.fromhex("0400604835")),
      CanSample(13.37, 2, 0x33DB, bytes.fromhex("0400604801000033")),
    ]
    report = audit_samples(samples)
    self.assertEqual(report.radar_disable_transmitted, [13.17])
    self.assertEqual(report.transmitted["0x33d"].rdm_off_set, 1)
    self.assertEqual(report.camera_result, "fault_observed")
    self.assertEqual(report.camera["0x33da"].first_problem_time, 13.37)
    self.assertEqual(report.camera["0x33db"].rdm_problem_set, 1)

  def test_rejected_or_forwarded_hud_is_not_transmission(self):
    report = audit_samples([
      CanSample(1, 193, 0x33D, bytes.fromhex("4100004804")),
      CanSample(1, 128, 0x33DA, bytes.fromhex("0400604835")),
    ])
    self.assertEqual(report.transmitted, {})
    self.assertEqual(report.rejected, {"0x33d": 1})
    self.assertEqual(report.camera_result, "not_observed")

  def test_observed_clear_camera_is_distinct_from_missing_camera(self):
    cases = [([], "not_observed"),
             ([CanSample(0, 2, 0x33DA, bytes.fromhex("040000482c"))], "fault_not_observed")]
    for samples, expected in cases:
      with self.subTest(expected=expected):
        self.assertEqual(audit_samples(samples).camera_result, expected)

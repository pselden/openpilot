# Odyssey RDM investigation

Findings as of October 15, 2026, from the supplied Honda Odyssey logs and
source research. This branch adds offline diagnostics and documentation;
it does not contain a validated vehicle-control fix.

## Main findings

- Both the original build and `odytest` develop a camera-reported
  `RDM_PROBLEM` shortly after the radar communication-disable request.
- `odytest` successfully transmits `RDM_OFF=1`, but that does not prevent
  the camera fault. Transmission is not proof of ECU acceptance or an
  effective change to RDM or the handsfree timer.
- Radar-side CAN message `0x400`, byte 0, mask `0x08`, changes shortly
  before the camera reports the fault. Its exact meaning is unknown.
- The supplied factory-system baseline has neither this bit nor the RDM
  fault set. It is a passive/dashcam run with factory ACC use, not an
  active lateral-only openpilot run.
- The evidence points toward a software/protocol interaction during radar
  takeover. It does not establish a damaged camera, radar, or harness.

## Evidence from the logs

Times below are relative to the first CAN event in each startup segment.

| Observation | Original route `1d`, segment 0 | `odytest` route `2a`, segment 0 |
| --- | ---: | ---: |
| Radar-disable successful TX echo | 14.928519 s | 13.171614 s |
| Radar `0x400` byte 0 mask `0x08` first set | 15.104746 s | 13.356540 s |
| Camera `RDM_PROBLEM` first set | 15.145013 s | 13.367455 s |
| Radar bit precedes camera fault by | 40.267 ms | 10.915 ms |

The bit remains set in all 3,000 radar samples in each later supplied segment
(`1d/19` and `2a/5`). The camera fault is also set in all 600 samples of each
camera HUD stream in those segments. In baseline `29/0`, the radar bit is
clear in all 3,050 samples and the camera fault is clear in all 610 samples
of each HUD stream. All 15,146 radar `0x400` frames across the five segments
pass the Honda nibble checksum; the observed bit is not the counter or
checksum field.

The camera and radar firmware identifiers match across the baseline and
old/new startup logs: `36161-THR-A230` and `36802-THR-A220`, respectively.
Different openpilot builds and operating modes remain comparison limits.

### Radar shutdown is partial, not a complete loss of radar traffic

Native radar powertrain streams stop after the disable request and openpilot
supplies replacements. However, local radar/camera traffic continues:
`0x400`, `0x410`, and `0x420` still arrive from radar-side bus 0 and are
forwarded toward camera-side bus 2.

Panda logs forwarded transmissions as bus number plus 128. In particular,
`src=130` is a camera-bus TX echo. A frame disappearing from ordinary bus-2
RX after relay opening does not mean it stopped reaching the camera.
The flagged `0x400` packets have those forwarding echoes.

This corrects the earlier blanket missing-traffic hypothesis. Likewise,
absence of generic Panda bus-1-to-bus-2 forwarding does not prove that a
bus-1 HUD field has no vehicle-side path to the camera; diagnostic replies
in the startup logs show that vehicle routing needs further investigation.

## What does RDM_OFF accomplish?

`RDM_OFF` and `RDM_PROBLEM` are separate fields. The Honda DBC places them in
LKAS HUD messages; the field name alone does not establish an acknowledged
camera-disable command.

The maintainer's stated intent is to suppress stock RDM/handsfree-timer
behavior. The `odytest` change sets both `RDM_OFF=1` and
`LANE_ASSIST_BEEP_OFF=1` for the Odyssey's alternate-radar configuration.
Any behavioral difference cannot automatically be assigned to RDM_OFF alone.

What the supplied logs establish:

- In `2a/5`, all 598 successful replacement `0x33D` transmissions carry
  `RDM_OFF=1` during actual cruise use.
- Camera-origin messages already report `RDM_OFF=1` before radar shutdown
  and before the replacement HUD transmissions in the startup logs.
- The camera subsequently reports both `RDM_OFF=1` and `RDM_PROBLEM=1`.
- In the factory-system baseline, the camera changes to `RDM_OFF=1`
  around 3.516 seconds without developing `RDM_PROBLEM`.

Thus, the flag may still affect HUD, warning, or timer behavior, but no
practical benefit on this Odyssey has been demonstrated by these logs.
It could be redundant in these drives because the camera already reports
RDM off. Calling the command unsuccessful solely because the fault persists
is too strong: we know it does not prevent this fault, but we have not
verified whether it suppresses the handsfree timer.

## Why can disabling radar produce a camera/RDM fault?

Honda service text for related systems says that radar error detection can
signal the camera, and that RDM can stop because of a connected-unit or
communication fault even when the camera itself is healthy. A radar-based
variant's system diagram routes camera-calculated RDM instructions through
the radar to other control units. This explains a dependency beyond camera
lane recognition. These sources describe related Honda architectures, not
an exact specification of this Odyssey's firmware:

- [Honda Civic FC/FK RDM troubleshooting, mirrored service text](https://honcivic.automotive-manuals.com/techinfo/html/en/civic-fc-fk/T007366.html)
- [Honda service diagrams, pages 59–60, mirrored PDF](https://www.civicx.com/forum/servicemanual/SM_41.pdf)

A plausible sequence is:

1. Radar communication is disabled for openpilot longitudinal takeover.
2. The integrated radar/camera system enters an unavailable or inconsistent
   state; radar-side `0x400` changes.
3. The camera reports RDM unavailable through `RDM_PROBLEM`.

This is a working hypothesis. The bit could instead indicate diagnostic or
communication-disabled mode, or both reports could reflect another shared
cause. Timing and forwarding establish association, not bit-level causality.
No verified public definition for this four-byte Bosch `0x400` bit was found.
The Nidec `RADAR_STATE` signal at the same address belongs to a different
protocol and cannot be used to decode it.

### Related maintainer development

[Commit 3dfaf2f9, dated October 15, 2026](https://github.com/mvl-boston/opendbc/commit/3dfaf2f934cc558c485b2a9d2eb1c4d20125ecb4)
was found on `cursor/rdx-mmr-alpha-startup-dtc-6860`. Its actual diff extends
startup diagnostic trouble code (DTC) clearing from CAN FD to classic Bosch
physical-radar alpha-long cars before deferred radar disable. It also
surfaces brake-error state in ACC fault reporting for alpha-long-capable
classic Bosch cars using stock ACC.

The commit rationale attributes next-drive brake/ACC faults to stored radar
communication faults from an earlier cutover. That is a useful separate
lead, not a confirmed explanation of our camera bit. The change does not
decode or alter `0x400`, and it was not part of the supplied log builds.
Its functional-address clearing affects other reachable ECUs as well as
the radar, so diagnostic codes should be recorded before any clearing.
Clearing stored faults does not by itself prove an active protocol problem
has been repaired.

## What remains to be tested

- Record camera, radar, and VSA diagnostic codes before clearing anything.
  These logs do not identify the specific stored DTC behind the RDM report.
- Compare a true active lateral-only/stock-longitudinal startup with an
  alpha-long startup. This separates relay interception from radar disable;
  the passive baseline changes both conditions.
- Examine cutover timing and replacement-stream continuity/counters against
  the `0x400` transition. A controlled radar-handback capture could show
  whether the state is reversible, without uniquely naming the bit.
- Assess handsfree-timer and warning behavior separately, with driver
  monitoring and normal supervision maintained. `RDM_PROBLEM` is not a
  valid stand-alone success/failure test of timer suppression.

Do not treat masking `0x400` or `RDM_PROBLEM` as a repair: it could conceal
an unavailable function. An exact runtime patch remains unproven.

The fault is already present well before the reported segment-19 slowdown;
it does not transition at that event. The earlier analysis found direct
negative-acceleration commands from the E2E planner during the slowdown.
These observations do not establish that the RDM fault caused it.

## Offline audit tool

From the repository root, with `pycapnp` and `zstandard` installed:

```sh
python tools/scripts/replay_odyssey_hud_rdm.py /path/to/rlog.zst
python -m unittest tools.scripts.tests.test_replay_odyssey_hud_rdm
```

The tool reads actual Panda TX/rejection echoes and camera RX separately;
it never connects to vehicle hardware or transmits CAN. Its defaults use
the non-CAN-FD Odyssey alpha-long layout: TX bus 1, camera RX bus 2.
An absent camera stream is `not_observed`, not success. `fault_observed`
means the bit appeared at least once, not that it remained set throughout.
The tool audits HUD and disable traffic; it does not automatically decode
the unknown radar `0x400` bit or read vehicle DTCs.

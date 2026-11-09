# MVL4096 integration branch

Branch: `codex-ody-mvl-20261108` in both `pselden/openpilot` and
`pselden/opendbc`. The published `sp-ody` release is unchanged.

## Integration bases

| Repository | MVL base | Retained personal snapshot |
|---|---|---|
| openpilot | `25f72bb83df7221e14dcce3d6b61791b87ef2eb0` | `4a6b1f363a59a8dbc8154e2794a8a45049f5872d` |
| opendbc | `763a209b1812e46f276f45bcba4b6445125bd631` | `8f774df9fb9f5f72838da6667b70af357b9730fe` |

The app base contains sunnypilot master `3d8f211d4`, including Blendful,
predictive Acceleration Boost, model artifact fixes, and MVL's exclusion of
SPLC while Blendful is enabled. MVL's shared Honda/Nidec code, schemas, runtime
pins, updater compatibility, and shared touch handling are retained.

The Odyssey overlay keeps the Brikowski stable longitudinal response through
`c91503afe`, van-load presets, cluster HUD, navigation turn suppression,
Factory mode, departure chime, launch helper, branding, and Dropbox archives.
Odyssey response algorithms now live in `opendbc/car/honda/odyssey.py`, with
explicit hooks in MVL's controller. Other Honda code stays on the MVL base.
The driving page exposes Acceleration Boost instead of the retired DEC toggle.
The settings-profile version stays at 1; this update does not force a reset.

## Steering range audit

| Surface | Previous release | This branch / handling |
|---|---|---|
| Command ceiling | 3840 | MVL's 4096, positive and negative |
| Reference normalization | 3840 / 2560 = 1.5 | 4096 / 2560 = 1.6 |
| Seed lateral acceleration factor | 1.35 | 1.44; same ordinary physical gain |
| Seed friction | 0.133333… | 0.125; same friction compensation in CAN counts |
| Normalized slew constant | 2 | 1.875; both give 76.8 counts per 100 Hz step |
| Slew accumulator | Fractional | Preserved; truncate only the emitted CAN command |
| Inactive steering | Zero | Preserved in both bus modes |
| Torque telemetry | Emitted count / 3840 | Emitted count / 4096; raw CAN telemetry is preserved |
| Learner buckets and fit | 2560-equivalent physical scale | Same physical scale, projected into the 4096 normalization |
| Minimum learning torque | 51.2 physical counts | Unchanged |
| Learned-fit cache version | 2 | 4097; reject both unscaled and previous 3840 fits |
| Enforced torque setup | Could reinitialize the unscaled seed | Honda interface reapplies range scaling during public tune setup |
| Driver override detection | Steering torque sensor units | Retain MVL's thresholds; command-range rescaling does not rescale sensor units |
| Saturation | Normalized command reaches 1 | Still 1, now corresponding to 4096; no larger software ceiling |
| CAN encoding / steering safety | Existing Honda message format and gating | Preserved; 4096 fits the existing signed signal |

The ceiling increases by 6.67%; this is not a 6.67% gain increase throughout
the ordinary torque-controlled range. The seed rescaling preserves that gain.
No claim is made about physical EPS response in the newly exposed top range.

Manual torque overrides remain values in the active normalized command scale.
They are not rewritten automatically because those saved keys are shared across
vehicles. An old manual factor needs multiplication by 4096/3840, and manual
friction needs division by that ratio, to preserve physical response. Review
any enabled manual overrides before trying the branch. NNLC output calibration
has not been validated for this Odyssey/range combination; initial validation
should use the torque controller with manual overrides and NNLC off.

## Maintenance

Use MVL as the app and vehicle integration upstream. Keep personal vehicle
behavior in the Odyssey module and small platform-specific hooks; carry app
features independently of runtime updates. Record both base SHAs on every
integration. MVL rewrites branch history, so compare against these pinned bases
and rebuild a candidate branch when needed rather than assuming a fast-forward
merge. Test the app and vehicle pair before advancing a release branch.

Do not replace whole shared Honda controllers with older fork files during an
update. Preserve Odyssey's 0.5 s longitudinal delay, alternate brake feedback,
per-controller gas map, and its existing -60..2000 gas / -3.5..2 acceleration
safety contract while taking MVL's unrelated vehicle and safety fixes.

## Validation and limits

Local results: 1,271 Honda/HUD/safety tests passed, 619 skipped, with 2,354
subtests; 193 application tests passed with 2 subtests. Lint, import scans,
parameter registration, and whitespace checks passed.

Checks cover Honda controller/HUD and safety behavior, physical steering
gain and slew, both steering bus modes, cache rejection, enforced-torque setup,
Blendful, predictive Boost, cruise/launch, navigation turn suppression, Factory
mode, settings, branch switching, archive behavior, imports, and parameter keys.
The native MPC solver was built locally for the planner regression tests.

The full Linux build, QCOM model inference/timing, recorded-drive replay, and
vehicle operation remain unvalidated. UI unit tests pass; a hidden-window render
could not initialize a graphics platform in this environment. No device or
firmware was changed. This is an integration branch, not a replacement release.

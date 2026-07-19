# Troubleshooting

## Contents

- Setup and discovery
- Port and servo communication
- Calibration
- Configuration validation
- YAM CAN and teleoperation
- Failure policy

## Setup and discovery

| Error or symptom | Meaning | Recovery |
|---|---|---|
| `UV is required but is not installed` | The initializer cannot create the Python environment | Install UV from its official instructions, then rerun the initializer |
| `ModuleNotFoundError` while starting calibration | The initialized dependencies or managed files are incomplete, or the command ran outside the project root | Confirm `pwd`, run through `uv`, and rerun the current initializer if a managed import is absent |
| `Bridge configuration not found: outputs/mission_hacks_calibrations.json` | The seed/current runtime config is absent or the command ran outside the project root | Confirm `pwd`; restore the initializer-provided seed config rather than inventing ranges |
| `Not a bridge configuration` | Required `yam_arm` or `leader_arms` object is missing | Restore valid structure, then validate through `load_bridge_config` |
| `Serial identity directory not found: /dev/serial/by-id` | Stable Linux serial identities are unavailable | Check USB connection, udev enumeration, and that the command runs on the hardware host |
| `No usb-1a86_USB_Single_Serial_* controllers found` | No matching leader controller alias is present | Check USB cable/controller enumeration with `ls -l /dev/serial/by-id` |
| `Unknown serial controller` / `Serial device not found` | The supplied alias/path is stale or incorrect | Re-list by-id devices and use the exact current full path |
| `No stable serial identity points to ...` | A transient `/dev/tty*` path has no matching by-id alias | Use or restore a stable by-id identity; do not key calibration by transient port |
| `The same controller was selected more than once` | Repeated `--port` values resolve to one controller | Remove the duplicate alias/path |
| `New leader(s) require --template-leader` | The controller has no mapping entry, and calibration cannot safely invent signs/joints | Choose a confirmed equivalent existing full leader ID as the template, then verify every mapping |
| `Template leader is not configured` | The template string does not exactly match a JSON leader key | Run `--show` and copy the full key exactly |

## Port and servo communication

| Error or symptom | Meaning | Recovery |
|---|---|---|
| `Could not open <device>` | Device is disconnected, busy, or inaccessible | Recheck by-id path, close other processes using it, and verify serial permissions |
| `Could not set baud rate to 1000000` | Wrong device, driver problem, disconnect, or unsupported setup | Confirm this is the Feetech controller and preserve the proven default unless hardware documentation says otherwise |
| `Health check failed: <leader-id>` | At least one configured servo missed one or more pings | Read the per-servo counts; fix power, cabling, or ID mismatch before calibration |
| `Servo <id> communication failed (comm=..., error=...)` | A read failed on the Feetech bus | Stop, check that leader's dedicated power supply and serial cable, then rerun check-only |
| `Servo <id> returned <raw>; expected 0..4095` | Corrupt read or incompatible protocol/address/range | Stop; inspect power/cable/controller settings rather than expanding the valid range |
| One servo is `0/N`, others are `N/N` | That configured ID is absent, duplicated, unpowered, or disconnected | Follow the servo ID mismatch procedure in `configuration.md` |
| Every servo is `0/N` | Controller opens but servo bus is unpowered or bus settings/wiring are wrong | Check the leader power brick and bus wiring before changing IDs |
| Intermittent counts | Marginal power, shared supply, loose cable, or bus noise | Give each leader its own supply, reseat cables, and require a clean check before proceeding |

Do not “fix” serial permissions by running the entire calibration or teleoperation process as root. Prefer the platform's serial-device group/udev setup; group changes may require logout/login.

## Calibration

| Error or symptom | Meaning | Recovery |
|---|---|---|
| `Servo <id> did not produce a stable initial reading` | Fewer than three of five valid readings agreed within the proven tolerance | Fix power/cabling/mechanical instability and retry; do not widen the tolerance |
| `Calibration for <leader-id> is incomplete (servo X: span Y)` | A listed servo moved fewer than `--minimum-span` ticks | Rerun and sweep that joint/gripper through both extremes |
| Ctrl-C exits before capture begins | Ctrl-C was used outside the intentional capture completion stage | Rerun; press Enter to start and use Ctrl-C only after all spans are captured |
| Existing JSON did not change after an error | Expected transactional behavior | Fix the error and rerun; the previous known config was deliberately preserved |
| Motion clips early after a successful run | The full leader range was not captured | Recalibrate and deliberately reach both mechanical extremes without forcing the mechanism |

The calibrator holds all results in memory. It writes a temporary sibling JSON, validates every leader with the runtime loader, and uses one atomic replacement only at the end. Do not suggest recovering partial controller results from a failed run.

## Configuration validation

| Error | Meaning and correction |
|---|---|
| `Expected a two-value range` | A joint, servo, or valid-position range is not a two-item JSON list |
| `YAM joint IDs must be contiguous from 0` | `joint_ranges` has a missing, extra, negative, or one-based key; restore `"0".."N-1"` |
| `YAM joint ranges must have shape (N, 2)` | The YAM range array is empty or malformed |
| `YAM joint ranges must be finite and non-zero` | A range is zero-width or non-finite; restore physical YAM limits |
| `Invalid port configuration` | Baud is non-positive or protocol end is not `0`/`1` |
| `Invalid position register configuration` | Address is negative or valid tick bounds are descending/equal |
| `Servo IDs must be unique and positive` | Duplicate/non-positive IDs exist in one leader entry; reconcile physical IDs |
| `Servo <id> has an invalid output range` | Calibration bounds are descending/equal; recalibrate rather than reversing bounds |
| `Servo <id> has an invalid YAM mapping` | Sign is not `-1`/`1` or `yam_joint` is outside zero-based bounds |
| `Multiple servos map to one YAM joint` | Two leader servos target the same follower joint; correct the mistaken mapping |
| `Invalid fixed YAM joint` | A fixed index is duplicated or out of bounds |
| `Fixed position is outside its YAM range` | The held value violates the physical target range |
| `A YAM joint cannot be both mapped and fixed` | Remove the overlap; each joint has one owner |
| `Every YAM joint must be mapped or fixed` | At least one zero-based YAM joint is uncovered |
| `Invalid leader config: ...` | JSON shape, type, required key, leader identity, or number conversion failed | Use the nested exception text to locate the exact malformed/missing value |

## YAM CAN and teleoperation

| Error or symptom | Meaning | Recovery |
|---|---|---|
| CAN channel not found | Requested `can0`/`can1` does not exist on this host | Inspect `ip -details link`; configure the correct adapter/channel per host documentation |
| CAN channel is down | Interface exists but cannot communicate | Ask approval before bringing it up; use the hardware's required bitrate (repository hardware notes specify 1 Mbit/s) |
| One arm never moves in a multi-arm command | Leader and CAN list lengths/order may differ; `zip` ignores extras | Require equal lengths and explicit matching order |
| Correct joint moves backward | That leader servo's `sign` is wrong | Stop, flip only that sign, validate, and retest one pair |
| Wrong YAM joint moves | `yam_joint` is wrong for that leader servo | Stop, correct zero-based mapping without creating duplicates/gaps, validate, and retest |
| YAM moves unexpectedly at startup | Leader pose did not correspond to a safe YAM target or pairing/order is wrong | Stop immediately; realign poses and verify one pair before relaunching |
| Leader read crashes teleoperation | Intentional fail-fast behavior from a servo/bus error | Fix the underlying leader communication problem; do not add a catch-and-continue loop |

## Failure policy

Every unexpected calibration or runtime error must remain fatal. Cleanup may close opened buses, but code and guidance must not consume the error, skip one failed controller, continue commanding other YAM arms, or overwrite calibration after a partial failure.

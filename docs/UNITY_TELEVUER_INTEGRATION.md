# Unity Tracking Integration for Televuer Flow

This document describes how to run teleoperation using Unity wrist tracking while keeping the existing teleop pipeline unchanged.

## What was added

- A compatibility bridge at `teleop/utils/unity_televuer_bridge.py`.
- A tracking source selector in `teleop/teleop_hand_and_arm.py`:
  - `--tracking-source televuer` (default, original behavior)
  - `--tracking-source unity` (new behavior)
- Unity bridge parameters:
  - `--unity-host` (default `0.0.0.0`)
  - `--unity-port` (default `8765`)

## Data contract (Unity -> Python)

Unity must send JSON messages with:

```json
{
  "head": [16 floats],
  "left": [16 floats],
  "right": [16 floats]
}
```

The 16 values should be column-major matrix data (matching current `TrackerSender.cs` ordering).

## Current limitations

- Unity source currently supports wrist poses only (arm IK path).
- No controller events are provided by Unity yet.
- No 25-point hand skeleton is provided by Unity yet.

Because of this, when using `--tracking-source unity`:

- Use `--input-mode hand`.
- Use `--ee dex1` (gripper path) or no hand actuation.
- `dex3`, `inspire_dfx`, `inspire_ftp`, and `brainco` are blocked intentionally.

## Run example

Start Unity scene and then launch:

```bash
python teleop/teleop_hand_and_arm.py \
  --tracking-source unity \
  --unity-host 0.0.0.0 \
  --unity-port 8765 \
  --input-mode hand \
  --arm G1_29 \
  --ee dex1 \
  --img-server-ip 192.168.123.164
```

## Next extension points

To reach full parity with Televuer, add these fields to Unity payload and map them in the bridge:

- Hand keypoints for `left_hand_pos` and `right_hand_pos` (25x3 each).
- Controller state fields (`*_thumbstickValue`, trigger values, A button).
- Optional pinch metrics for dex1 hand mode.

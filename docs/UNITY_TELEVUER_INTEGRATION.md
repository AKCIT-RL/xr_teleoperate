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

## Video Display Mode

The recommended display target is a 3D Quad with a `Renderer` only.

- Use the stereo side-by-side shader at [unity/Assets/Shaders/XRTeleopStereoSbs.shader](../unity/Assets/Shaders/XRTeleopStereoSbs.shader) on the Quad material.
- Assign the Quad renderer to `remoteVideoRenderer` in [WebRTCSignalingUnity.cs](../WebRTCSignalingUnity.cs).
- Do not use `RawImage` for the current setup.
- If you want monoscopic preview instead of stereo, keep the default material and omit `--stereo-video`.

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
  --img-server-ip 172.20.10.2
```

## Simulation Commands (Current Pipeline)

Use two terminals.

Terminal A (WebRTC signaling + video stream to Unity):

```bash
python python_webrtc.py \
  --host 0.0.0.0 \
  --port 8765 \
  --test-image C:/Users/muril/OneDrive/Desktop/input.jpg \
  --stereo-video \
  --video-fps 30 \
  --forward-url ws://127.0.0.1:9876
```

If you prefer live camera from teleimager instead of test image:

```bash
python python_webrtc.py \
  --host 0.0.0.0 \
  --port 8765 \
  --send-video \
  --stereo-video \
  --img-server-ip 192.168.123.164 \
  --video-fps 30 \
  --forward-url ws://127.0.0.1:9876
```

Terminal B (teleop simulation using Unity tracking bridge):

```bash
python teleop/teleop_hand_and_arm.py \
  --sim \
  --tracking-source unity \
  --unity-host 127.0.0.1 \
  --unity-port 9876 \
  --input-mode hand \
  --arm G1_29 \
  --ee dex1 \
  --img-server-ip 192.168.123.164
```

## Unity Scene Setup

1. Create a `Quad` in the scene and place it in front of the XR camera.
2. Assign an unlit material to the Quad.
3. Drag the Quad's `Renderer` to `remoteVideoRenderer` in [WebRTCSignalingUnity.cs](../WebRTCSignalingUnity.cs).
4. Leave `remoteVideoRenderer` as the only video target.
5. Keep `TrackerSender` assigned in the same GameObject or via Inspector.

## Next extension points

To reach full parity with Televuer, add these fields to Unity payload and map them in the bridge:

- Hand keypoints for `left_hand_pos` and `right_hand_pos` (25x3 each).
- Controller state fields (`*_thumbstickValue`, trigger values, A button).
- Optional pinch metrics for dex1 hand mode.

# Running Simulation 

## Terminal A: Isaac Sim with stereo head camera
python sim_main.py \
  --device cpu \
  --enable_cameras \
  --task Isaac-PickPlace-Cylinder-G129-Dex1-Joint \
  --enable_dex1_dds \
  --robot_type g129

## Terminal B: WebRTC with stereo preservation
python python_webrtc.py \
  --host 0.0.0.0 \
  --port 8765 \
  --send-video \
  --stereo-video \
  --img-server-ip 127.0.0.1 \
  --forward-url ws://127.0.0.1:9876

## Terminal C: Teleop bridge (accepts stereo from Isaac via image server)
python teleop/teleop_hand_and_arm.py \
  --sim \
  --tracking-source unity \
  --unity-host 127.0.0.1 \
  --unity-port 9876

## Different Networks (Home PC <-> University)

When Unity and Python are on different networks, NAT often blocks direct media paths. Use TURN.

### Python signaling/ICE command (example)

```bash
python python_webrtc.py \
  --host 0.0.0.0 \
  --port 8765 \
  --send-video \
  --stereo-video \
  --img-server-ip 127.0.0.1 \
  --forward-url ws://127.0.0.1:9876 \
  --ice-server stun:stun.l.google.com:19302 \
  --turn-url turn:YOUR_TURN_HOST:3478?transport=udp \
  --turn-username YOUR_USER \
  --turn-password YOUR_PASS
```

### Unity Inspector fields in `WebRTCSignalingUnity`

Set these values before building/deploying:

- `signalingUrl`: reachable URL for your signaling server (e.g. `ws://PUBLIC_IP_OR_DNS:8765`)
- `stunUrls`: comma-separated STUN list (e.g. `stun:stun.l.google.com:19302`)
- `turnUrls`: comma-separated TURN list (e.g. `turn:YOUR_TURN_HOST:3478?transport=udp`)
- `turnUsername`: TURN username
- `turnPassword`: TURN password

### Notes

- If direct P2P works, connection can go low-latency without relay.
- If direct P2P fails, TURN relay is mandatory across strict NAT networks.
- Keep port `8765` open on the signaling host or use a reverse proxy/tunnel.

### Commands for Tailscale


```bash
python sim_main.py \
--device cpu \
--enable_cameras \
--task Isaac-PickPlace-Cylinder-G129-Dex1-Joint \
--enable_dex1_dds \
--robot_type g129 
```

```bash
python python_webrtc.py \
--host 0.0.0.0 \
--port 8765 \
--send-video \
--stereo-video \
--img-server-ip 127.0.0.1 \
--forward-url ws://127.0.0.1:9876 \
--ice-server stun:stun.l.google.com:19302 
```

```bash
python teleop_hand_and_arm.py \
--sim \
--tracking-source unity \
--unity-host 127.0.0.1 \
--unity-port 9876 
```

### Remote PC: join same Tailscale tailnet

Install and login to same Tailscale account/team.
Confirm it can reach Sim PC Tailscale IP:
100.118.137.125
Sim PC MagicDNS name is:
pmec4090.taild17f05.ts.net

### Unity on remote PC: set network fields
signalingUrl: ws://100.118.137.125:8765
stunUrls: stun:stun.l.google.com:19302
turnUrls: leave empty for this first test
turnUsername: empty
turnPassword: empty

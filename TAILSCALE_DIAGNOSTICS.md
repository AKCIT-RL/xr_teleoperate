# Tailscale Video Reception Diagnostic Guide

## Problem
Video texture reception works **locally** but fails over **Tailscale VPN**. The texture stays `null` on the Unity side even though the WebRTC signaling and data channels work correctly.

## What's Been Changed

### Python Side (`python_webrtc.py`)
- Added frame transmission counters and logging to `ImageClientVideoTrack` and `StaticImageVideoTrack`
- Every 1 second, logs: `[ImageClientVideoTrack] sent N frames, latest shape: HxWxC`
- Added `--video-debug` flag for more verbose diagnostics
- Added log when video track is added: `[VIDEO-DEBUG] Video track successfully registered`

### Unity Side (`WebRTCSignalingUnity.cs`)
- Added counters: `onTrackCallCount`, `onVideoReceivedCallCount`
- Every 2 seconds, logs diagnostic summary:
  ```
  [TAILSCALE-DIAGNOSTIC] elapsed=XXs | onTrackCalls=N | onVideoReceivedCalls=M | appliedFrames=K | textureNull=true/false
  ```
- Enhanced OnTrack logging to show:
  - When callback fires
  - Track type (should be `VideoStreamTrack`)
  - Subscription status to OnVideoReceived
- Enhanced OnRemoteVideoReceived logging to show:
  - Every callback with frame count
  - Texture dimensions or warning if null

## Diagnostic Workflow

### Step 1: Test Locally (Baseline)
1. Run Python server with test image:
   ```bash
   python python_webrtc.py --test-image assets/g1/meshes/texture.png --video-debug
   ```
2. Connect from Unity **on same machine**
3. Check console logs:
   - **Python**: Should see `[ImageClientVideoTrack] sent 30 frames...` every ~1 second
   - **Unity**: Should see `[TAILSCALE-DIAGNOSTIC]` with values:
     - `onTrackCalls >= 1` (callback fired)
     - `onVideoReceivedCalls >= 30` (frames arriving)
     - `textureNull=false` (texture successfully assigned)
   - **Unity**: Depth reconstruction should render points

### Step 2: Test Over Tailscale
1. **From different machine** connected via Tailscale VPN
2. Update Unity `signalingUrl` to Tailscale IP, e.g., `ws://100.x.x.x:8765`
3. Connect and watch console:

#### Expected if it works:
```
[TAILSCALE-DIAGNOSTIC] elapsed=2.5s | onTrackCalls=1 | onVideoReceivedCalls=60 | appliedFrames=30 | textureNull=false
```

#### Expected if video frames don't arrive:
```
[TAILSCALE-DIAGNOSTIC] elapsed=2.5s | onTrackCalls=1 | onVideoReceivedCalls=0 | appliedFrames=0 | textureNull=true
```

#### Expected if track doesn't form:
```
[TAILSCALE-DIAGNOSTIC] elapsed=2.5s | onTrackCalls=0 | onVideoReceivedCalls=0 | appliedFrames=0 | textureNull=true
```

## Interpreting Results

### Scenario 1: `onTrackCalls=0` (Track never created)
**Root cause**: SDP/signaling issue
- Check Python console for SDP parsing errors
- Verify offer contains `m=video` line
- Tailscale may be filtering or modifying SDP

**Next step**:
- Add logging to `HandleSignalingMessage()` to print received offer SDP lines
- Check if Tailscale is modifying SDP (e.g., filtering certain attributes)

### Scenario 2: `onTrackCalls >= 1` but `onVideoReceivedCalls=0` (Track exists, no frames)
**Root cause**: Video frame transmission broken
- Track is created and OnTrack fires
- But OnVideoReceived callback never fires
- This suggests video RTP packets not arriving or being dropped

**Possible causes**:
- Codec mismatch (Tailscale may break certain codecs)
- MTU too small (Tailscale might use lower MTU)
- Video packet loss/corruption on Tailscale

**Next steps**:
- Force video codec: `--video-codec h264` or VP8
- Check Tailscale MTU: test with `ping -l 1500 <tailscale-ip>`
- Enable packet logging on Tailscale side

### Scenario 3: `onVideoReceivedCalls > 0` but `textureNull=true` (Frames arrive, texture fails)
**Root cause**: Video decoding failure
- Frames are reaching OnVideoReceived callback
- But texture assignment fails (or stays null)

**Possible causes**:
- Codec incompatibility with Unity WebRTC plugin
- Decoder crash on non-local network

**Next steps**:
- Add try-catch around texture assignment in OnRemoteVideoReceived
- Log error details if texture assignment fails

## Quick Test Commands

### Test 1: Basic connectivity
```bash
python python_webrtc.py --test-image assets/g1/meshes/texture.png --video-debug --host 0.0.0.0 --port 8765
```
Then connect from Unity (adjust IP to Tailscale IP if remote)

### Test 2: With Tailscale TURN (if available)
```bash
python python_webrtc.py --test-image assets/g1/meshes/texture.png --video-debug \
  --host 0.0.0.0 --port 8765 \
  --ice-server stun:stun.l.google.com:19302 \
  --ice-server stun:stun1.l.google.com:19302
```

### Test 3: Check if local still works after Tailscale attempt
```bash
# From same machine, this should still work
python python_webrtc.py --test-image assets/g1/meshes/texture.png --video-debug
```
If local fails after Tailscale test, restart Python server.

## Console Log Reference

### Python Output Examples
```
[ImageClientVideoTrack] sent 30 frames, latest shape: (480, 1280, 3)
[StaticImageVideoTrack] sent 30 frames, image shape: (480, 1280, 3)
🎥 Video track adicionada ao PeerConnection
[VIDEO-DEBUG] Video track successfully registered with peer connection
```

### Unity Output Examples
```
[TAILSCALE-DIAGNOSTIC] elapsed=1.2s | onTrackCalls=1 | onVideoReceivedCalls=30 | appliedFrames=30 | textureNull=false
🎥 Video track recebida do Python
[TAILSCALE-DIAGNOSTIC] OnTrack called (count=1), track kind: Video
[TAILSCALE-DIAGNOSTIC] OnVideoReceived called (count=30): 1280x480
✅ ICE Connected, DataChannel should be open now!
[TAILSCALE-DIAGNOSTIC] ICE CONNECTED - remoteVideoTrack != null: true
```

## Next Steps if Issue Persists

1. **If onTrackCalls=0**:
   - Log SDP offer/answer in both Python and Unity
   - Compare SDP structure between local (working) and Tailscale (failing)
   - Check if Tailscale modifies m=video lines

2. **If onVideoReceivedCalls=0**:
   - Capture Tailscale network traffic (tcpdump, Wireshark)
   - Check if RTP packets (port 5000+) are being sent
   - Try forcing different codec (add `--video-codec h264` to Python server)

3. **If texture stays null**:
   - Try simpler test: render just the track existence (not texture)
   - Check Unity WebRTC plugin logs for decode errors
   - Try reducing video resolution

## Temporary Workaround

If Tailscale video reception fails, try:
1. Using a TURN server instead of direct P2P
2. Using a different VPN solution (OpenVPN, WireGuard direct)
3. Testing with HTTP bridge instead of WebRTC (higher latency but more reliable)

---

**Last Updated**: When these diagnostics were added
**Status**: Active investigation - use logs to identify exact failure point

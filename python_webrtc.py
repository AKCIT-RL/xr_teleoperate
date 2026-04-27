import asyncio
import argparse
import json
import logging
import websockets
import fractions
import av

import numpy as np
from av import VideoFrame

from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate, RTCConfiguration, RTCIceServer, VideoStreamTrack

logging.basicConfig(level=logging.INFO)

pcs = set()
forwarder = None
video_track = None


class ImageClientVideoTrack(VideoStreamTrack):
    def __init__(self, img_server_ip: str, fps: float = 30.0, preserve_stereo: bool = False):
        super().__init__()
        from teleimager.image_client import ImageClient

        self._img_client = ImageClient(host=img_server_ip)
        self._fps = max(1.0, fps)
        self._time_base = fractions.Fraction(1, int(self._fps))
        self._pts = 0
        self._preserve_stereo = preserve_stereo
        self._debug_saved = False

    async def recv(self):
        # Use thread offload because image client access is blocking.
        head_img, _ = await asyncio.to_thread(self._img_client.get_head_frame)

        if head_img is None:
            head_img = np.zeros((480, 640, 3), dtype=np.uint8)

        # Keep the binocular pair intact when Unity should render stereo side-by-side.
        if not self._preserve_stereo and len(head_img.shape) == 3 and head_img.shape[1] >= 2 * head_img.shape[0]:
            head_img = head_img[:, : head_img.shape[1] // 2]

        # DEBUG: Save one frame to inspect if stereo is being sent
        if not self._debug_saved:
            import cv2
            debug_path = "/home/teleop/workspace/unity_frame_debug.jpg"
            cv2.imwrite(debug_path, head_img)
            logging.info(f"🐛 DEBUG: Saved frame to {debug_path} - Shape: {head_img.shape}, Stereo preserved: {self._preserve_stereo}")
            self._debug_saved = True

        # OpenCV-style frames are usually BGR.
        frame = VideoFrame.from_ndarray(head_img, format="bgr24")
        frame.pts = self._pts
        frame.time_base = self._time_base
        self._pts += 1
        return frame

    def close(self):
        try:
            self._img_client.close()
        except Exception:
            pass


class StaticImageVideoTrack(VideoStreamTrack):
    def __init__(self, image_path: str, fps: float = 30.0, preserve_stereo: bool = False):
        super().__init__()
        self._fps = max(1.0, fps)
        self._time_base = fractions.Fraction(1, int(self._fps))
        self._pts = 0
        self._preserve_stereo = preserve_stereo

        # Decode one frame from a local image file using PyAV/FFmpeg.
        container = av.open(image_path)
        frame = next(container.decode(video=0))
        self._image = frame.to_ndarray(format="bgr24")
        container.close()

    async def recv(self):
        image = self._image
        if not self._preserve_stereo and len(image.shape) == 3 and image.shape[1] >= 2 * image.shape[0]:
            image = image[:, : image.shape[1] // 2]

        frame = VideoFrame.from_ndarray(image, format="bgr24")
        frame.pts = self._pts
        frame.time_base = self._time_base
        self._pts += 1
        await asyncio.sleep(1.0 / self._fps)
        return frame

    def close(self):
        pass


class BridgeForwarder:
    def __init__(self, url: str, queue_size: int = 8):
        self.url = url
        self.queue = asyncio.Queue(maxsize=queue_size)
        self._task = None
        self._stop = asyncio.Event()

    def start(self):
        self._task = asyncio.create_task(self._run())

    async def close(self):
        self._stop.set()
        if self._task is not None:
            await self._task

    async def enqueue(self, payload: str):
        if self.queue.full():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        await self.queue.put(payload)

    async def _run(self):
        while not self._stop.is_set():
            try:
                async with websockets.connect(self.url) as ws:
                    logging.info(f"Forwarder connected to {self.url}")
                    while not self._stop.is_set():
                        try:
                            payload = await asyncio.wait_for(self.queue.get(), timeout=0.5)
                        except asyncio.TimeoutError:
                            continue
                        await ws.send(payload)
            except Exception as e:
                logging.warning(f"Forwarder disconnected: {e}")
                await asyncio.sleep(1.0)


def is_pose_payload(message: str) -> bool:
    try:
        data = json.loads(message)
    except json.JSONDecodeError:
        return False

    if not isinstance(data, dict):
        return False
    return "head" in data and "left" in data and "right" in data

# ------------------------------
# Filtragem de ICE
# ------------------------------
def is_valid_candidate(ip):
    # Ignora link-local IPv4 e IPv6 locais
    if ip.startswith("169.254."):
        return False
    if ip.startswith("fe80:") or ip.startswith("fc00:") or ip.startswith("fd00:"):
        return False
    return True

def candidate_from_sdp(sdp: str) -> RTCIceCandidate:
    bits = sdp.split()
    candidate = RTCIceCandidate(
        component=int(bits[1]),
        foundation=bits[0],
        ip=bits[4],
        port=int(bits[5]),
        priority=int(bits[3]),
        protocol=bits[2],
        type=bits[7],
    )

    for i in range(8, len(bits) - 1, 2):
        if bits[i] == "raddr":
            candidate.relatedAddress = bits[i + 1]
        elif bits[i] == "rport":
            candidate.relatedPort = int(bits[i + 1])
        elif bits[i] == "tcptype":
            candidate.tcpType = bits[i + 1]

    return candidate

def clean_sdp_for_unity(sdp, candidates=None):
    """
    Limpa e reorganiza o SDP para Unity WebRTC.
    - candidates: lista de strings de candidates já filtradas
    """
    cleaned = []
    for line in sdp.splitlines():
        if not line.strip():
            continue
        # Keep full SDP shape (video + data), only remove known problematic attrs.
        if line.startswith("a=extmap-allow-mixed") or line.startswith("a=ice-options"):
            continue
        cleaned.append(line)
    return "\r\n".join(cleaned)
# ------------------------------
# Handler WebSocket
# ------------------------------
async def handle_client(websocket):
    print("🌐 Cliente conectado")

    config = RTCConfiguration(iceServers=[RTCIceServer(urls=["stun:stun.l.google.com:19302"])])
    pc = RTCPeerConnection(configuration=config)
    pcs.add(pc)

    pending_candidates = []
    remote_description_set = False

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        print("🔗 Connection state:", pc.connectionState)

    @pc.on("iceconnectionstatechange")
    async def on_ice_state():
        print("🧊 ICE state:", pc.iceConnectionState)

    @pc.on("datachannel")
    def on_datachannel(channel):
        print(f"💬 DataChannel criado: {channel.label}")

        @channel.on("open")
        def on_open():
            print("🔥 PYTHON: DataChannel OPEN")
            channel.send("Hello from Python!")
            channel.send("Oi do Python!")

        @channel.on("message")
        def on_message(message):
            if isinstance(message, bytes):
                text = message.decode("utf-8", errors="replace")
            else:
                text = str(message)

            print("📥 Unity → Python:", text)

            if forwarder is not None and is_pose_payload(text):
                asyncio.create_task(forwarder.enqueue(text))

    @pc.on("icecandidate")
    async def on_icecandidate(event):
        if event.candidate:
            if not is_valid_candidate(event.candidate.ip):
                print("🚫 Ignorando candidate inválido (não enviado):", event.candidate.ip)
                return

            await websocket.send(json.dumps({
                "type": "candidate",
                "candidate": event.candidate.to_sdp(),
                "sdpMid": event.candidate.sdpMid,
                "sdpMLineIndex": event.candidate.sdpMLineIndex,
            }))
        else:
            await websocket.send(json.dumps({"type": "candidate", "candidate": None}))
            print("A")

    # ------------------------------
    # Mensagens WebSocket
    # ------------------------------
    try:
        async for message in websocket:
            data = json.loads(message)

            if data.get("type") == "offer":
                print("📥 OFFER recebida")
                offer = RTCSessionDescription(sdp=data["sdp"], type=data["type"])
                await pc.setRemoteDescription(offer)
                remote_description_set = True
                print("✅ RemoteDescription setada")

                for c in pending_candidates:
                    await pc.addIceCandidate(c)
                pending_candidates.clear()
                print("🧊 Pending ICE aplicados")

                if video_track is not None:
                    if "m=video" in data["sdp"]:
                        pc.addTrack(video_track)
                        print("🎥 Video track adicionada ao PeerConnection")
                    else:
                        print("⚠️ Offer sem m=video; Unity precisa solicitar vídeo (AddTransceiver RecvOnly).")

                answer = await pc.createAnswer()
                await pc.setLocalDescription(answer)

                while pc.iceGatheringState != "complete":
                    await asyncio.sleep(0.1)

                new_sdp = clean_sdp_for_unity(pc.localDescription.sdp)
                
                await websocket.send(json.dumps({
                    "type": pc.localDescription.type,
                    "sdp": new_sdp
                }))
                print("📤 Answer filtrada enviada")

            elif data.get("type") == "candidate":
                candidate_str = data.get("candidate")
                if candidate_str:
                    ice_candidate = candidate_from_sdp(candidate_str)
                    ice_candidate.sdpMid = data.get("sdpMid", "0")
                    ice_candidate.sdpMLineIndex = data.get("sdpMLineIndex", 0)

                    if not is_valid_candidate(ice_candidate.ip):
                        print("🚫 Ignorando candidate inválido:", ice_candidate.ip)
                        continue

                    if remote_description_set:
                        await pc.addIceCandidate(ice_candidate)
                        print("🧊 ICE aplicado")
                    else:
                        pending_candidates.append(ice_candidate)
                        print("⏳ ICE armazenado (aguardando SDP)")
                else:
                    await pc.addIceCandidate(None)
                    print("🏁 ICE finalizado")

            elif data.get("type") == "bye":
                print("👋 Cliente desconectou")
                break

    except Exception as e:
        print("❌ Erro:", e)

    finally:
        await pc.close()
        pcs.discard(pc)
        print("🛑 PeerConnection fechado")

# ------------------------------
# Servidor
# ------------------------------
async def main():
    global forwarder, video_track

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Signaling server host")
    parser.add_argument("--port", type=int, default=8765, help="Signaling server port")
    parser.add_argument("--forward-url", type=str, default=None, help="Optional websocket URL to forward Unity pose payloads")
    parser.add_argument("--send-video", action="store_true", help="Send head camera video track to Unity over WebRTC")
    parser.add_argument("--stereo-video", action="store_true", help="Keep binocular frames side-by-side instead of cropping to one eye")
    parser.add_argument("--test-image", type=str, default=None, help="Optional local image path (jpg/png) to stream as repeated video frames")
    parser.add_argument("--img-server-ip", type=str, default="127.0.0.1", help="Image server IP for video source")
    parser.add_argument("--video-fps", type=float, default=30.0, help="Video FPS sent to Unity")
    args = parser.parse_args()

    if args.forward_url:
        forwarder = BridgeForwarder(args.forward_url)
        forwarder.start()

    if args.test_image:
        video_track = StaticImageVideoTrack(args.test_image, fps=args.video_fps, preserve_stereo=args.stereo_video)
    elif args.send_video:
        video_track = ImageClientVideoTrack(args.img_server_ip, fps=args.video_fps, preserve_stereo=args.stereo_video)

    server = await websockets.serve(handle_client, args.host, args.port)
    print(f"🚀 Servidor rodando em ws://{args.host}:{args.port}")
    if args.forward_url:
        print(f"🔁 Forward de poses para {args.forward_url}")
    if args.send_video:
        print(f"🎥 Video enabled from image server {args.img_server_ip}")
    elif args.test_image:
        print(f"🖼️  Test image video enabled from {args.test_image}")
    if args.stereo_video:
        print("🥽 Stereo side-by-side mode enabled")

    try:
        await asyncio.Future()
    finally:
        server.close()
        await server.wait_closed()
        if forwarder is not None:
            await forwarder.close()
        if video_track is not None:
            video_track.close()

if __name__ == "__main__":
    asyncio.run(main())
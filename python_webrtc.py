import asyncio
import argparse
import json
import logging
import websockets

from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate, RTCConfiguration, RTCIceServer

logging.basicConfig(level=logging.INFO)

pcs = set()
forwarder = None


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
                        payload = await asyncio.wait_for(self.queue.get(), timeout=0.5)
                        await ws.send(payload)
            except asyncio.TimeoutError:
                continue
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
    lines = sdp.splitlines()
    session = []
    media = []

    # separa session vs media
    in_media = False
    for line in lines:
        if not line.strip():
            continue
        if line.startswith("m="):
            in_media = True

        # remove problemáticos
        if line.startswith("a=extmap-allow-mixed") or line.startswith("a=ice-options"):
            continue

        if in_media:
            media.append(line)
        else:
            session.append(line)

    # msid-semantic uma vez, logo após a=group:BUNDLE
    insert_idx = next((i for i, l in enumerate(session) if l.startswith("a=group:BUNDLE")), -1)
    if insert_idx != -1:
        session.insert(insert_idx + 1, "a=msid-semantic: WMS")
    else:
        session.append("a=msid-semantic: WMS")

    # extrai campos importantes do media
    m_application = next((l for l in media if l.startswith("m=application")), None)
    c_line = next((l for l in media if l.startswith("c=IN")), None)
    mid = next((l for l in media if l.startswith("a=mid")), None)
    sctp = next((l for l in media if l.startswith("a=sctp-port")), None)
    fingerprint = next((l for l in media if l.startswith("a=fingerprint:sha-256")), None)
    ice_ufrag = next((l for l in media if l.startswith("a=ice-ufrag")), None)
    ice_pwd = next((l for l in media if l.startswith("a=ice-pwd")), None)

    # monta media na ordem que Unity aceita
    new_media = [
        m_application,
        c_line,
        mid,
        sctp,
    ]

    # adiciona candidates se fornecidos
    if candidates:
        new_media.extend(candidates)
        new_media.append("a=end-of-candidates")

    # adiciona ufrag/pwd/fingerprint/setup
    new_media.extend([ice_ufrag, ice_pwd, fingerprint, "a=setup:active"])

    new_media = [l for l in new_media if l]

    return "\r\n".join(session + new_media)
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

                answer = await pc.createAnswer()
                await pc.setLocalDescription(answer)

                # ------------------------------
                # Filtra IPv6 e link-local do SDP
                # ------------------------------
                sdp_lines = pc.localDescription.sdp.splitlines()
                new_sdp_lines = []
                connection_line_added = False

                for line in sdp_lines:

                    # Remove IPv6 ou link-local
                    if line.startswith("c=IN IP6") or "169.254." in line:
                        print("🚫 Removendo linha de conexão inválida:", line)
                        continue

                    # Filtra candidates inválidos
                    if line.startswith("a=candidate:"):
                        parts = line.split()
                        ip = parts[4]
                        if ":" in ip or ip.startswith("169.254."):
                            print("🚫 Removendo candidate inválido do SDP:", ip)
                            continue

                    new_sdp_lines.append(line)

                # ► Verifica se ainda existe "c=IN"
                has_connection_line = any(l.startswith("c=IN") for l in new_sdp_lines)

                if not has_connection_line:
                    import socket
                    ip = socket.gethostbyname(socket.gethostname())
                    good_c_line = f"c=IN IP4 {ip}"
                    print("➕ Adicionando linha de conexão válida:", good_c_line)

                    # Inserir logo após "m=application"
                    for i, l in enumerate(new_sdp_lines):
                        if l.startswith("m=application"):
                            new_sdp_lines.insert(i + 1, good_c_line)
                            break

                # Monta o SDP final
                new_sdp = "\r\n".join(new_sdp_lines)

                while pc.iceGatheringState != "complete":
                    await asyncio.sleep(0.1)

                
                new_sdp = clean_sdp_for_unity(new_sdp)
                answer_fixa = [
                    "v=0",
                    "o=- 0 0 IN IP4 0.0.0.0",
                    "s=-",
                    "t=0 0",
                    "a=group:BUNDLE 0",
                    "a=msid-semantic:WMS",
                    "m=application 54380 UDP/DTLS/SCTP webrtc-datachannel",
                    "c=IN IP4 0.0.0.0",
                    "a=mid:0",
                    "a=max-message-size:65536",
                    "a=candidate:a138df236977f30fc6bd7add39969f04 1 udp 2130706431 fd7a:115c:a1e0::b101:8c83 54380 typ host",
                    "a=candidate:ad14d2108c406b61752b2ccd658c2ab1 1 udp 2130706431 100.104.140.98 54381 typ host",
                    "a=candidate:13aab828fd3e44e4e88e5b6941da9711 1 udp 2130706431 2804:3d90:8286:49e0:fce0:9a0:d81b:8949 54382 typ host",
                    "a=candidate:bee9f57f2289be8d0ba405c9987b9c3b 1 udp 2130706431 2804:3d90:8286:49e0:90e5:39fa:6edc:b6ca 54383 typ host",
                    "a=candidate:40537ee97c0b7cd4fcd42ec8e27c5e50 1 udp 2130706431 192.168.1.20 54384 typ host",
                    "a=candidate:8da486d9d6c197b4e10ed3fdf23632ac 1 udp 1694498815 177.200.36.116 5886 typ srflx raddr 192.168.1.20 rport 54384",
                    "a=end-of-candidates",
                    "a=ice-ufrag:f6fD",
                    "a=ice-pwd:4MxocW7cRhHsR081u278z9",
                    "a=setup:active",
                    "a=fingerprint:sha-256 AC:78:1A:DC:C3:66:43:11:77:87:6B:C1:AD:2D:81:66:9C:AC:DE:84:28:CA:B7:58:BE:5B:FB:08:D8:0E:1D:79",
                    "a=sctp-port:5000"
                ]

                # Para enviar como string única com \r\n:
                answer_sdp = "\r\n".join(answer_fixa)
                
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
    global forwarder

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Signaling server host")
    parser.add_argument("--port", type=int, default=8765, help="Signaling server port")
    parser.add_argument("--forward-url", type=str, default=None, help="Optional websocket URL to forward Unity pose payloads")
    args = parser.parse_args()

    if args.forward_url:
        forwarder = BridgeForwarder(args.forward_url)
        forwarder.start()

    server = await websockets.serve(handle_client, args.host, args.port)
    print(f"🚀 Servidor rodando em ws://{args.host}:{args.port}")
    if args.forward_url:
        print(f"🔁 Forward de poses para {args.forward_url}")

    try:
        await asyncio.Future()
    finally:
        server.close()
        await server.wait_closed()
        if forwarder is not None:
            await forwarder.close()

if __name__ == "__main__":
    asyncio.run(main())
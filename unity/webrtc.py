import asyncio
import os
from aiortc import RTCPeerConnection, RTCSessionDescription

OFFER_FILE = "Assets/offer.txt"
ANSWER_FILE = "Assets/answer.txt"

ICE_UNITY = "Assets/ice_unity.txt"
ICE_PYTHON = "Assets/ice_python.txt"


async def run_pc():
    pc = RTCPeerConnection()

    # -----------------------------------
    # Evento: DataChannel vindo da Unity
    # -----------------------------------
    @pc.on("datachannel")
    def on_datachannel(channel):
        print(f"📡 Python: DataChannel recebido → {channel.label}")

        @channel.on("message")
        def on_message(message):
            print("📨 Unity → Python:", message)
            channel.send("Olá Unity, aqui é Python!")

    # -----------------------------------
    # Captura ICE candidates do Python
    # -----------------------------------
    @pc.on("icecandidate")
    def on_icecandidate(candidate):
        if candidate:
            cand = candidate.to_sdp()
            with open(ICE_PYTHON, "a") as f:
                f.write(cand + "\n")

    # -----------------------------------
    # Espera Offer
    # -----------------------------------
    print("🕒 Aguardando Offer...")
    while not os.path.exists(OFFER_FILE):
        await asyncio.sleep(0.1)

    offer_sdp = open(OFFER_FILE, "r", encoding="utf-8").read()
    offer = RTCSessionDescription(offer_sdp, "offer")

    print("📥 Offer recebida")
    await pc.setRemoteDescription(offer)

    # -----------------------------------
    # Aplica ICE da Unity (se já existir)
    # -----------------------------------
    if os.path.exists(ICE_UNITY):
        for line in open(ICE_UNITY, "r"):
            cand = line.strip()
            if cand:
                pc.addIceCandidate(candidate=cand)

    # -----------------------------------
    # Cria Answer
    # -----------------------------------
    print("📝 Criando Answer...")
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    # -----------------------------------
    # Espera ICE gathering
    # -----------------------------------
    print("🧊 Python Gather ICE...")
    while pc.iceGatheringState != "complete":
        await asyncio.sleep(0.1)

    # -----------------------------------
    # Salva Answer
    # -----------------------------------
    with open(ANSWER_FILE, "wb") as f:
        f.write(pc.localDescription.sdp.encode("utf-8"))

    print("✅ Answer salva")
    print("🚀 Aguardando mensagens...")

    while True:
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(run_pc())
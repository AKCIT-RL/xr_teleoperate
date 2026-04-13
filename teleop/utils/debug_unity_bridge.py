import argparse
import asyncio
import json
import os
import sys
import time

import numpy as np
import websockets

try:
    from teleop.utils.unity_televuer_bridge import UnityTeleVuerBridge
except ModuleNotFoundError:
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if repo_root not in sys.path:
        sys.path.append(repo_root)
    from teleop.utils.unity_televuer_bridge import UnityTeleVuerBridge


def make_pose(tx: float, ty: float, tz: float) -> list:
    pose = np.eye(4, dtype=np.float64)
    pose[0, 3] = tx
    pose[1, 3] = ty
    pose[2, 3] = tz
    # Unity sender uses column-major ordering in TrackerSender.cs
    return pose.reshape(16, order="F").tolist()


async def send_unity_like_packet(uri: str, payload: dict):
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps(payload))


def run_debug(host: str, port: int):
    bridge = UnityTeleVuerBridge(host=host, port=port)
    try:
        # Let websocket server come up.
        time.sleep(0.2)

        packet = {
            "head": make_pose(0.0, 1.6, -0.2),
            "left": make_pose(-0.30, 1.25, -0.45),
            "right": make_pose(0.30, 1.25, -0.45),
        }

        uri = f"ws://{host}:{port}"
        asyncio.run(send_unity_like_packet(uri, packet))

        # Give bridge time to process one message.
        time.sleep(0.2)

        tele_data = bridge.get_tele_data()

        print("=== Unity Bridge Debug ===")
        print("Head pose (Robot basis):")
        print(np.array_str(tele_data.head_pose, precision=4, suppress_small=True))
        print()

        print("Left wrist pose (Unitree-compatible):")
        print(np.array_str(tele_data.left_wrist_pose, precision=4, suppress_small=True))
        print()

        print("Right wrist pose (Unitree-compatible):")
        print(np.array_str(tele_data.right_wrist_pose, precision=4, suppress_small=True))
        print()

        left_t = tele_data.left_wrist_pose[:3, 3]
        right_t = tele_data.right_wrist_pose[:3, 3]
        rot_ok = np.isfinite(tele_data.left_wrist_pose[:3, :3]).all() and np.isfinite(tele_data.right_wrist_pose[:3, :3]).all()
        trans_ok = np.isfinite(left_t).all() and np.isfinite(right_t).all()

        print(f"Finite rotation blocks: {rot_ok}")
        print(f"Finite translation vectors: {trans_ok}")
        print(f"Left wrist translation:  {left_t}")
        print(f"Right wrist translation: {right_t}")

        if rot_ok and trans_ok:
            print("\nRESULT: Bridge received Unity packet and produced valid tele-data.")
        else:
            print("\nRESULT: Invalid numeric output. Check payload format and transforms.")

    finally:
        bridge.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Local UnityTeleVuerBridge debug without robot stack.")
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9876)
    args = parser.parse_args()

    run_debug(args.host, args.port)

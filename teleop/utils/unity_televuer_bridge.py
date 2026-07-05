import asyncio
import json
import threading
from dataclasses import dataclass, field

import numpy as np
import websockets


T_ROBOT_OPENXR = np.array([
    [0, 0, -1, 0],
    [-1, 0, 0, 0],
    [0, 1, 0, 0],
    [0, 0, 0, 1],
])

T_OPENXR_ROBOT = np.array([
    [0, -1, 0, 0],
    [0, 0, 1, 0],
    [-1, 0, 0, 0],
    [0, 0, 0, 1],
])

CONST_HEAD_POSE = np.array([
    [1, 0, 0, 0],
    [0, 1, 0, 1.5],
    [0, 0, 1, -0.2],
    [0, 0, 0, 1],
])

CONST_RIGHT_ARM_POSE = np.array([
    [1, 0, 0, 0.15],
    [0, 1, 0, 1.13],
    [0, 0, 1, -0.3],
    [0, 0, 0, 1],
])

CONST_LEFT_ARM_POSE = np.array([
    [1, 0, 0, -0.15],
    [0, 1, 0, 1.13],
    [0, 0, 1, -0.3],
    [0, 0, 0, 1],
])


def safe_mat_update(prev_mat, mat):
    det = np.linalg.det(mat)
    if not np.isfinite(det) or np.isclose(det, 0.0, atol=1e-6):
        return prev_mat, False
    return mat, True


@dataclass
class TeleDataCompat:
    head_pose: np.ndarray = field(default_factory=lambda: np.eye(4, dtype=np.float64))
    left_wrist_pose: np.ndarray = field(default_factory=lambda: np.eye(4, dtype=np.float64))
    right_wrist_pose: np.ndarray = field(default_factory=lambda: np.eye(4, dtype=np.float64))
    left_hand_pos: np.ndarray = field(default_factory=lambda: np.zeros((25, 3), dtype=np.float64))
    right_hand_pos: np.ndarray = field(default_factory=lambda: np.zeros((25, 3), dtype=np.float64))
    # convenção alinhada ao v1: 10.0 (solto/aberto) → 0.0 (apertado/fechado)
    left_ctrl_triggerValue: float = 10.0
    right_ctrl_triggerValue: float = 10.0
    left_hand_pinchValue: float = 10.0
    right_hand_pinchValue: float = 10.0
    left_ctrl_trigger: bool = False
    right_ctrl_trigger: bool = False
    left_ctrl_aButton: bool = False
    left_ctrl_bButton: bool = False
    right_ctrl_aButton: bool = False
    right_ctrl_bButton: bool = False
    left_ctrl_thumbstick: bool = False
    right_ctrl_thumbstick: bool = False
    left_ctrl_thumbstickValue: np.ndarray = field(default_factory=lambda: np.zeros(2, dtype=np.float64))
    right_ctrl_thumbstickValue: np.ndarray = field(default_factory=lambda: np.zeros(2, dtype=np.float64))


class UnityTeleVuerBridge:
    """
    Ponte de compatibilidade que expõe uma interface TeleVuer-like e ingere
    head/left/right (4x4) + estado dos controles enviados pela Unity via websocket.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 8766):
        self._host = host
        self._port = port
        self._lock = threading.Lock()
        self._clients = set()
        self._head_pose = CONST_HEAD_POSE.copy()
        self._left_arm_pose = CONST_LEFT_ARM_POSE.copy()
        self._right_arm_pose = CONST_RIGHT_ARM_POSE.copy()
        # estado de input cru (default = neutro/solto)
        self._input = {
            "leftTrigger": 0.0, "rightTrigger": 0.0,
            "leftStickX": 0.0, "leftStickY": 0.0,
            "rightStickX": 0.0, "rightStickY": 0.0,
            "leftPrimary": False, "leftSecondary": False,
            "rightPrimary": False, "rightSecondary": False,
            "leftStickClick": False, "rightStickClick": False,
        }
        self._stop_flag = threading.Event()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve())

    async def _serve(self):
        server = await websockets.serve(self._handle_client, self._host, self._port)
        try:
            while not self._stop_flag.is_set():
                await asyncio.sleep(0.1)
        finally:
            server.close()
            await server.wait_closed()

    @staticmethod
    def _matrix_from_payload(values):
        arr = np.asarray(values, dtype=np.float64)
        if arr.size != 16:
            raise ValueError(f"Expected 16 values for matrix, got {arr.size}")
        return arr.reshape((4, 4), order="F")

    async def _handle_client(self, websocket):
        with self._lock:
            self._clients.add(websocket)

        async for raw in websocket:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")

            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if not isinstance(payload, dict):
                continue

            head = payload.get("head")
            left = payload.get("left")
            right = payload.get("right")
            if left is None or right is None:
                continue

            try:
                head_pose = self._matrix_from_payload(head) if head is not None else None
                left_pose = self._matrix_from_payload(left)
                right_pose = self._matrix_from_payload(right)
            except (TypeError, ValueError):
                continue

            with self._lock:
                if head_pose is not None:
                    self._head_pose = head_pose
                self._left_arm_pose = left_pose
                self._right_arm_pose = right_pose
                # ✨ atualiza estado de input só com os campos presentes
                for k in self._input:
                    if k in payload:
                        self._input[k] = payload[k]

        with self._lock:
            self._clients.discard(websocket)

    def get_tele_data(self):
        with self._lock:
            head_raw = self._head_pose.copy()
            left_raw = self._left_arm_pose.copy()
            right_raw = self._right_arm_pose.copy()
            inp = dict(self._input)

        bxr_world_head, _ = safe_mat_update(CONST_HEAD_POSE, head_raw)
        left_ipxr_bxr_world_arm, left_arm_ok  = safe_mat_update(CONST_LEFT_ARM_POSE, left_raw)
        right_ipxr_bxr_world_arm, right_arm_ok = safe_mat_update(CONST_RIGHT_ARM_POSE, right_raw)

        brobot_world_head = T_ROBOT_OPENXR @ bxr_world_head @ T_OPENXR_ROBOT
        left_ipxr_brobot_world_arm  = T_ROBOT_OPENXR @ left_ipxr_bxr_world_arm  @ T_OPENXR_ROBOT
        right_ipxr_brobot_world_arm = T_ROBOT_OPENXR @ right_ipxr_bxr_world_arm @ T_OPENXR_ROBOT

        # Convenção do punho: a grip pose do controller da Unity já chega ~na
        # convenção URDF Unitree (igual ao branch de controller do v1). NÃO
        # aplicar T_TO_UNITREE (Rx±90) — confirmado empiricamente: roll no
        # controle → roll limpo no robô. Correção = identidade.
        left_ipunitree_brobot_world_arm  = left_ipxr_brobot_world_arm.copy()
        right_ipunitree_brobot_world_arm = right_ipxr_brobot_world_arm.copy()

        left_ipunitree_brobot_head_arm  = left_ipunitree_brobot_world_arm.copy()
        right_ipunitree_brobot_head_arm = right_ipunitree_brobot_world_arm.copy()
        left_ipunitree_brobot_head_arm[0:3, 3]  -= brobot_world_head[0:3, 3]
        right_ipunitree_brobot_head_arm[0:3, 3] -= brobot_world_head[0:3, 3]

        left_ipunitree_brobot_wrist_arm  = left_ipunitree_brobot_head_arm.copy()
        right_ipunitree_brobot_wrist_arm = right_ipunitree_brobot_head_arm.copy()
        left_ipunitree_brobot_wrist_arm[0, 3]  += 0.15
        right_ipunitree_brobot_wrist_arm[0, 3] += 0.15
        left_ipunitree_brobot_wrist_arm[2, 3]  += 0.45
        right_ipunitree_brobot_wrist_arm[2, 3] += 0.45

        # ---- input dos controles nas convenções do v1 ----
        # trigger cru 0..1 → 10..0 (0 = apertado/fechado), igual doc 3/v1
        left_trig_v1  = 10.0 - float(inp["leftTrigger"]) * 10.0
        right_trig_v1 = 10.0 - float(inp["rightTrigger"]) * 10.0

        # thumbstick: v1 usa front=(0,-1). OpenXR/Unity entrega y+ pra frente,
        # então invertemos y pra casar a convenção esperada pelo doc 5.
        left_stick  = np.array([float(inp["leftStickX"]),  -float(inp["leftStickY"])])
        right_stick = np.array([float(inp["rightStickX"]), -float(inp["rightStickY"])])

        return TeleDataCompat(
            head_pose=brobot_world_head,
            left_wrist_pose=left_ipunitree_brobot_wrist_arm,
            right_wrist_pose=right_ipunitree_brobot_wrist_arm,
            left_ctrl_triggerValue=left_trig_v1,
            right_ctrl_triggerValue=right_trig_v1,
            left_hand_pinchValue=left_trig_v1,
            right_hand_pinchValue=right_trig_v1,
            left_ctrl_trigger=float(inp["leftTrigger"]) > 0.5,
            right_ctrl_trigger=float(inp["rightTrigger"]) > 0.5,
            left_ctrl_aButton=bool(inp["leftPrimary"]),
            left_ctrl_bButton=bool(inp["leftSecondary"]),
            right_ctrl_aButton=bool(inp["rightPrimary"]),
            right_ctrl_bButton=bool(inp["rightSecondary"]),
            left_ctrl_thumbstick=bool(inp["leftStickClick"]),
            right_ctrl_thumbstick=bool(inp["rightStickClick"]),
            left_ctrl_thumbstickValue=left_stick,
            right_ctrl_thumbstickValue=right_stick,
        )

    def render_to_xr(self, _img):
        return None

    async def _broadcast_feedback(self, payload: str):
        with self._lock:
            clients = list(self._clients)
        if not clients:
            return
        await asyncio.gather(*(client.send(payload) for client in clients), return_exceptions=True)

    def send_feedback(self, payload):
        if isinstance(payload, dict):
            payload = json.dumps(payload)
        elif not isinstance(payload, str):
            payload = str(payload)
        print(f"📳 Unity bridge feedback queued: {payload}")
        if self._loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(self._broadcast_feedback(payload), self._loop)

    def close(self):
        self._stop_flag.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)
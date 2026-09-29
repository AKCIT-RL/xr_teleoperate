"""Cliente do IPC do teleop (teleop/utils/ipc.py, flag --ipc).

- comandos: REQ em ipc://@xr_teleoperate_data.ipc  (CMD_START / CMD_RECORD_TOGGLE / CMD_STOP)
- estado:   SUB em ipc://@xr_teleoperate_hb.ipc    (START, STOP, READY, RECORD_RUNNING a 10 Hz)
"""
import asyncio
import time
import uuid

import zmq
import zmq.asyncio

DATA_ADDR = "ipc://@xr_teleoperate_data.ipc"
HB_ADDR = "ipc://@xr_teleoperate_hb.ipc"
COMMANDS = {"start": "CMD_START", "record": "CMD_RECORD_TOGGLE", "stop": "CMD_STOP"}


class TeleopIPC:
    def __init__(self):
        self.ctx = zmq.asyncio.Context.instance()
        self.state = {}
        self.last_hb = 0.0
        self.record_started_at = None
        self._task = None

    @property
    def online(self) -> bool:
        return time.time() - self.last_hb < 1.0

    def info(self) -> dict:
        s = self.state if self.online else {}
        rec = bool(s.get("RECORD_RUNNING"))
        return {
            "online": self.online,
            "start": bool(s.get("START")),
            "ready": bool(s.get("READY")),
            "recording": rec,
            "record_elapsed": (time.time() - self.record_started_at) if rec and self.record_started_at else 0,
        }

    def start(self):
        self._task = asyncio.create_task(self._hb_loop())

    async def _hb_loop(self):
        sub = self.ctx.socket(zmq.SUB)
        sub.setsockopt(zmq.RCVHWM, 1)
        sub.setsockopt_string(zmq.SUBSCRIBE, "")
        sub.connect(HB_ADDR)
        while True:
            try:
                if await sub.poll(500):
                    msg = await sub.recv_json()
                    was_rec = bool(self.state.get("RECORD_RUNNING")) and self.online
                    self.state = msg
                    self.last_hb = time.time()
                    if msg.get("RECORD_RUNNING") and not was_rec:
                        self.record_started_at = time.time()
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(0.5)
        sub.close(0)

    async def send(self, action: str) -> dict:
        cmd = COMMANDS.get(action)
        if cmd is None:
            return {"status": "error", "msg": f"comando desconhecido: {action}"}
        if not self.online:
            return {"status": "error", "msg": "teleop não está respondendo (sem heartbeat)"}
        req = self.ctx.socket(zmq.REQ)
        req.setsockopt(zmq.LINGER, 0)
        req.connect(DATA_ADDR)
        try:
            await req.send_json({"reqid": str(uuid.uuid4()), "cmd": cmd})
            if await req.poll(1500):
                return await req.recv_json()
            return {"status": "error", "msg": "sem resposta do teleop"}
        finally:
            req.close(0)

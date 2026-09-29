"""Visão do robô: assina o JPEG publicado pelo servidor de imagens (ZMQ) e repassa ao
navegador como MJPEG, sem decodificar. Funciona com a simulação (127.0.0.1) e com
o robô real (IP do robô)."""
import asyncio
import time

import zmq
import zmq.asyncio
from aiohttp import web

_ctx = zmq.asyncio.Context.instance()


async def request_cam_config(host: str, port: int, timeout: float = 1.0):
    """GET_DATA no REP do servidor de imagens (porta 60000). None se não responder."""
    req = _ctx.socket(zmq.REQ)
    req.setsockopt(zmq.LINGER, 0)
    req.connect(f"tcp://{host}:{port}")
    try:
        await req.send(b"GET_DATA")
        if await req.poll(int(timeout * 1000)):
            return await req.recv_json()
        return None
    except Exception:
        return None
    finally:
        req.close(0)


class FrameSource:
    """Um assinante ZMQ por endereço; guarda só o último quadro."""

    def __init__(self, host: str, port: int):
        self.host, self.port = host, port
        self.frame = None
        self.seq = 0
        self.last_ts = 0.0
        self.clients = 0
        self._cond = asyncio.Condition()
        self._task = asyncio.create_task(self._loop())

    async def _loop(self):
        sub = _ctx.socket(zmq.SUB)
        sub.setsockopt(zmq.RCVHWM, 1)
        sub.setsockopt(zmq.CONFLATE, 1)
        sub.setsockopt_string(zmq.SUBSCRIBE, "")
        sub.connect(f"tcp://{self.host}:{self.port}")
        try:
            while True:
                if await sub.poll(1000):
                    data = await sub.recv()
                    async with self._cond:
                        self.frame = data
                        self.seq += 1
                        self.last_ts = time.time()
                        self._cond.notify_all()
        except asyncio.CancelledError:
            pass
        finally:
            sub.close(0)

    @property
    def live(self) -> bool:
        return time.time() - self.last_ts < 2.0

    async def next_frame(self, after_seq: int, timeout: float = 2.0):
        async with self._cond:
            try:
                await asyncio.wait_for(self._cond.wait_for(lambda: self.seq > after_seq), timeout)
            except asyncio.TimeoutError:
                return None, after_seq
            return self.frame, self.seq

    def close(self):
        self._task.cancel()


_sources = {}
_shutting_down = False


def shutdown():
    """Encerra os assinantes e faz os streams MJPEG abertos terminarem."""
    global _shutting_down
    _shutting_down = True
    for src in _sources.values():
        src.close()


def get_source(host: str, port: int) -> FrameSource:
    key = (host, port)
    if key not in _sources:
        _sources[key] = FrameSource(host, port)
    return _sources[key]


def source_status(host: str, port: int) -> dict:
    src = _sources.get((host, port))
    return {"live": bool(src and src.live), "frames": src.seq if src else 0, "clients": src.clients if src else 0}


async def mjpeg_handler(request: web.Request):
    host = request.query.get("host", "127.0.0.1")
    port = int(request.query.get("port", "55555"))
    max_fps = float(request.query.get("fps", "30"))
    src = get_source(host, port)
    resp = web.StreamResponse(headers={
        "Content-Type": "multipart/x-mixed-replace; boundary=frame",
        "Cache-Control": "no-cache, no-store", "Pragma": "no-cache",
    })
    await resp.prepare(request)
    src.clients += 1
    seq = 0
    min_dt = 1.0 / max_fps
    last = 0.0
    try:
        while not _shutting_down:
            frame, seq = await src.next_frame(seq)
            if frame is None:
                continue
            now = time.time()
            if now - last < min_dt:
                await asyncio.sleep(min_dt - (now - last))
            last = time.time()
            await resp.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                             + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n")
    except ConnectionResetError:
        pass
    finally:
        src.clients -= 1
    return resp

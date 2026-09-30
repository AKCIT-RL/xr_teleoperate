"""Interface de teleoperação — servidor.

Uso (env tv_unity_svr):
    python gui/app.py            # abre em http://localhost:8080

Gerencia a simulação, a ponte WebRTC e o teleop; repassa logs, estado e a visão
do robô para a página em gui/static/.
"""
import asyncio
import json
import sys
import time
from pathlib import Path

from aiohttp import web, WSMsgType

sys.path.insert(0, str(Path(__file__).resolve().parent))

import checks                                            # noqa: E402
import commands                                          # noqa: E402
import recordings                                        # noqa: E402
import video                                             # noqa: E402
from config import (STATIC_DIR, GUI_HOST, GUI_PORT, PORT_IMAGES, PORT_CAM_CONFIG,
                    DEFAULT_ROBOT_IP)                    # noqa: E402
from procman import ManagedProcess                       # noqa: E402
from teleop_ipc import TeleopIPC                         # noqa: E402

LABELS = {"sim": "Simulação", "bridge": "Ponte WebRTC", "teleop": "Teleop"}
READY_TIMEOUT = {"sim": 900.0, "bridge": 60.0, "teleop": 180.0}


class App:
    def __init__(self):
        self.clients = set()
        self.procs = {n: ManagedProcess(n, LABELS[n], self.broadcast) for n in LABELS}
        self.ipc = TeleopIPC()
        self.session = {"active": False, "mode": None, "base": None, "step": None, "error": None,
                        "replay": None}
        self._session_task = None

    # ---------- websocket ----------
    async def broadcast(self, msg: dict):
        if not self.clients:
            return
        data = json.dumps(msg)
        for ws in list(self.clients):
            try:
                await ws.send_str(data)
            except (ConnectionResetError, RuntimeError):
                self.clients.discard(ws)

    def state(self) -> dict:
        base = self.session.get("base") or {}
        img_host = base.get("robot_ip", DEFAULT_ROBOT_IP) if base.get("mode") == "real" else "127.0.0.1"
        return {
            "type": "state", "time": time.time(),
            "procs": {n: p.info() for n, p in self.procs.items()},
            "teleop_ipc": self.ipc.info(),
            "session": self.session,
            "video": {"host": img_host, "port": PORT_IMAGES, **video.source_status(img_host, PORT_IMAGES)},
        }

    async def ws_handler(self, request):
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        self.clients.add(ws)
        await ws.send_str(json.dumps(self.state()))
        for name, p in self.procs.items():
            await ws.send_str(json.dumps({"type": "logs", "proc": name, "entries": p.logs.snapshot()}))
        try:
            async for msg in ws:
                if msg.type == WSMsgType.ERROR:
                    break
        finally:
            self.clients.discard(ws)
        return ws

    async def state_loop(self):
        while True:
            await asyncio.sleep(0.5)
            await self.broadcast(self.state())

    # ---------- processos ----------
    def any_running(self) -> bool:
        return any(p.running for p in self.procs.values())

    def managed_pids(self) -> set:
        return {p.proc.pid for p in self.procs.values() if p.running}

    async def start_proc(self, name: str, base: dict, overrides: dict, extra_args=None):
        values = commands.resolve(base, overrides)
        spec = commands.launch_spec(name, values[name], extra_args)
        await self.procs[name].start(spec)

    async def run_session(self, base: dict, overrides: dict):
        order = commands.active_processes(base)
        self.session.update(active=True, mode=base.get("mode"), base=base, error=None, replay=None)
        try:
            for name in order:
                self.session["step"] = name
                p = self.procs[name]
                if not p.running:
                    await self.start_proc(name, base, overrides)
                if not await p.wait_ready(READY_TIMEOUT[name]):
                    raise RuntimeError(f"{LABELS[name]} não ficou pronto (veja o log)")
            self.session["step"] = "done"
        except asyncio.CancelledError:
            self.session["step"] = None
            raise
        except Exception as e:
            self.session["error"] = str(e)
            self.session["step"] = "failed"

    async def stop_all(self):
        if self._session_task and not self._session_task.done():
            self._session_task.cancel()
        # ordem inversa: teleop -> ponte -> simulação
        for name in ("teleop", "bridge", "sim"):
            await self.procs[name].stop()
        self.session.update(active=False, step=None, replay=None)

    # ---------- rotas ----------
    async def index(self, request):
        return web.FileResponse(STATIC_DIR / "index.html")

    async def api_schema(self, request):
        return web.json_response({
            "schema": commands.schema_json(),
            "presets": commands.TASK_PRESETS,
            "default_base": commands.DEFAULT_BASE,
            "tasks": commands.list_sim_tasks(),
            "interfaces": await checks.interfaces(),
        })

    async def api_preview(self, request):
        body = await request.json()
        base, overrides = body.get("base", {}), body.get("overrides", {})
        values = commands.resolve(base, overrides)
        return web.json_response({
            "values": values,
            "active": commands.active_processes(base),
            "commands": {n: commands.launch_spec(n, values[n])["short"] for n in values},
            "warnings": commands.validate(base, values),
        })

    async def api_checks(self, request):
        body = await request.json()
        base = body.get("base", {})
        items = await checks.local_checks(self.managed_pids(), self.any_running())
        if base.get("mode") == "real":
            items += await checks.robot_checks(base.get("robot_ip") or DEFAULT_ROBOT_IP, base.get("robot_iface") or "")
        return web.json_response({"items": items, "interfaces": await checks.interfaces()})

    async def api_kill_stale(self, request):
        body = await request.json()
        checks.kill_stale([int(p) for p in body.get("pids", [])])
        return web.json_response({"ok": True})

    async def api_session_start(self, request):
        body = await request.json()
        if self._session_task and not self._session_task.done():
            return web.json_response({"ok": False, "msg": "sessão já em andamento"}, status=409)
        self._session_task = asyncio.create_task(self.run_session(body.get("base", {}), body.get("overrides", {})))
        return web.json_response({"ok": True})

    async def api_session_stop(self, request):
        await self.stop_all()
        return web.json_response({"ok": True})

    async def api_proc_action(self, request):
        name, action = request.match_info["name"], request.match_info["action"]
        if name not in self.procs:
            raise web.HTTPNotFound()
        body = await request.json() if request.can_read_body else {}
        p = self.procs[name]
        try:
            if action == "stop":
                await p.stop()
            elif action in ("start", "restart"):
                if action == "restart":
                    await p.stop()
                base = body.get("base") or self.session.get("base") or {}
                await self.start_proc(name, base, body.get("overrides", {}))
                self.session.update(active=True, base=base, mode=base.get("mode"))
            else:
                raise web.HTTPBadRequest()
        except RuntimeError as e:
            return web.json_response({"ok": False, "msg": str(e)}, status=409)
        return web.json_response({"ok": True})

    async def api_state(self, request):
        return web.json_response(self.state())

    async def api_logs(self, request):
        name = request.match_info["name"]
        if name not in self.procs:
            raise web.HTTPNotFound()
        level = request.query.get("min", "debug")
        order = ["debug", "info", "warn", "error"]
        entries = [e for e in self.procs[name].logs.snapshot() if order.index(e["level"]) >= order.index(level)]
        return web.json_response({"entries": entries[-int(request.query.get("n", "200")):]})

    async def api_usb_status(self, request):
        return web.json_response(await checks.usb_network_status())

    async def api_usb_enable(self, request):
        return web.json_response(await checks.usb_network_enable())

    async def api_teleop_cmd(self, request):
        return web.json_response(await self.ipc.send(request.match_info["cmd"]))

    async def api_cam_config(self, request):
        host = request.query.get("host", "127.0.0.1")
        cfg = await video.request_cam_config(host, PORT_CAM_CONFIG)
        return web.json_response({"config": cfg})

    # gravações
    async def api_recordings(self, request):
        return web.json_response({"episodes": await asyncio.to_thread(recordings.list_episodes)})

    async def api_recording_series(self, request):
        t, e = request.match_info["task"], request.match_info["episode"]
        try:
            return web.json_response(await asyncio.to_thread(recordings.load_series, t, e))
        except FileNotFoundError:
            raise web.HTTPNotFound()

    async def api_recording_frame(self, request):
        t, e = request.match_info["task"], request.match_info["episode"]
        try:
            path = recordings.frame_image(t, e, int(request.match_info["index"]), int(request.match_info["cam"]))
        except (FileNotFoundError, ValueError):
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={"Cache-Control": "max-age=3600"})

    async def api_replay(self, request):
        body = await request.json()
        if self.any_running():
            return web.json_response({"ok": False, "msg": "Encerre a sessão atual antes do replay."}, status=409)
        try:
            ep_dir = recordings.safe_episode_dir(body["task"], body["episode"])
            data = await asyncio.to_thread(recordings.load_series, body["task"], body["episode"])
        except (KeyError, FileNotFoundError):
            raise web.HTTPNotFound()
        task_name = data["meta"].get("task_name")
        preset = next((k for k, v in commands.TASK_PRESETS.items() if v["task"] == task_name), "tres_mesas")
        base = {"mode": "sim", "preset": preset, "headless": not body.get("window", True)}
        overrides = {"sim": {"task": task_name} if task_name else {}}
        extra = ["--replay_data", "--file_path", str(ep_dir), "--step_hz", "30"]
        await self.start_proc("sim", base, overrides, extra_args=extra)
        self.session.update(active=True, mode="replay", base=base, error=None, step="replay",
                            replay={"task": body["task"], "episode": body["episode"],
                                    "duration": data["meta"]["duration"], "started": time.time()})
        return web.json_response({"ok": True})


async def on_startup(app):
    core = app["core"]
    core.ipc.start()
    app["state_task"] = asyncio.create_task(core.state_loop())


async def on_shutdown(app):
    core = app["core"]
    app["state_task"].cancel()
    video.shutdown()                     # streams MJPEG abertos terminam sozinhos
    if core.ipc._task:
        core.ipc._task.cancel()
    await core.stop_all()
    for ws in list(core.clients):
        await ws.close()


@web.middleware
async def no_cache_static(request, handler):
    """Página e arquivos estáticos sempre revalidados: evita o navegador rodar um app.js antigo."""
    resp = await handler(request)
    if request.path == "/" or request.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


def make_app() -> web.Application:
    core = App()
    app = web.Application(client_max_size=4 * 1024 * 1024, middlewares=[no_cache_static])
    app["core"] = core
    r = app.router
    r.add_get("/", core.index)
    r.add_static("/static", STATIC_DIR)
    r.add_get("/ws", core.ws_handler)
    r.add_get("/video.mjpg", video.mjpeg_handler)
    r.add_get("/api/schema", core.api_schema)
    r.add_post("/api/preview", core.api_preview)
    r.add_post("/api/checks", core.api_checks)
    r.add_post("/api/kill-stale", core.api_kill_stale)
    r.add_post("/api/session/start", core.api_session_start)
    r.add_post("/api/session/stop", core.api_session_stop)
    r.add_post("/api/process/{name}/{action}", core.api_proc_action)
    r.add_get("/api/state", core.api_state)
    r.add_get("/api/logs/{name}", core.api_logs)
    r.add_post("/api/teleop/{cmd}", core.api_teleop_cmd)
    r.add_get("/api/usb-network", core.api_usb_status)
    r.add_post("/api/usb-network/enable", core.api_usb_enable)
    r.add_get("/api/cam-config", core.api_cam_config)
    r.add_get("/api/recordings", core.api_recordings)
    r.add_get("/api/recordings/{task}/{episode}/series", core.api_recording_series)
    r.add_get("/api/recordings/{task}/{episode}/frame/{index}/{cam}.jpg", core.api_recording_frame)
    r.add_post("/api/replay", core.api_replay)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app


if __name__ == "__main__":
    print(f"Interface de teleoperação em http://localhost:{GUI_PORT}")
    # shutdown_timeout curto: os processos já foram encerrados no on_shutdown
    web.run_app(make_app(), host=GUI_HOST, port=GUI_PORT, print=None,
                handle_signals=True, shutdown_timeout=5)

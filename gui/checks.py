"""Verificações antes de iniciar: interfaces de rede, portas, GPU, processos antigos, robô."""
import asyncio
import json
import os
import socket

import psutil

from config import PORT_SIGNALING, PORT_BRIDGE, PORT_IMAGES, PORT_CAM_CONFIG
from video import request_cam_config

SCRIPTS = ("sim_main.py", "python_webrtc.py", "teleop_hand_and_arm.py")


async def _run(*cmd, timeout=3.0):
    try:
        p = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                 stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(p.communicate(), timeout)
        return p.returncode, out.decode(errors="replace")
    except (asyncio.TimeoutError, FileNotFoundError):
        return -1, ""


async def interfaces() -> list:
    """[{name, ip, prefix}] das interfaces IPv4 ativas (menos loopback)."""
    rc, out = await _run("ip", "-j", "-4", "addr")
    result = []
    if rc == 0:
        for dev in json.loads(out or "[]"):
            if dev.get("ifname") == "lo" or "UP" not in dev.get("flags", []):
                continue
            for a in dev.get("addr_info", []):
                result.append({"name": dev["ifname"], "ip": a["local"], "prefix": a.get("prefixlen")})
    return result


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


async def gpu() -> dict:
    rc, out = await _run("nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits")
    if rc != 0 or not out.strip():
        return {"ok": None, "text": "nvidia-smi indisponível"}
    used, total = [float(x) for x in out.strip().splitlines()[0].split(",")]
    return {"ok": used / total < 0.5, "text": f"{used/1024:.1f} / {total/1024:.1f} GB"}


def stale_processes(managed_pids: set) -> list:
    found = []
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmd = " ".join(p.info["cmdline"] or [])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if p.info["pid"] in managed_pids or "bash -c" in cmd:
            continue
        for s in SCRIPTS:
            if s in cmd and "python" in cmd:
                found.append({"pid": p.info["pid"], "script": s})
    return found


def kill_stale(pids: list):
    import signal
    for pid in pids:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass


async def local_checks(managed_pids: set, any_running: bool) -> list:
    items = []
    if not any_running:
        busy = [p for p in (PORT_SIGNALING, PORT_BRIDGE, PORT_IMAGES, PORT_CAM_CONFIG) if not port_free(p)]
        items.append({"key": "ports", "ok": not busy,
                      "text": "Portas 8765 · 9876 · 55555 · 60000 livres" if not busy
                      else f"Portas em uso: {', '.join(map(str, busy))}"})
    g = await gpu()
    items.append({"key": "gpu", "ok": g["ok"], "text": f"GPU {g['text']}"})
    stale = stale_processes(managed_pids)
    items.append({"key": "stale", "ok": not stale,
                  "text": "Nenhum processo antigo rodando" if not stale
                  else "Processos antigos: " + ", ".join(f"{s['script']} ({s['pid']})" for s in stale),
                  "pids": [s["pid"] for s in stale]})
    return items


async def robot_checks(robot_ip: str, iface: str) -> list:
    items = []
    cmd = ["ping", "-c", "1", "-W", "1"] + (["-I", iface] if iface else []) + [robot_ip]
    rc, out = await _run(*cmd, timeout=3.0)
    items.append({"key": "ping", "ok": rc == 0,
                  "text": f"ping {robot_ip}" + (f" pela {iface}" if iface else "") + (" ok" if rc == 0 else " sem resposta")})
    cfg = await request_cam_config(robot_ip, PORT_CAM_CONFIG, timeout=1.5)
    if cfg is None:
        items.append({"key": "imgserver", "ok": False,
                      "text": "Servidor de imagens não responde na :60000 (é o teleimager?)"})
    else:
        head = cfg.get("head_camera", {})
        ok = bool(head.get("enable_zmq"))
        items.append({"key": "imgserver", "ok": ok,
                      "text": f"Servidor de imagens responde · cabeça {head.get('image_shape')} "
                              f"{'binocular' if head.get('binocular') else 'mono'} · ZMQ "
                              + ("habilitado" if ok else "DESABILITADO")})
    return items

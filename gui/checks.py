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


def _driver(ifname: str) -> str:
    try:
        return os.path.basename(os.readlink(f"/sys/class/net/{ifname}/device/driver"))
    except OSError:
        return ""


async def interfaces() -> list:
    """[{name, ip, prefix, usb}] das interfaces IPv4 ativas (menos loopback).
    usb=True: placa de rede do Quest pelo cabo (modo NCM, driver cdc_ncm)."""
    rc, out = await _run("ip", "-j", "-4", "addr")
    result = []
    if rc == 0:
        for dev in json.loads(out or "[]"):
            if dev.get("ifname") == "lo" or "UP" not in dev.get("flags", []):
                continue
            for a in dev.get("addr_info", []):
                result.append({"name": dev["ifname"], "ip": a["local"], "prefix": a.get("prefixlen"),
                               "usb": _driver(dev["ifname"]) == "cdc_ncm"})
    return result


# ---------- rede pelo cabo USB (Quest em modo NCM) ----------
# No Quest: `adb shell svc usb setFunctions ncm` vira a porta USB numa placa de rede
# (usb0, cliente DHCP). No PC: o perfil do NetworkManager `quest-usb`
# (match.driver cdc_ncm, ipv4.method shared) dá 10.42.0.1 ao PC e entrega IP ao Quest.
NM_PROFILE = "quest-usb"
NM_PROFILE_CMD = ("nmcli connection add type ethernet con-name quest-usb match.driver cdc_ncm "
                  "ipv4.method shared ipv6.method disabled connection.autoconnect-priority 10")


async def adb_state() -> str:
    rc, out = await _run("adb", "devices", timeout=4.0)
    if rc != 0:
        return "sem adb"
    rows = [l.split() for l in out.splitlines()[1:] if l.strip()]
    if not rows:
        return "desconectado"
    return rows[0][1] if len(rows[0]) > 1 else "desconhecido"   # device | unauthorized | offline


async def usb_network_status() -> dict:
    ncm = [n for n in os.listdir("/sys/class/net") if _driver(n) == "cdc_ncm"]
    st = {"iface": None, "pc_ip": None, "quest_ip": None, "active": False,
          "adb": await adb_state(), "profile": False, "profile_cmd": NM_PROFILE_CMD}
    rc, out = await _run("nmcli", "-t", "-f", "NAME", "connection", "show")
    st["profile"] = rc == 0 and NM_PROFILE in out.splitlines()
    if not ncm:
        return st
    iface = ncm[0]
    st["iface"] = iface
    rc, out = await _run("ip", "-j", "-4", "addr", "show", "dev", iface)
    for dev in json.loads(out or "[]") if rc == 0 else []:
        for a in dev.get("addr_info", []):
            st["pc_ip"] = a["local"]
    if not st["pc_ip"]:
        return st
    # o Quest aparece na tabela de vizinhos depois de pegar IP; confirma com um ping
    rc, out = await _run("ip", "-j", "neigh", "show", "dev", iface)
    candidates = [n["dst"] for n in json.loads(out or "[]") if rc == 0
                  and ":" not in n.get("dst", "") and n.get("lladdr")
                  and not set(n.get("state", [])) & {"FAILED", "INCOMPLETE"}]
    for ip in candidates:
        prc, _ = await _run("ping", "-c", "1", "-W", "1", ip, timeout=2.0)
        if prc == 0:
            st["quest_ip"] = ip
            st["active"] = True
            break
    return st


async def usb_network_enable() -> dict:
    """Liga o NCM no Quest e espera ele pegar IP. Se o DHCP do Quest desistir (acontece
    quando o PC ainda não estava servindo), repete o comando uma vez."""
    adb = await adb_state()
    if adb != "device":
        msg = {"desconectado": "Quest não encontrado pelo adb: conecte o cabo USB.",
               "unauthorized": "Autorize a depuração USB no óculos e tente de novo."}.get(adb, f"adb: {adb}")
        return {"ok": False, "msg": msg, "status": await usb_network_status()}
    if not (await usb_network_status())["profile"]:
        return {"ok": False, "msg": "Falta o perfil de rede do PC. Rode uma vez no terminal: " + NM_PROFILE_CMD,
                "status": await usb_network_status()}
    retried = False
    rc, out = await _run("adb", "shell", "svc", "usb", "setFunctions", "ncm", timeout=10.0)
    t0 = asyncio.get_running_loop().time()
    while asyncio.get_running_loop().time() - t0 < 30.0:
        await asyncio.sleep(2.0)
        st = await usb_network_status()
        if st["active"]:
            return {"ok": True, "msg": f"Cabo ativo: PC {st['pc_ip']} · Quest {st['quest_ip']}", "status": st}
        if not retried and st["pc_ip"] and asyncio.get_running_loop().time() - t0 > 12.0:
            retried = True
            if await adb_state() == "device":
                await _run("adb", "shell", "svc", "usb", "setFunctions", "ncm", timeout=10.0)
    st = await usb_network_status()
    if st["iface"] and not st["pc_ip"]:
        msg = "A placa do cabo apareceu, mas o PC não está servindo IP nela (perfil quest-usb inativo?)."
    elif st["iface"]:
        msg = ("O Quest não pegou IP. Se o óculos pedir, autorize a depuração USB e clique de novo "
               "(a troca de modo USB pede autorização outra vez).")
    else:
        msg = "A placa de rede do Quest não apareceu no PC. Verifique o cabo e tente de novo."
    return {"ok": False, "msg": msg, "status": st}


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

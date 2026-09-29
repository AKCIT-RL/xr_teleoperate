"""Iniciar, acompanhar e encerrar os processos (simulação, ponte, teleop).

Cada processo roda num grupo de processos próprio (start_new_session), então o
encerramento alcança também os filhos (o Isaac cria vários). Encerramento em
etapas: SIGINT (como Ctrl+C) -> SIGTERM -> SIGKILL.
"""
import asyncio
import os
import re
import signal
import time

from config import LOG_BUFFER_LINES, STOP_GRACE_S
from logfilter import LogBuffer, clean

# Marcos detectados nos logs: nome -> regex. "ready" define o estado "pronto".
MARKERS = {
    "sim": {
        "ready": r"start controller success",
        "env_ok": r"create environment success",
        "replay": r"data_idx: \d+",
        "fail": r"Failed to create|Error executing job|Traceback",
    },
    "bridge": {
        "ready": r"Servidor rodando em",
        "quest_signaling": r"Cliente conectado",
        # o aiortc não dispara "open" para canais criados pelo Unity (já chegam abertos),
        # então "DataChannel criado" conta como conectado; as poses no [stats] confirmam
        "quest_connected": r"DataChannel criado|DataChannel OPEN",
        "quest_gone": r"PeerConnection fechado|Cliente desconectou",
        "teleop_link": r"Forwarder connected",
        "teleop_link_down": r"Forwarder disconnected",
        "stats": r"\[stats\]",
    },
    "teleop": {
        "ready": r"Press \[r\] to start syncing|start syncing the robot",
        "fail": r"Traceback|ValueError",
    },
}


class ManagedProcess:
    def __init__(self, name: str, label: str, broadcast):
        self.name = name
        self.label = label
        self.broadcast = broadcast          # async fn(dict)
        self.logs = LogBuffer(name, LOG_BUFFER_LINES)
        self.proc = None
        self.state = "parado"               # parado | iniciando | pronto | parando | erro
        self.started_at = None
        self.exit_code = None
        self.command = ""
        self.flags = {}                     # marcos vistos (quest_connected, teleop_link...)
        self.stats = ""
        self._reader = None
        self._stopping = False
        self._markers = {k: re.compile(v) for k, v in MARKERS.get(name, {}).items()}

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    def info(self) -> dict:
        return {
            "name": self.name, "label": self.label, "state": self.state,
            "pid": self.proc.pid if self.running else None,
            "uptime": (time.time() - self.started_at) if self.running and self.started_at else 0,
            "exit_code": self.exit_code, "command": self.command,
            "flags": self.flags, "stats": self.stats,
            "warn": self.logs.counts["warn"], "error": self.logs.counts["error"],
        }

    async def _emit_state(self):
        await self.broadcast({"type": "proc", "proc": self.info()})

    async def _log(self, text: str):
        entry, new = self.logs.add(text)
        await self.broadcast({"type": "log", "proc": self.name, "entry": entry, "new": new})

    async def start(self, spec: dict):
        if self.running:
            raise RuntimeError(f"{self.label} já está rodando")
        self.logs.clear()
        self.flags = {}
        self.stats = ""
        self.exit_code = None
        self._stopping = False
        self.command = spec["display"]
        # COLUMNS largo: o logging do teleop (rich) quebra linhas na largura do "terminal"
        env = dict(os.environ, PYTHONUNBUFFERED="1", COLUMNS="400")
        await self._log(f"$ {spec['short']}")
        self.proc = await asyncio.create_subprocess_exec(
            *spec["argv"], cwd=spec["cwd"], env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.DEVNULL, start_new_session=True,
        )
        self.started_at = time.time()
        self.state = "iniciando"
        await self._emit_state()
        self._reader = asyncio.create_task(self._read_output())

    async def _read_output(self):
        buf = b""
        stream = self.proc.stdout
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                break
            buf += chunk
            # \r também separa linhas (barras de progresso)
            parts = re.split(rb"\r\n|\n|\r", buf)
            buf = parts.pop()
            for raw in parts:
                await self._handle_line(raw.decode("utf-8", errors="replace"))
        if buf:
            await self._handle_line(buf.decode("utf-8", errors="replace"))
        rc = await self.proc.wait()
        self.exit_code = rc
        # filhos que sobraram no grupo (ex.: o processo saiu sozinho sem limpar)
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        self.state = "parado" if (self._stopping or rc == 0) else "erro"
        await self._log(f"[processo encerrado, código {rc}]")
        await self._emit_state()

    async def _handle_line(self, raw: str):
        text = clean(raw)
        if not text.strip():
            return
        indent = len(text) - len(text.lstrip())
        last = self.logs.entries[-1] if self.logs.entries else None
        if indent >= 2 and last is not None and time.time() - last["ts"] < 1.0:
            # continuação: traceback / quebra de linha do rich
            entry = self.logs.extend_last(text.strip(), " " if indent >= 20 else "\n")
            if entry is not None:
                await self.broadcast({"type": "log", "proc": self.name, "entry": entry, "new": False})
                return
        changed = False
        for name, rx in self._markers.items():
            if rx.search(text):
                if name == "stats":
                    self.stats = text.split("[stats]", 1)[1].strip()
                    m = re.search(r"poses (\d+)/s", self.stats)
                    if m and int(m.group(1)) > 0:
                        self.flags["quest_connected"] = time.time()
                        self.flags["quest_signaling"] = time.time()
                    changed = True
                    continue
                if name == "ready" and self.state == "iniciando":
                    self.state = "pronto"
                elif name == "quest_gone":
                    self.flags.pop("quest_connected", None)
                    self.flags.pop("quest_signaling", None)
                elif name == "teleop_link_down":
                    self.flags.pop("teleop_link", None)
                else:
                    self.flags[name] = time.time()
                changed = True
        await self._log(text)
        if changed:
            await self._emit_state()

    def _signal_group(self, sig):
        try:
            os.killpg(os.getpgid(self.proc.pid), sig)
        except ProcessLookupError:
            pass

    async def stop(self):
        if not self.running:
            return
        self._stopping = True
        self.state = "parando"
        await self._emit_state()
        grace = STOP_GRACE_S.get(self.name, 10.0)
        for sig, wait in ((signal.SIGINT, grace), (signal.SIGTERM, 5.0), (signal.SIGKILL, 5.0)):
            if not self.running:
                break
            if sig != signal.SIGINT:
                await self._log(f"[não encerrou a tempo; enviando {sig.name}]")
            self._signal_group(sig)
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=wait)
            except asyncio.TimeoutError:
                continue
        # filhos que escaparam do grupo principal (ex.: se o processo trocou de grupo)
        if self._reader:
            try:
                await asyncio.wait_for(self._reader, timeout=5.0)
            except asyncio.TimeoutError:
                pass

    async def wait_ready(self, timeout: float) -> bool:
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.state == "pronto":
                return True
            if not self.running:
                return False
            await asyncio.sleep(0.3)
        return False

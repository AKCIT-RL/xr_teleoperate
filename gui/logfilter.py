"""Classificação e agrupamento das linhas de log dos processos.

- classify(): nível (debug/info/warn/error). "debug" = ruído, só aparece com "Detalhado".
- LogBuffer: guarda as últimas N entradas e agrupa linhas repetidas consecutivas
  (mesmo texto a menos dos números) em uma só, com contador.
"""
import re
import time
from collections import deque

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

ERROR = re.compile(r"Traceback|\bError\b|ERROR|Exception|❌|Failed|failed|FATAL|Segmentation fault")
WARN = re.compile(r"WARNING|Warning|\bwarn|⚠|WARN")
HARD_ERROR = re.compile(r"Traceback|Exception|FATAL|Segmentation fault")


def _is_error(text: str) -> bool:
    # "Warning: ... failed" é aviso, não erro
    return bool(ERROR.search(text)) and (not WARN.search(text) or bool(HARD_ERROR.search(text)))

# A simulação (Isaac) imprime centenas de linhas: para ela só os marcos abaixo aparecem
# como info; o resto vira "debug" (visível com "Detalhado").
SIM_MILESTONES = re.compile(
    r"robot control system started|^Task:|create environment|create image server|create dds|"
    r"create action provider|create controller|start controller|Running without GUI|"
    r"left-click on the Sim window|overall average frequency|data_idx|replay|args_cli\.task|"
    r"received signal|stopping controller|Cleaning up"
)
# Avisos conhecidos e inofensivos do Isaac/IsaacLab
SIM_BENIGN = re.compile(
    r"\[Warning\] \[(omni|carb|gpu\.foundation|rtx|pxr|omni\.)|will be deprecated|is deprecated|"
    r"Fabric mode with Warp|enable_external_forces_every_iteration|"
    r"Failed to set process group"      # esperado: a interface já cria o grupo de processos
)

# Linhas que não ajudam na operação (só com "Detalhado")
NOISE = {
    "sim": [],
    "bridge": [
        r"📥 Unity → Python", r"📤 Python → Unity", r"📦 Python → Unity queued", r"🧊 ICE aplicado",
        r"⏳ ICE armazenado", r"\[ICE OVERRIDE\]", r"^INFO:aioice", r"^INFO:aiortc", r"Hello from Python",
    ],
    "teleop": [
        r"📳 Unity bridge feedback", r"^-{10,}", r"main process sleep", r"^ik:",
    ],
}
_NOISE = {k: [re.compile(p) for p in v] for k, v in NOISE.items()}

DIGITS = re.compile(r"\d+([.,]\d+)?")

# Formatos com nível explícito:
#   logging_mp (rich):  "21:20:27:168020 INFO     texto      arquivo.py:144"
#   logging padrão:     "WARNING:root:texto"
RICH = re.compile(r"^\d{2}:\d{2}:\d{2}:\d+\s+(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+(.*?)(\s{2,}\S+\.py:\d+)?$")
STDLOG = re.compile(r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL):[\w.]+:(.*)$")
LEVELS = {"DEBUG": "debug", "INFO": "info", "WARNING": "warn", "ERROR": "error", "CRITICAL": "error"}

# Mensagens que o próprio processo marca como aviso/erro mas são esperadas
DEMOTE = {
    "teleop": re.compile(r"IMPORTANT: Please keep your distance|already exist, now self\.episode_id"),
    "bridge": re.compile(r"Forwarder disconnected"),
}


def clean(line: str) -> str:
    return ANSI.sub("", line).rstrip()


def parse(text: str):
    """(nível explícito ou None, texto sem prefixo de log)."""
    m = RICH.match(text)
    if m:
        return LEVELS[m.group(1)], m.group(2).strip()
    m = STDLOG.match(text)
    if m:
        return LEVELS[m.group(1)], m.group(2).strip()
    return None, text


GUI_OWN = re.compile(r"^\$ |^\[(processo encerrado|não encerrou)")


def classify(proc: str, text: str, hint: str = None) -> str:
    """hint = nível que veio na própria linha (INFO/WARNING...), quando existe."""
    if GUI_OWN.search(text):          # linhas escritas pela própria interface
        return "warn" if text.startswith("[não encerrou") else "info"
    demote = DEMOTE.get(proc)
    if demote and demote.search(text):
        return "info"
    if proc == "sim":
        if SIM_BENIGN.search(text):
            return "debug"
        if hint in ("warn", "error"):
            return hint
        if _is_error(text):
            return "error"
        if WARN.search(text):
            return "warn"
        return "info" if SIM_MILESTONES.search(text) else "debug"
    if hint in ("warn", "error", "debug"):
        return hint
    if hint is None:
        if _is_error(text):
            return "error"
        if WARN.search(text):
            return "warn"
    for rx in _NOISE.get(proc, []):
        if rx.search(text):
            return "debug"
    return "info"


class LogBuffer:
    def __init__(self, proc: str, maxlen: int):
        self.proc = proc
        self.entries = deque(maxlen=maxlen)
        self._next_id = 1
        self._last_key = None
        self.counts = {"warn": 0, "error": 0}

    def extend_last(self, text: str, sep: str):
        """Linha de continuação (traceback, bloco indentado): anexa à última entrada."""
        if not self.entries:
            return None
        e = self.entries[-1]
        e["text"] = e["text"] + sep + text
        if e["level"] != "error" and ERROR.search(text) and self.proc != "sim":
            e["level"] = "error"
            self.counts["error"] += 1
        self._last_key = None
        return e

    def add(self, text: str):
        """Retorna (entrada, nova?)."""
        hint, text = parse(text)
        level = classify(self.proc, text, hint)
        key = DIGITS.sub("#", text)
        now = time.time()
        if self.entries and key == self._last_key:
            e = self.entries[-1]
            e["count"] += 1
            e["text"] = text
            e["ts"] = now
            return e, False
        e = {"id": self._next_id, "ts": now, "level": level, "text": text, "count": 1}
        self._next_id += 1
        self._last_key = key
        self.entries.append(e)
        if level in self.counts:
            self.counts[level] += 1
        return e, True

    def snapshot(self):
        return list(self.entries)

    def clear(self):
        self.entries.clear()
        self._last_key = None
        self.counts = {"warn": 0, "error": 0}

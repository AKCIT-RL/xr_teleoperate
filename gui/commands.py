"""Parâmetros de cada processo e montagem das linhas de comando.

O front manda duas coisas:
  base      -> escolhas da tela (modo, tarefa, rede, gravação...)
  overrides -> valores alterados à mão no "Avançado", por processo

derive(base) calcula o valor de TODOS os parâmetros a partir da base;
overrides são aplicados por cima; build_argv() gera a linha de comando.
"""
import re
import shlex
from dataclasses import dataclass, asdict
from typing import Optional

from config import (CONDA_ROOT, SIM_ENV, TELEOP_ENV, SIM_REPO, REPO, TELEOP_DIR,
                    PORT_SIGNALING, PORT_BRIDGE, DEFAULT_ROBOT_IP)


@dataclass
class Param:
    key: str
    flag: str
    kind: str                  # bool | str | int | float | select
    label: str
    options: Optional[list] = None
    help: str = ""
    locked: bool = False       # valor imposto pela interface (não editável)


SIM_PARAMS = [
    Param("task", "--task", "str", "Tarefa (gym id)"),
    Param("robot_type", "--robot_type", "str", "Tipo de robô"),
    Param("device", "--device", "select", "Dispositivo", ["cpu", "cuda"]),
    Param("enable_cameras", "--enable_cameras", "bool", "Câmeras", locked=True,
          help="necessário para a visão do robô"),
    Param("headless", "--headless", "bool", "Headless (sem janela)"),
    Param("enable_dex1_dds", "--enable_dex1_dds", "bool", "Garra Dex1 (DDS)"),
    Param("enable_dex3_dds", "--enable_dex3_dds", "bool", "Mão Dex3 (DDS)"),
    Param("enable_inspire_dds", "--enable_inspire_dds", "bool", "Mão Inspire (DDS)"),
    Param("step_hz", "--step_hz", "int", "Frequência do laço (Hz)"),
    Param("physics_dt", "--physics_dt", "float", "Passo da física (s)"),
    Param("extra", "", "str", "Argumentos extras"),
]

BRIDGE_PARAMS = [
    Param("host", "--host", "str", "Host da sinalização"),
    Param("port", "--port", "int", "Porta da sinalização"),
    Param("img_server_ip", "--img-server-ip", "str", "IP do servidor de imagens"),
    Param("ice_host", "--ice-host", "str", "IP anunciado ao Quest (--ice-host)"),
    Param("forward_url", "--forward-url", "str", "URL do teleop (forward)"),
    Param("send_video", "--send-video", "bool", "Enviar vídeo"),
    Param("stereo_video", "--stereo-video", "bool", "Vídeo estéreo"),
    Param("video_fps", "--video-fps", "float", "FPS do vídeo"),
    Param("video_codec", "--video-codec", "select", "Codec", ["auto", "vp8", "h264"]),
    Param("video_max_width", "--video-max-width", "int", "Largura máx. do vídeo"),
    Param("video_max_height", "--video-max-height", "int", "Altura máx. do vídeo"),
    Param("ice_server", "--ice-server", "str", "Servidor ICE (STUN)"),
    Param("turn_url", "--turn-url", "str", "TURN URL"),
    Param("turn_username", "--turn-username", "str", "TURN usuário"),
    Param("turn_password", "--turn-password", "str", "TURN senha"),
    Param("video_debug", "--video-debug", "bool", "Log detalhado de vídeo"),
    Param("log_messages", "--log-messages", "bool", "Logar cada mensagem do DataChannel"),
    Param("extra", "", "str", "Argumentos extras"),
]

TELEOP_PARAMS = [
    Param("sim", "--sim", "bool", "Simulação (--sim)"),
    Param("tracking_source", "--tracking-source", "select", "Fonte de rastreamento", ["unity", "televuer"]),
    Param("unity_host", "--unity-host", "str", "Host da ponte Unity"),
    Param("unity_port", "--unity-port", "int", "Porta da ponte Unity"),
    Param("input_mode", "--input-mode", "select", "Entrada", ["controller", "hand"]),
    Param("arm", "--arm", "select", "Braço", ["G1_29", "G1_23", "H1_2", "H1"]),
    Param("ee", "--ee", "select", "Efetuador", ["", "dex1", "dex3", "inspire_ftp", "inspire_dfx", "brainco"],
          help="vazio = sem efetuador (mão fixa)"),
    Param("motion", "--motion", "bool", "Locomoção (--motion)"),
    Param("img_server_ip", "--img-server-ip", "str", "IP do servidor de imagens"),
    Param("network_interface", "--network-interface", "str", "Interface de rede (DDS)"),
    Param("unity_wrist_pitch_offset", "--unity-wrist-pitch-offset", "float", "Offset do pulso (graus)"),
    Param("frequency", "--frequency", "float", "Frequência (Hz)"),
    Param("haptic_mode", "--haptic-mode", "select", "Háptico", ["filtered", "legacy"]),
    Param("ipc", "--ipc", "bool", "Controle por IPC", locked=True,
          help="obrigatório: os botões da interface usam o IPC"),
    Param("record", "--record", "bool", "Gravação"),
    Param("task_dir", "--task-dir", "str", "Pasta dos dados"),
    Param("task_name", "--task-name", "str", "Nome da tarefa (pasta)"),
    Param("task_goal", "--task-goal", "str", "Objetivo (texto)"),
    Param("task_desc", "--task-desc", "str", "Descrição (texto)"),
    Param("task_steps", "--task-steps", "str", "Passos (texto)"),
    Param("headless", "--headless", "bool", "Sem Rerun (--headless)",
          help="no teleop, --headless só desliga o visualizador Rerun da gravação; "
               "sem ele o Rerun usa a porta 9876, a mesma da ponte Unity"),
    Param("affinity", "--affinity", "bool", "Afinidade de CPU"),
    Param("extra", "", "str", "Argumentos extras"),
]

SCHEMA = {"sim": SIM_PARAMS, "bridge": BRIDGE_PARAMS, "teleop": TELEOP_PARAMS}

# Tarefas validadas. Qualquer outra pode ser digitada no Avançado.
TASK_PRESETS = {
    "tres_mesas": {
        "label": "3 Mesas · mão fixa · locomoção",
        "task": "Isaac-Custom-3Tables-G129-Dex1-Wholebody",
        "ee": "", "dex1": False, "motion": True, "record_name": "tres_mesas",
        "note": "Robô de mão fixa: sem --enable_dex1_dds e sem --ee.",
    },
    "cilindro": {
        "label": "Cilindro · garra Dex1 · base fixa",
        "task": "Isaac-PickPlace-Cylinder-G129-Dex1-Joint",
        "ee": "dex1", "dex1": True, "motion": False, "record_name": "cilindro",
        "note": "Base fixa: sem locomoção.",
    },
    "mover_cilindro": {
        "label": "Mover cilindro · garra Dex1 · locomoção",
        "task": "Isaac-Move-Cylinder-G129-Dex1-Wholebody",
        "ee": "dex1", "dex1": True, "motion": True, "record_name": "mover_cilindro",
        "note": "Locomanipulação: anda com os thumbsticks e pega com a garra (gatilho).",
    },
}

DEFAULT_BASE = {
    "mode": "sim",               # sim | real
    "preset": "tres_mesas",
    "headless": True,
    "input_mode": "controller",
    "motion": True,
    "quest_ip": "",              # IP do PC visto pelo Quest (--ice-host)
    "robot_iface": "",           # interface cabeada (modo real)
    "robot_ip": DEFAULT_ROBOT_IP,
    "real_ee": "",
    "stereo": True,
    "record": True,
    "record_name": "tres_mesas",
}


def derive(base: dict) -> dict:
    """Valor de todos os parâmetros de cada processo a partir das escolhas da tela."""
    b = {**DEFAULT_BASE, **(base or {})}
    real = b["mode"] == "real"
    preset = TASK_PRESETS.get(b["preset"], TASK_PRESETS["tres_mesas"])
    img_ip = b["robot_ip"] if real else "127.0.0.1"
    controller = b["input_mode"] == "controller"
    motion = bool(b["motion"]) and controller and (real or preset["motion"])

    sim = {
        "task": preset["task"], "robot_type": "g129", "device": "cpu",
        "enable_cameras": True, "headless": bool(b["headless"]),
        "enable_dex1_dds": preset["dex1"], "enable_dex3_dds": False, "enable_inspire_dds": False,
        "step_hz": None, "physics_dt": None, "extra": "",
    }
    bridge = {
        "host": "0.0.0.0", "port": PORT_SIGNALING, "img_server_ip": img_ip,
        "ice_host": b["quest_ip"] or None,
        "forward_url": f"ws://127.0.0.1:{PORT_BRIDGE}",
        "send_video": True, "stereo_video": bool(b["stereo"]), "video_fps": 30,
        "video_codec": "auto", "video_max_width": None, "video_max_height": None,
        "ice_server": None, "turn_url": None, "turn_username": None, "turn_password": None,
        "video_debug": False, "log_messages": False, "extra": "",
    }
    teleop = {
        "sim": not real, "tracking_source": "unity",
        "unity_host": "127.0.0.1", "unity_port": PORT_BRIDGE,
        "input_mode": b["input_mode"], "arm": "G1_29",
        "ee": (b["real_ee"] if real else preset["ee"]) or "",
        "motion": motion, "img_server_ip": img_ip,
        "network_interface": (b["robot_iface"] or None) if real else None,
        "unity_wrist_pitch_offset": 60, "frequency": 30, "haptic_mode": "filtered",
        "ipc": True, "record": bool(b["record"]),
        "task_dir": "./utils/data/", "task_name": b["record_name"] or preset["record_name"],
        "task_goal": None, "task_desc": None, "task_steps": None,
        "headless": True, "affinity": False, "extra": "",
    }
    return {"sim": sim, "bridge": bridge, "teleop": teleop}


def active_processes(base: dict) -> list:
    real = (base or {}).get("mode", "sim") == "real"
    return ["bridge", "teleop"] if real else ["sim", "bridge", "teleop"]


def resolve(base: dict, overrides: dict) -> dict:
    values = derive(base)
    for proc, ov in (overrides or {}).items():
        if proc not in values:
            continue
        for key, val in ov.items():
            param = next((p for p in SCHEMA[proc] if p.key == key), None)
            if param is None or param.locked:
                continue
            values[proc][key] = val
    return values


def _args_for(proc: str, values: dict) -> list:
    args = []
    for p in SCHEMA[proc]:
        v = values.get(p.key)
        if p.key == "extra":
            if v:
                args += shlex.split(str(v))
            continue
        if p.kind == "bool":
            if v is True or (isinstance(v, str) and v.lower() in ("1", "true", "sim")):
                args.append(p.flag)
            continue
        if v is None or v == "":
            continue
        args += [p.flag, str(v)]
    return args


def script_args(proc: str, values: dict) -> list:
    script = {"sim": "sim_main.py", "bridge": "python_webrtc.py", "teleop": "teleop_hand_and_arm.py"}[proc]
    return [script] + _args_for(proc, values)


def launch_spec(proc: str, values: dict, extra_args: Optional[list] = None) -> dict:
    """argv real (com ativação do conda), cwd e a linha exibida na tela."""
    args = script_args(proc, values) + (extra_args or [])
    env_name = SIM_ENV if proc == "sim" else TELEOP_ENV
    cwd = {"sim": SIM_REPO, "bridge": REPO, "teleop": TELEOP_DIR}[proc]
    inner = "python -u " + " ".join(shlex.quote(a) for a in args)
    conda_sh = CONDA_ROOT / "etc" / "profile.d" / "conda.sh"
    shell = f"source {shlex.quote(str(conda_sh))} && conda activate {shlex.quote(env_name)} && exec {inner}"
    return {
        "argv": ["bash", "-c", shell],
        "cwd": str(cwd),
        "display": f"(cd {cwd} && conda activate {env_name} && python {' '.join(shlex.quote(a) for a in args)})",
        "short": "python " + " ".join(shlex.quote(a) for a in args),
    }


def validate(base: dict, values: dict) -> list:
    """Avisos para combinações que sabemos que falham."""
    warnings = []
    real = (base or {}).get("mode") == "real"
    sim, bridge, teleop = values["sim"], values["bridge"], values["teleop"]
    if not bridge.get("ice_host"):
        warnings.append("Escolha o IP do PC na rede do Quest (vira --ice-host).")
    if real:
        if not teleop.get("network_interface"):
            warnings.append("Modo real: escolha a interface cabeada do robô (--network-interface).")
        if teleop.get("sim"):
            warnings.append("Modo real com --sim ligado: o teleop falaria com a simulação (domínio DDS 1).")
    else:
        fixed_hand = "3Tables" in str(sim.get("task"))
        if fixed_hand and (sim.get("enable_dex1_dds") or teleop.get("ee")):
            warnings.append("Tarefa de mão fixa: desligue --enable_dex1_dds e deixe --ee vazio.")
        if teleop.get("motion") and "Wholebody" not in str(sim.get("task")):
            warnings.append("--motion ligado numa tarefa sem Wholebody: o robô não vai andar.")
    if teleop.get("tracking_source") == "unity" and teleop.get("ee") in ("dex3", "inspire_ftp", "inspire_dfx", "brainco"):
        warnings.append("Com Unity só funcionam --ee dex1 ou nenhum.")
    if teleop.get("record") and not teleop.get("headless") and str(teleop.get("unity_port")) == "9876":
        warnings.append("Gravação sem --headless no teleop: o Rerun tenta usar a porta 9876 da ponte Unity.")
    if teleop.get("input_mode") == "hand" and teleop.get("motion"):
        warnings.append("Locomoção só funciona com --input-mode controller.")
    return warnings


def list_sim_tasks() -> list:
    """Todos os gym ids registrados no repositório da simulação."""
    ids = set()
    try:
        for f in (SIM_REPO / "tasks").rglob("__init__.py"):
            for m in re.finditer(r'id\s*=\s*"([^"]+)"', f.read_text(errors="ignore")):
                if m.group(1).startswith("Isaac-"):
                    ids.add(m.group(1))
    except OSError:
        pass
    return sorted(ids)


def schema_json() -> dict:
    return {proc: [asdict(p) for p in params] for proc, params in SCHEMA.items()}

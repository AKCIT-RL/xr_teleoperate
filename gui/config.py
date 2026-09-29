"""Caminhos, envs e constantes da interface de teleoperação."""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# Repositório da simulação: symlink ao lado deste repo (sobrescrevível por variável de ambiente)
SIM_REPO = Path(os.environ.get("TELEOP_GUI_SIM_REPO", str(REPO.parent / "unitree_sim_isaaclab")))
CONDA_ROOT = Path(os.environ.get("TELEOP_GUI_CONDA_ROOT", str(Path.home() / "miniconda3")))
SIM_ENV = os.environ.get("TELEOP_GUI_SIM_ENV", "unitree_sim_env")
TELEOP_ENV = os.environ.get("TELEOP_GUI_TELEOP_ENV", "tv_unity_svr")

TELEOP_DIR = REPO / "teleop"
DATA_DIR = TELEOP_DIR / "utils" / "data"
CACHE_DIR = Path(__file__).resolve().parent / ".cache"
STATIC_DIR = Path(__file__).resolve().parent / "static"

GUI_HOST = os.environ.get("TELEOP_GUI_HOST", "0.0.0.0")
GUI_PORT = int(os.environ.get("TELEOP_GUI_PORT", "8080"))

# Portas usadas pelos processos (verificadas antes de iniciar)
PORT_SIGNALING = 8765
PORT_BRIDGE = 9876
PORT_IMAGES = 55555
PORT_CAM_CONFIG = 60000

DEFAULT_ROBOT_IP = "192.168.123.164"

# Quanto esperar cada processo encerrar após SIGINT antes de escalar para SIGTERM/SIGKILL
STOP_GRACE_S = {"sim": 20.0, "bridge": 5.0, "teleop": 10.0}

LOG_BUFFER_LINES = 3000

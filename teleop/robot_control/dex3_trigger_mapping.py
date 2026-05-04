"""
Dex3 trigger -> joint target mapping.

Modulo utilitario do desenho descrito em
``docs/DEX3_TRIGGER_CONTROLLER_DESIGN.md`` (Modulos B e C).

Responsabilidades:

- Modulo B: normalizacao + saturacao do `triggerValue` do Quest 3.
  O `tv_wrapper` ja expoe `*_ctrl_triggerValue` na faixa documentada
  ``10.0 -> 0.0`` (0.0 = totalmente pressionado).  Aqui convertemos para
  ``alpha`` em ``[0.0, 1.0]`` com `0.0 = aberto` e `1.0 = fechado`.

- Modulo C: mapeamento linear por junta para 7 alvos por mao.
  Os limites e a ordem de juntas seguem estritamente:
    * `assets/unitree_hand/unitree_dex3_left.urdf`
    * `assets/unitree_hand/unitree_dex3_right.urdf`
    * `Dex3_1_Left_JointIndex` / `Dex3_1_Right_JointIndex`
      em `teleop/robot_control/robot_hand_unitree.py`

Decisoes conservadoras (documentadas e ajustaveis):

- `thumb_0` (rotacao base do polegar, eixo y) e mantida em `0.0` por
  padrao em ambas as maos: a direcao mecanica de "oposicao" desta junta
  nao e inferivel apenas pelo URDF, portanto preferimos nao move-la
  via trigger ate que o operador confirme em hardware.
- Demais juntas usam direcao de fechamento coerente com o URDF e
  margem em relacao ao limite (`SAFETY_MARGIN`) para evitar bater no
  fim de curso.
- `clip_to_dex3_limits()` aplica saturacao final contra os limites
  reais do URDF independentemente da configuracao escolhida.
"""

from __future__ import annotations

import math
from enum import Enum

import numpy as np


# ---------------------------------------------------------------------------
# Trigger normalization (Modulo B)
# ---------------------------------------------------------------------------

# Faixa em que o tv_wrapper publica o trigger (ja invertida em relacao ao raw
# do televuer), conforme `teleop/televuer/src/televuer/tv_wrapper.py`:
#
#     left_ctrl_triggerValue: float = 10.0   # 10.0 -> 0.0
#     ...
#     left_ctrl_triggerValue=10.0 - self.tvuer.left_ctrl_triggerValue * 10
#
# Logo:
#   - 10.0 = trigger solto (aberto)
#   -  0.0 = trigger totalmente pressionado (fechado)
TRIGGER_VALUE_OPEN: float = 10.0
TRIGGER_VALUE_CLOSED: float = 0.0


def normalize_trigger(value: float) -> float:
    """Converte `triggerValue` (faixa do tv_wrapper) em ``alpha in [0, 1]``.

    Semantica resultante:
        * `alpha = 0.0` -> mao aberta (trigger solto)
        * `alpha = 1.0` -> mao fechada (trigger no maximo)

    Politica de seguranca:
        * `NaN` ou `Inf` -> retorna `0.0` (mao aberta) como fallback seguro.
        * Valores fora de `[0.0, 10.0]` sao saturados antes da conversao.
    """
    if value is None:
        return 0.0
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(v) or math.isinf(v):
        return 0.0
    v_clamped = max(TRIGGER_VALUE_CLOSED, min(TRIGGER_VALUE_OPEN, v))
    return (TRIGGER_VALUE_OPEN - v_clamped) / (TRIGGER_VALUE_OPEN - TRIGGER_VALUE_CLOSED)


# ---------------------------------------------------------------------------
# Limites reais do URDF (Modulo C - tabela explicita)
# ---------------------------------------------------------------------------

class Dex3Side(Enum):
    LEFT = "left"
    RIGHT = "right"


# Limites extraidos do URDF, na MESMA ordem usada pelo controlador
# (`Dex3_1_Left_JointIndex` / `Dex3_1_Right_JointIndex`).
#
# LEFT  hardware order: [thumb_0, thumb_1, thumb_2, middle_0, middle_1, index_0, index_1]
# RIGHT hardware order: [thumb_0, thumb_1, thumb_2, index_0, index_1, middle_0, middle_1]
DEX3_LEFT_JOINT_LIMITS: np.ndarray = np.array(
    [
        # (lower, upper)
        (-1.04719755, 1.04719755),  # left_hand_thumb_0_joint
        (-0.72431163, 0.920),        # left_hand_thumb_1_joint
        (0.0, 1.74532925),           # left_hand_thumb_2_joint
        (-1.57079632, 0.0),          # left_hand_middle_0_joint
        (-1.74532925, 0.0),          # left_hand_middle_1_joint
        (-1.57079632, 0.0),          # left_hand_index_0_joint
        (-1.74532925, 0.0),          # left_hand_index_1_joint
    ],
    dtype=np.float64,
)

DEX3_RIGHT_JOINT_LIMITS: np.ndarray = np.array(
    [
        (-1.04719755, 1.04719755),   # right_hand_thumb_0_joint
        (-0.920, 0.72431163),        # right_hand_thumb_1_joint
        (-1.74532925, 0.0),          # right_hand_thumb_2_joint
        (0.0, 1.57079632),           # right_hand_index_0_joint
        (0.0, 1.74532925),           # right_hand_index_1_joint
        (0.0, 1.57079632),           # right_hand_middle_0_joint
        (0.0, 1.74532925),           # right_hand_middle_1_joint
    ],
    dtype=np.float64,
)


# ---------------------------------------------------------------------------
# Pose padrao de aberto/fechado (Modulo C - default conservador)
# ---------------------------------------------------------------------------

# Postura aberta = 0.0 em todas as juntas (palma estendida segundo o URDF).
DEX3_LEFT_OPEN_QPOS: np.ndarray = np.zeros(7, dtype=np.float64)
DEX3_RIGHT_OPEN_QPOS: np.ndarray = np.zeros(7, dtype=np.float64)


# Postura fechada (valores escolhidos dentro dos limites do URDF, com margem):
#   - thumb_0 mantida em 0.0 (direcao mecanica nao trivial pelo URDF).
#   - thumb_1: usa o lado de maior amplitude do range para flexao do polegar,
#     com aproximadamente 76% do limite (LEFT: 0.7 / 0.920; RIGHT: -0.7 / -0.920).
#   - thumb_2 e flexores middle/index: ~80% do limite na direcao de fechamento.
DEX3_LEFT_CLOSE_QPOS: np.ndarray = np.array(
    [
        0.0,    # thumb_0 (neutro)
        0.7,    # thumb_1 (limite +0.920)
        1.4,    # thumb_2 (limite +1.74532925)
        -1.3,   # middle_0 (limite -1.57079632)
        -1.4,   # middle_1 (limite -1.74532925)
        -1.3,   # index_0  (limite -1.57079632)
        -1.4,   # index_1  (limite -1.74532925)
    ],
    dtype=np.float64,
)

DEX3_RIGHT_CLOSE_QPOS: np.ndarray = np.array(
    [
        0.0,    # thumb_0 (neutro)
        -0.7,   # thumb_1 (limite -0.920)
        -1.4,   # thumb_2 (limite -1.74532925)
        1.3,    # index_0  (limite +1.57079632)
        1.4,    # index_1  (limite +1.74532925)
        1.3,    # middle_0 (limite +1.57079632)
        1.4,    # middle_1 (limite +1.74532925)
    ],
    dtype=np.float64,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _select_side(side):
    if isinstance(side, Dex3Side):
        return side
    if isinstance(side, str):
        s = side.strip().lower()
        if s in ("l", "left"):
            return Dex3Side.LEFT
        if s in ("r", "right"):
            return Dex3Side.RIGHT
    raise ValueError(f"Invalid Dex3 side: {side!r}; use 'left' or 'right'.")


def get_dex3_limits(side) -> np.ndarray:
    """Retorna os limites (lower, upper) por junta na ordem de hardware."""
    s = _select_side(side)
    return DEX3_LEFT_JOINT_LIMITS if s is Dex3Side.LEFT else DEX3_RIGHT_JOINT_LIMITS


def get_dex3_open_qpos(side) -> np.ndarray:
    s = _select_side(side)
    return (DEX3_LEFT_OPEN_QPOS if s is Dex3Side.LEFT else DEX3_RIGHT_OPEN_QPOS).copy()


def get_dex3_close_qpos(side) -> np.ndarray:
    s = _select_side(side)
    return (DEX3_LEFT_CLOSE_QPOS if s is Dex3Side.LEFT else DEX3_RIGHT_CLOSE_QPOS).copy()


def clip_to_dex3_limits(qpos: np.ndarray, side) -> np.ndarray:
    """Satura `qpos` (7,) contra os limites reais do URDF para o lado dado."""
    limits = get_dex3_limits(side)
    qpos = np.asarray(qpos, dtype=np.float64).reshape(-1)
    if qpos.shape[0] != limits.shape[0]:
        raise ValueError(
            f"qpos has shape {qpos.shape}, expected ({limits.shape[0]},) for side {side}"
        )
    lower = limits[:, 0]
    upper = limits[:, 1]
    return np.clip(qpos, lower, upper)


def map_trigger_to_dex3(
    alpha: float,
    side,
    open_qpos: np.ndarray | None = None,
    close_qpos: np.ndarray | None = None,
) -> np.ndarray:
    """Mapeia ``alpha in [0, 1]`` em alvos articulares Dex3 do lado dado.

    Implementacao:
        ``q_i = q_open_i + alpha * (q_close_i - q_open_i)``

    Garantias:
        * Saturacao de `alpha` em `[0, 1]` (defensiva).
        * Resultado final passa por `clip_to_dex3_limits` para garantir que
          presets customizados nao violem o URDF.
    """
    side_enum = _select_side(side)
    if open_qpos is None:
        open_qpos = get_dex3_open_qpos(side_enum)
    if close_qpos is None:
        close_qpos = get_dex3_close_qpos(side_enum)

    a = float(alpha)
    if math.isnan(a) or math.isinf(a):
        a = 0.0
    a = max(0.0, min(1.0, a))

    open_q = np.asarray(open_qpos, dtype=np.float64).reshape(-1)
    close_q = np.asarray(close_qpos, dtype=np.float64).reshape(-1)
    if open_q.shape != close_q.shape or open_q.shape[0] != 7:
        raise ValueError(
            "open_qpos/close_qpos must both have shape (7,); "
            f"got open={open_q.shape}, close={close_q.shape}"
        )

    q_target = open_q + a * (close_q - open_q)
    return clip_to_dex3_limits(q_target, side_enum)


__all__ = [
    "Dex3Side",
    "TRIGGER_VALUE_OPEN",
    "TRIGGER_VALUE_CLOSED",
    "DEX3_LEFT_JOINT_LIMITS",
    "DEX3_RIGHT_JOINT_LIMITS",
    "DEX3_LEFT_OPEN_QPOS",
    "DEX3_RIGHT_OPEN_QPOS",
    "DEX3_LEFT_CLOSE_QPOS",
    "DEX3_RIGHT_CLOSE_QPOS",
    "normalize_trigger",
    "get_dex3_limits",
    "get_dex3_open_qpos",
    "get_dex3_close_qpos",
    "clip_to_dex3_limits",
    "map_trigger_to_dex3",
]

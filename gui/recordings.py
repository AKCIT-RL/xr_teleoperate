"""Episódios gravados pelo teleop (--record): lista, séries para os gráficos e imagens.

O data.json de um episódio longo tem dezenas de MB; o resultado processado fica em
cache (gui/.cache), invalidado pela data de modificação do arquivo.
"""
import hashlib
import json
import math
from pathlib import Path

from config import DATA_DIR, CACHE_DIR

MAX_POINTS = 1500
CACHE_VERSION = 3          # mude quando o formato das séries mudar


def _cache_path(data_json: Path) -> Path:
    st = data_json.stat()
    h = hashlib.sha1(f"{CACHE_VERSION}:{data_json}:{st.st_mtime_ns}:{st.st_size}".encode()).hexdigest()[:16]
    return CACHE_DIR / f"ep_{h}.json"


def _episode_dirs():
    if not DATA_DIR.is_dir():
        return []
    return sorted(p.parent for p in DATA_DIR.glob("*/episode_*/data.json"))


def safe_episode_dir(task: str, episode: str) -> Path:
    d = (DATA_DIR / task / episode).resolve()
    if DATA_DIR.resolve() not in d.parents or not (d / "data.json").is_file():
        raise FileNotFoundError(f"{task}/{episode}")
    return d


def list_episodes() -> list:
    out = []
    for d in _episode_dirs():
        data_json = d / "data.json"
        meta = None
        cp = _cache_path(data_json)
        if cp.is_file():
            try:
                meta = json.loads(cp.read_text())["meta"]
            except (OSError, ValueError, KeyError):
                meta = None
        out.append({
            "task": d.parent.name, "episode": d.name,
            "mtime": data_json.stat().st_mtime,
            "size_mb": round(data_json.stat().st_size / 1e6, 1),
            "meta": meta,          # None até o episódio ser aberto pela primeira vez
        })
    return out


def _yaw(q):
    w, x, y, z = q
    return math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))


def _state_of(frame):
    ss = frame.get("sim_state") or {}
    st = ss.get("init_state")
    if isinstance(st, str):
        try:
            st = json.loads(st)
        except ValueError:
            st = None
    return st or {}, ss.get("task_name")


def load_series(task: str, episode: str) -> dict:
    d = safe_episode_dir(task, episode)
    data_json = d / "data.json"
    cp = _cache_path(data_json)
    if cp.is_file():
        try:
            return json.loads(cp.read_text())
        except ValueError:
            pass

    content = json.loads(data_json.read_text())
    frames = content.get("data", [])
    info = content.get("info", {})
    fps = float((info.get("image") or {}).get("fps") or 30.0)
    n = len(frames)
    step = max(1, math.ceil(n / MAX_POINTS))
    idx = list(range(0, n, step))

    def q(frame, group, side):
        return (frame.get(group, {}).get(side, {}) or {}).get("qpos", []) or []

    series = {"i": idx, "t": [i / fps for i in idx],
              "left_state": [], "left_action": [], "right_state": [], "right_action": [],
              "base_x": [], "base_y": [], "base_yaw": [], "vx": [], "vy": [], "wz": []}
    task_name = None
    for i in idx:
        f = frames[i]
        series["left_state"].append(q(f, "states", "left_arm"))
        series["left_action"].append(q(f, "actions", "left_arm"))
        series["right_state"].append(q(f, "states", "right_arm"))
        series["right_action"].append(q(f, "actions", "right_arm"))
        st, tn = _state_of(f)
        task_name = task_name or tn
        robot = (st.get("articulation") or {}).get("robot") or {}
        pose = (robot.get("root_pose") or [[None] * 7])[0]
        if pose and pose[0] is not None:
            series["base_x"].append(pose[0]); series["base_y"].append(pose[1]); series["base_yaw"].append(_yaw(pose[3:7]))
        else:
            for k in ("base_x", "base_y", "base_yaw"):
                series[k].append(None)

    # Velocidade pela variação da posição da base (~0,2 s entre amostras): a velocidade
    # instantânea do sim_state oscila com cada passo da política de RL e esconde o deslocamento.
    xs, ys, yaws = series["base_x"], series["base_y"], series["base_yaw"]
    for k in range(len(idx)):
        a, b = max(0, k - 1), min(len(idx) - 1, k + 1)
        if a == b or None in (xs[a], xs[b], yaws[a], yaws[b]):
            series["vx"].append(None); series["vy"].append(None); series["wz"].append(None)
            continue
        dt = (idx[b] - idx[a]) / fps
        dx, dy = (xs[b] - xs[a]) / dt, (ys[b] - ys[a]) / dt
        yaw = yaws[k] if yaws[k] is not None else yaws[a]
        c, s = math.cos(yaw), math.sin(yaw)
        dyaw = math.atan2(math.sin(yaws[b] - yaws[a]), math.cos(yaws[b] - yaws[a]))
        series["vx"].append(c * dx + s * dy)
        series["vy"].append(-s * dx + c * dy)
        series["wz"].append(dyaw / dt)
    # média móvel de ~1 s: tira o balanço da marcha e deixa o comando de deslocamento
    half = max(1, int(round(0.5 * fps / step)))
    for k in ("vx", "vy", "wz"):
        vals = series[k]
        smooth = []
        for j in range(len(vals)):
            win = [v for v in vals[max(0, j - half): j + half + 1] if v is not None]
            smooth.append(sum(win) / len(win) if win and vals[j] is not None else None)
        series[k] = smooth

    # posição inicial e final dos objetos (para o mapa)
    objects = {}
    for which, fi in (("start", 0), ("end", n - 1)):
        if n == 0:
            break
        st, _ = _state_of(frames[fi])
        for name, obj in ((st.get("rigid_object") or {}).items()):
            pose = (obj.get("root_pose") or [[None]])[0]
            if pose and pose[0] is not None:
                objects.setdefault(name, {})[which] = [pose[0], pose[1]]

    cams = sorted((frames[0].get("colors") or {}).keys()) if n else []
    meta = {
        "frames": n, "fps": fps, "duration": n / fps if fps else 0,
        "task_name": task_name, "cameras": cams, "date": info.get("date"),
        "has_sim_state": any(v is not None for v in series["base_x"]),
        "goal": (content.get("text") or {}).get("goal"),
    }
    result = {"meta": meta, "series": series, "objects": objects}
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(result))
    return result


def frame_image(task: str, episode: str, index: int, cam: int) -> Path:
    d = safe_episode_dir(task, episode)
    p = (d / "colors" / f"{index:06d}_color_{cam}.jpg").resolve()
    if d not in p.parents or not p.is_file():
        raise FileNotFoundError(str(p))
    return p

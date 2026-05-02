import argparse
import json
import logging
import math
import os
import shutil
from pathlib import Path

import imageio.v3 as iio
import numpy as np
import pandas as pd
from datasets import Dataset, Features, Sequence, Value

# Configuração para ignorar verbosity do datasets em stdout
from datasets.utils.logging import set_verbosity_error
set_verbosity_error()

FPS = 30

def flatten_qpos(item):
    if isinstance(item, dict):
        if "qpos" in item:
            item = item["qpos"]
        else:
            item = list(item.values())
    if isinstance(item, (list, tuple, np.ndarray)):
        return [float(x) for x in item]
    return [float(item)]

class Manipulation2PsiConverter:
    """
    Converter formatado especificamente para as tarefas de MANIPULAÇÃO.
    Ele gera as variáveis de locomoção com zeros para isolar as predições.
    """
    def __init__(self):
        # Features originais que o Psi0 espera (estados com len=32 e ações com len=36)
        self.features = Features({
            "states": Sequence(Value("float32")),
            "action": Sequence(Value("float32")),
            "timestamp": Value("float32"),
            "frame_index": Value("int64"),
            "episode_index": Value("int64"),
            "index": Value("int64"),
            "task_index": Value("int64"),
            "next.done": Value("bool"),
        })

    def pad_array(self, arr, expected_len):
        """Preenche o array com zeros caso a mão não possua o número padrão de DoFs."""
        arr = list(arr)
        if len(arr) < expected_len:
            arr += [0.0] * (expected_len - len(arr))
        return arr[:expected_len]

    def build_obs(self, frame):
        # 14 juntas da mão + 14 juntas dos braços + RPY (3) + Height (1) = 32 posições
        states = frame.get("states", {})
        
        left_arm = self.pad_array(flatten_qpos(states.get("left_arm", [])), 7)
        right_arm = self.pad_array(flatten_qpos(states.get("right_arm", [])), 7)
        
        left_ee = self.pad_array(flatten_qpos(states.get("left_ee", [])), 7)
        right_ee = self.pad_array(flatten_qpos(states.get("right_ee", [])), 7)

        # Variáveis dummy de locomoção com torso passivo estático
        torso_rpy_height = [0.0, 0.0, 0.0, 0.75]
        
        return left_ee + right_ee + left_arm + right_arm + torso_rpy_height
    
    def build_act(self, frame):
        # 14 juntas da mão + 14 juntas dos braços + RPY (3) + Height (1) + Locomoção(4) = 36 posições
        actions = frame.get("actions", {})
        
        left_arm = self.pad_array(flatten_qpos(actions.get("left_arm", [])), 7)
        right_arm = self.pad_array(flatten_qpos(actions.get("right_arm", [])), 7)
        
        left_ee = self.pad_array(flatten_qpos(actions.get("left_ee", [])), 7)
        right_ee = self.pad_array(flatten_qpos(actions.get("right_ee", [])), 7)

        # Variáveis contínuas em zero forçando a estaticidade do torso na manipulação 
        torso_rpy_height = [0.0, 0.0, 0.0, 0.75]
        torso_loco_padding = [0.0, 0.0, 0.0, 0.0] # torso_vx, torso_vy, torso_vyaw, target_yaw
        
        return left_ee + right_ee + left_arm + right_arm + torso_rpy_height + torso_loco_padding

    def process_episode(self, episode_dir, episode_index, task_index, out_base, chunks_size=1000):
        print(f"Lendo episódio {episode_index} de {episode_dir}...")
        json_path = os.path.join(episode_dir, "data.json")
        try:
            with open(json_path, "r") as f:
                content = json.load(f)
            
            # Se for um ditonário com chave data, pega a chave. Senão, assume lista pura.
            data_list = content.get("data", content) if isinstance(content, dict) else content
        except Exception as e:
            print(f"Erro processando dados do episódio: {e}")
            return False, 0
        
        if not data_list:
            return False, 0

        # Identificando key da câmera principal (geralmente color_0)
        camera_key = None
        if "colors" in data_list[0]:
            keys = sorted(list(data_list[0]["colors"].keys()))
            if keys: camera_key = keys[0]

        rows = []
        rgb_paths = []
        for i, frame in enumerate(data_list):
            obs_array = self.build_obs(frame)
            act_array = self.build_act(frame)
            
            rows.append({
                "states": obs_array,
                "action": act_array,
                "timestamp": i * (1.0 / FPS),
                "frame_index": i,
                "episode_index": episode_index,
                "index": i,
                "task_index": task_index,
                "next.done": (i == len(data_list) - 1),
            })

            if camera_key:
                img_path = os.path.join(episode_dir, frame["colors"].get(camera_key, ""))
                rgb_paths.append(img_path)

        # Escrever o HF Dataset do episódio
        chunk_path = out_base / "data" / f"chunk-{episode_index // chunks_size:03d}"
        chunk_path.mkdir(parents=True, exist_ok=True)
        parquet_path = chunk_path / f"episode_{episode_index:06d}.parquet"
        
        ds = Dataset.from_list(rows, features=self.features)
        ds.to_parquet(str(parquet_path))

        # Escrever vídeo do episódio
        def frame_iter():
            for p in rgb_paths:
                if os.path.exists(p):
                    yield iio.imread(p)
                else:
                    # Frame vazio p/ evitar crash se houver falha corrompida de disco
                    yield np.zeros((480, 640, 3), dtype=np.uint8)

        if rgb_paths:
            vid_chunk_dir = out_base / "videos" / f"chunk-{episode_index // chunks_size:03d}" / "egocentric"
            vid_chunk_dir.mkdir(parents=True, exist_ok=True)
            vid_path = vid_chunk_dir / f"episode_{episode_index:06d}.mp4"
            iio.imwrite(vid_path, list(frame_iter()), fps=FPS, codec="libx264")

        return True, len(rows)


def main():
    parser = argparse.ArgumentParser(description="Conversor de XR Teleoperate para Psi0 (Apenas Manipulação)")
    parser.add_argument("--data-dir", type=str, required=True, help="Diretório alvo do XR Teleoperate (ex: data/pick_cylinder_manipulation)")
    parser.add_argument("--task-name", type=str, default="robot_manipulation", help="Nome da task")
    args = parser.parse_args()

    data_root = Path(args.data_dir).expanduser().resolve()
    
    # Criar pasta data/terminada com _psi para ficar isolada e visual
    base_out_dir = Path(__file__).parent / "data" / f"{data_root.name}_psi"
    
    if base_out_dir.exists():
        print(f"Limpando diretório do dataset existente: {base_out_dir}")
        shutil.rmtree(base_out_dir)
        
    for d in [base_out_dir / "data", base_out_dir / "videos", base_out_dir / "meta"]:
        d.mkdir(parents=True, exist_ok=True)

    print(f"Iniciando Mapeamento em {data_root}")
    print(f"As saídas preparadas para Psi0 sairão em {base_out_dir}")

    pipeline = Manipulation2PsiConverter()
    
    ep_dirs = sorted([p for p in data_root.iterdir() if p.is_dir() and "episode_" in p.name])
    
    episodes_meta = []
    dataset_cursor = 0
    total_frames = 0
    
    for ep_index, ep_dir in enumerate(ep_dirs):
        success, n_frames = pipeline.process_episode(ep_dir, ep_index, task_index=0, out_base=base_out_dir)
        if success:
            episodes_meta.append({
                "episode_index": ep_index,
                "tasks": [0],
                "length": n_frames,
                "dataset_from_index": dataset_cursor,
                "dataset_to_index": dataset_cursor + (n_frames - 1),
                "robot_type": "g1_manipulation",
                "instruction": args.task_name
            })
            dataset_cursor += n_frames
            total_frames += n_frames
            
    # Cria o metadata no padrao LeRobot
    if episodes_meta:
        meta_dir = base_out_dir / "meta"
        
        episodes_df = pd.DataFrame(episodes_meta)
        episodes_df.to_json(meta_dir / "episodes.jsonl", orient="records", lines=True)

        tasks_df = pd.DataFrame([{"task_index": 0, "task": args.task_name, "category": "manipulation", "description": ""}])
        tasks_df.to_json(meta_dir / "tasks.jsonl", orient="records", lines=True)

        info = {
            "codebase_version": "v2.1",
            "robot_type": "g1_manipulation",
            "total_episodes": len(ep_dirs),
            "total_frames": total_frames,
            "total_tasks": 1,
            "fps": FPS,
            "data_path": "data/chunk-{episode_chunk:03d}/episode_{episode_index:06d}.parquet",
            "video_path": "videos/chunk-{episode_chunk:03d}/egocentric/episode_{episode_index:06d}.mp4",
        }
        with open(meta_dir / "info.json", "w") as f:
            json.dump(info, f, indent=4)
        
        print("\n✅ Conversão finalizada com sucesso. Formato LeRobot Dataset compatível com Psi0!")
    else:
        print("\n⚠️ Nenhum episódio processado.")

if __name__ == "__main__":
    main()

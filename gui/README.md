# Interface de teleoperação (gui/)

Página web local que inicia, acompanha e encerra a simulação, a ponte WebRTC e o teleop,
mostra a visão do robô e os logs, controla a teleoperação (iniciar, gravar, encerrar) e
lista as gravações com replay determinístico no Isaac. Funciona em simulação e no robô real.

```bash
conda activate tv_unity_svr
cd ~/workspace/svr/xr_teleoperate
python gui/app.py            # abre em http://localhost:8080
```

Não precisa de pacotes além dos do `tv_unity_svr` (`aiohttp`, `pyzmq`, `psutil`) nem de
internet. Uso passo a passo: [docs/GUIA_RAPIDO_TELEOP_UNITY.md](../docs/GUIA_RAPIDO_TELEOP_UNITY.md).

## Arquivos

| Arquivo | O que faz |
|---|---|
| `app.py` | servidor (aiohttp): rotas, WebSocket de estado/logs, orquestração da sessão |
| `commands.py` | todos os parâmetros de cada processo, presets de tarefa e montagem das linhas de comando |
| `procman.py` | inicia cada processo em grupo próprio, lê a saída, detecta marcos ("pronto", "Quest conectado"), encerra em etapas (SIGINT → SIGTERM → SIGKILL) |
| `logfilter.py` | nível de cada linha, filtro de ruído, agrupamento de linhas repetidas |
| `teleop_ipc.py` | cliente do `--ipc` do teleop (comandos R/S/Q e heartbeat de estado) |
| `video.py` | assina o JPEG do servidor de imagens (ZMQ) e repassa como MJPEG ao navegador |
| `checks.py` | interfaces de rede, portas, GPU, processos antigos, ping e servidor de imagens do robô |
| `recordings.py` | lista episódios, séries para os gráficos (com cache em `.cache/`) e imagens |
| `static/` | página (HTML, CSS, JS, gráficos em canvas) |

## Como a interface fala com cada processo

- **Iniciar/encerrar:** `bash -c "source conda.sh && conda activate <env> && exec python -u <script> ..."`
  com `start_new_session`; o encerramento sinaliza o grupo inteiro.
- **Estado:** marcos nos logs (`procman.MARKERS`), heartbeat do IPC do teleop e a linha
  `[stats]` da ponte (a cada 5 s).
- **Teleoperação:** o teleop sempre sobe com `--ipc`; os botões mandam `CMD_START`,
  `CMD_RECORD_TOGGLE` e `CMD_STOP`.
- **Visão do robô:** `GET /video.mjpg?host=<servidor de imagens>&port=55555`.

## Observações

- O teleop sobe com `--headless` por padrão: nele, essa flag só desliga o visualizador Rerun
  da gravação, que de outra forma tenta usar a porta 9876 (a mesma da ponte Unity).
- Ao encerrar, o `sim_main.py` manda SIGTERM para **qualquer** processo cuja linha de comando
  contenha `sim_main.py` (`pgrep -f sim_main.py`). Evite ter um terminal rodando algo com
  esse texto (ex.: `grep sim_main.py`) enquanto a simulação fecha.
- No replay, a simulação costuma não fechar com Ctrl+C (trava em `simulation_app.close()`);
  a interface escala para SIGKILL depois de ~25 s.

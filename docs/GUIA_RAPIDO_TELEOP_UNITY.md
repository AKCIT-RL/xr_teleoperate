# Guia rápido — Teleoperação com Unity (Meta Quest) + simulação

Passo a passo para rodar a teleoperação do G1 no IsaacLab usando o app Unity no Quest.
Para entender o que cada processo faz, veja [ARQUITETURA_TELEOP_UNITY.md](ARQUITETURA_TELEOP_UNITY.md).

## Pré-requisitos (uma vez)

- Envs conda: `unitree_sim_env` (simulação) e `tv_unity_svr` (teleop).
- APK `com.Asteroyde.Teleop2` instalado no Quest (`adb install -r teleop.apk`).
- Quest e PC **na mesma rede Wi‑Fi**. Descubra o IP do PC:
  ```bash
  ip -4 -br addr        # ex.: wlp130s0  192.168.77.42/24
  ```
  Nos comandos abaixo, troque `<IP_PC>` por esse endereço.

## Pela interface (recomendado)

```bash
conda activate tv_unity_svr
cd ~/workspace/svr/xr_teleoperate
python gui/app.py
```

Abra `http://localhost:8080` (F11 para tela cheia na TV). Não precisa de internet.

1. **Operação → Configurar sessão:** escolha modo (SIM/REAL), tarefa, headless, entrada,
   IP do PC (rede do Quest) e gravação. Todos os parâmetros de cada processo e os comandos
   finais ficam em **Avançado**.
2. **Iniciar sessão:** a interface sobe simulação → ponte → teleop e mostra cada etapa.
   No modo real ela verifica o servidor de imagens do robô (que você inicia no robô) e
   exige os três itens de segurança.
3. **No Quest:** abra o app e conecte no endereço mostrado (`<IP_PC>:8765`).
4. **Iniciar teleoperação (R)** libera quando o Quest estiver conectado. **Gravar (S)** e
   **Encerrar teleop (Q)** ficam no mesmo painel; **Parar tudo** no topo encerra tudo.
5. **Gravações:** lista os episódios, com player das imagens, gráficos e o botão
   **Replay determinístico no Isaac** (encerre a sessão antes).

**Conexão do Quest pelo cabo USB (sem Wi‑Fi)**

O Quest 3 transforma a porta USB numa placa de rede (modo NCM). O PC entrega IP a ele e o
WebRTC passa todo pelo cabo — não depende da rede do evento.

- **Uma vez no PC** (cria o perfil de rede que distribui IP no cabo):
  ```bash
  nmcli connection add type ethernet con-name quest-usb match.driver cdc_ncm \
    ipv4.method shared ipv6.method disabled connection.autoconnect-priority 10
  ```
- **A cada sessão:** com o Quest no cabo e a depuração USB autorizada, clique em
  **Ativar cabo USB** (em Configurar sessão → Rede e vídeo). A interface liga o modo NCM,
  espera o Quest pegar IP e seleciona `10.42.0.1` como IP do PC. No app: `10.42.0.1:8765`.
- O indicador mostra se o cabo está ativo e o topo mostra **Quest · cabo** ou **Quest · Wi‑Fi**;
  na operação, o painel do Quest mostra o caminho em uso.
- O modo cabo **não fica salvo**: reiniciar o óculos ou reconectar o cabo desliga. A troca de
  modo pede de novo a autorização de depuração USB no óculos.
- Pelo terminal: `adb shell svc usb setFunctions ncm` (desfazer: `adb shell svc usb setFunctions`).

**Dicas**

- **Teclado:** com a janela da interface em foco, **R** inicia, **S** grava/salva e **Q**
  encerra a teleoperação (mesmas regras dos botões; Q pede confirmação).
- **Tarefas prontas:** 3 Mesas (mão fixa, locomoção), Cilindro (Dex1, base fixa) e Mover
  cilindro (Dex1, locomoção). Qualquer outra pode ser usada digitando o gym id em `--task`
  no Avançado; para deixá-la fixa na lista, adicione uma entrada em `TASK_PRESETS` em
  [gui/commands.py](../gui/commands.py) e reinicie a interface.
- **Resolução da câmera:** em 3 Mesas e Mover cilindro, o campo Simulação escolhe 640x480
  (padrão, mais leve) ou 960x720 (mais nítida, mas a simulação fica mais pesada) por olho.
  Vale ao iniciar a simulação. Pelo terminal, use `SIM_HEAD_CAM_RES=960x720 python sim_main.py ...`. A tarefa Cilindro fica em
  640x480.
- **Na TV:** abra como aplicativo, sem barra de endereço (Alt+F4 fecha; `--kiosk` no lugar de
  `--app` abre em tela cheia):
  ```bash
  google-chrome --app=http://localhost:8080 --user-data-dir=$HOME/.config/teleop-gui-chrome
  ```
- **Encerrar a interface:** Ctrl+C no terminal do `gui/app.py` — ela encerra antes os
  processos que estiverem rodando.

Os comandos abaixo continuam valendo para rodar pelo terminal.

## Ordem de inicialização (terminal)

**T1 (simulação) → T2 (ponte WebRTC) → app no Quest → T3 (teleop)**

O teleop precisa do servidor de imagens da simulação para iniciar, por isso a simulação sobe primeiro.

### T1 — Simulação

```bash
conda activate unitree_sim_env
cd ~/workspace/svr/unitree_sim_isaaclab
python sim_main.py --device cpu --enable_cameras \
  --task Isaac-Custom-3Tables-G129-Dex1-Wholebody --robot_type g129
```

Espere a cena aparecer e o robô ficar de pé (pode levar alguns minutos).

> O robô dessa tarefa tem **mão fixa**: não use `--enable_dex1_dds` aqui nem `--ee` no T3.
> Para a tarefa do cilindro com garra: `--task Isaac-PickPlace-Cylinder-G129-Dex1-Joint --enable_dex1_dds` e `--ee dex1` no T3.

### T2 — Ponte WebRTC (vídeo para o Quest + poses para o teleop)

```bash
conda activate tv_unity_svr
cd ~/workspace/svr/xr_teleoperate
python python_webrtc.py --host 0.0.0.0 --port 8765 \
  --send-video --stereo-video \
  --img-server-ip 127.0.0.1 --ice-host <IP_PC> \
  --forward-url ws://127.0.0.1:9876
```

Avisos `Forwarder disconnected ... 9876` são normais até o T3 subir.

### Quest

1. Abra o app (Biblioteca → **Fontes desconhecidas** → Teleop).
2. No menu de conexão, informe `<IP_PC>` e porta `8765` e confirme.
3. A câmera do robô deve aparecer em estéreo. Pegue os **controles**.

### T3 — Teleoperação

```bash
conda activate tv_unity_svr
cd ~/workspace/svr/xr_teleoperate/teleop
python teleop_hand_and_arm.py --sim --tracking-source unity \
  --unity-host 127.0.0.1 --unity-port 9876 \
  --input-mode controller --arm G1_29 --motion \
  --img-server-ip 127.0.0.1 --headless
```

Com os braços em posição neutra, aperte **R** no T3.

> `--headless` no teleop só desliga o visualizador Rerun da gravação. Sem ele, com
> `--record`, o Rerun tenta usar a porta 9876 — a mesma da ponte Unity — e gera erros de
> handshake no log.

## Controles

| Onde | Ação | Efeito |
|---|---|---|
| Terminal T3 | `R` | inicia a teleoperação |
| Terminal T3 | `S` | inicia/para a gravação de um episódio (só com `--record`) |
| Terminal T3 | `Q` | encerra |
| Controles | pose dos controles | braços do robô seguem |
| Controles | thumbstick esquerdo | anda (frente/trás/lados) |
| Controles | thumbstick direito (horizontal) | gira o robô |
| Controles | gatilho | garra (só em tarefas com Dex1) |
| Controles | **botão A (direito)** | **encerra a teleoperação** — cuidado na demo |

## Gravar e reproduzir (replay determinístico)

**Gravar:** acrescente ao comando do T3:
```bash
  --record --task-name tres_mesas
```
`R` para iniciar → `S` para começar a gravar → `S` para salvar → `Q` para sair.
Os episódios ficam em `teleop/utils/data/tres_mesas/episode_XXXX/`.

**Reproduzir** (encerre tudo antes; só precisa da simulação):
```bash
conda activate unitree_sim_env
cd ~/workspace/svr/unitree_sim_isaaclab
python sim_main.py --device cpu --enable_cameras \
  --task Isaac-Custom-3Tables-G129-Dex1-Wholebody --robot_type g129 \
  --replay_data --file_path ~/workspace/svr/xr_teleoperate/teleop/utils/data/tres_mesas \
  --step_hz 30
```
A `--task` precisa ser a mesma da gravação.

## Encerrar

`Ctrl+C` em T3 → T2 → T1 e feche o app no Quest. Se algo ficar preso:
```bash
ps -eo pid,args | grep -E "sim_main|python_webrtc|teleop_hand_and_arm" | grep -v grep
kill -INT <pid>        # se não fechar: kill -TERM <pid>
```

## Problemas comuns

| Sintoma | Causa / solução |
|---|---|
| App fica com tela preta | Normal antes de conectar: confirme o endereço no menu de conexão |
| T2 não mostra `Cliente conectado` | Quest em outra rede, IP errado no menu, ou firewall bloqueando a 8765 |
| Conecta mas o vídeo não chega | Confira `--ice-host <IP_PC>` (o PC tem Tailscale/Docker e o ICE pode escolher a interface errada) |
| T3 falha no início com `ImageClient`/`cam_config` | A simulação ainda não terminou de carregar |
| `Forwarder disconnected` não para | O T3 não subiu ou não está na porta 9876 |
| Sim: `Failed to create action provider: 'left_hand_Joint1_1'` | Passou `--enable_dex1_dds` numa tarefa de mão fixa |
| Cotovelo não acompanha o do operador | Offset do pulso desligado: o padrão é `--unity-wrist-pitch-offset 60` |
| Robô não anda | Faltou `--input-mode controller --motion` no T3, ou a tarefa não é `Wholebody` |
| Teleop com `--record` mostra `opening handshake failed` | Rerun usando a porta 9876: rode o teleop com `--headless` |
| Um terminal fecha sozinho quando a simulação encerra | O `sim_main.py` mata no final todo processo com `sim_main.py` na linha de comando (ex.: um `grep sim_main.py`) |
| Replay não fecha com Ctrl+C | A simulação trava em `simulation_app.close()`; use `kill -9` (a interface faz isso sozinha) |

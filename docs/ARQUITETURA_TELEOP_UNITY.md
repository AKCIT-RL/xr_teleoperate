# Arquitetura — Teleoperação do G1 com Unity (Meta Quest) e IsaacLab

**Foco: WebRTC e a ponte Unity ↔ teleop.** Este documento explica como o app no Quest e o
PC se conectam, o que acontece em cada etapa da sessão WebRTC, como o `python_webrtc.py`
funciona por dentro e como as poses chegam ao teleop (e o feedback volta). ZMQ, DDS e a
lógica de controle aparecem só de forma resumida.

Para apenas rodar o sistema, veja [GUIA_RAPIDO_TELEOP_UNITY.md](GUIA_RAPIDO_TELEOP_UNITY.md).

Estado descrito: branch `teleop_unity_real`, APK `com.Asteroyde.Teleop2`, setembro/2026.
O que foi **inferido do código sem teste** está marcado como tal.

---

## 1. Visão geral

```
 ┌──────────────── Meta Quest ────────────────┐
 │ App Unity (Teleop2)                        │
 │  WebRTCSignalingUnity  TrackerSender       │
 └──────┬──────────────────────────▲──────────┘
   (A)  │ WebSocket :8765          │ (B) WebRTC sobre UDP
        │ sinalização (JSON)       │     vídeo (SRTP)  ◄── PC
        │                          │     DataChannel "tracker" (SCTP) ◄──► poses / feedback
 ═══════╪════════ Wi‑Fi ═══════════╪══════════════════════════════════════
 ┌──────▼──────────────────────────┴──────────┐
 │ python_webrtc.py        (um event loop asyncio)
 │  • servidor de sinalização (websockets)    │◄── ZMQ :55555 imagens da simulação
 │  • RTCPeerConnection (aiortc)              │
 │  • trilha de vídeo ImageClientVideoTrack   │
 │  • BridgeForwarder  ─────────────┐         │
 └──────────────────────────────────┼─────────┘
   (C) WebSocket 127.0.0.1:9876     │  poses ↓   feedback ↑
 ┌──────────────────────────────────▼─────────┐
 │ teleop_hand_and_arm.py                     │
 │  • UnityTeleVuerBridge (thread + loop próprio)
 │  • loop principal 30 Hz: get_tele_data → IK → braços/locomoção
 └──────────────────────────┬─────────────────┘
                            │ DDS domínio 1
 ┌──────────────────────────▼─────────────────┐
 │ sim_main.py (IsaacLab)                     │
 └────────────────────────────────────────────┘
```

**Três conexões que interessam aqui:**

| | Entre | Protocolo | Transporte | Passa pela rede? |
|---|---|---|---|---|
| **A** | Unity → `python_webrtc.py` | WebSocket `ws://` (sem TLS), JSON | TCP, porta 8765 | **Sim** (LAN) |
| **B** | Unity ↔ `python_webrtc.py` | WebRTC: ICE → DTLS → SRTP + SCTP | UDP, portas dinâmicas | **Sim** (LAN) |
| **C** | `python_webrtc.py` ↔ teleop | WebSocket, JSON | TCP, `127.0.0.1:9876` | Não (loopback) |

A **ponte** tem duas metades: o `python_webrtc.py` termina a sessão WebRTC e fala com o
Quest; o `UnityTeleVuerBridge`, dentro do teleop, recebe as poses e as entrega ao código de
controle como se viessem do TeleVuer. A conexão C liga as duas metades.

---

## 2. WebRTC em uma página

WebRTC é um conjunto de protocolos para dois pares trocarem mídia e dados diretamente, com
baixa latência, mesmo atrás de NAT. Mapeado para este sistema:

| Peça | Para que serve | Aqui |
|---|---|---|
| **Sinalização** | Os pares precisam trocar descrições da sessão e endereços *antes* de terem um canal direto. O WebRTC não define como — cada aplicação escolhe. | WebSocket simples no 8765 (conexão A) |
| **SDP** (*Session Description Protocol*) | Texto que descreve a sessão: quais fluxos existem (vídeo, dados), codecs, direção, credenciais ICE, impressão digital do certificado DTLS | *offer* do Unity, *answer* do Python |
| **Offer/Answer** | Um lado propõe (offer), o outro aceita um subconjunto compatível (answer) | Unity oferece, Python responde |
| **ICE** | Descobre endereços possíveis de cada lado (*candidatos*) e testa pares até achar um que funcione | Candidatos `host` na LAN resolvem |
| **STUN** | Servidor que devolve "com que IP/porta você aparece do lado de fora" (para NAT) | Google STUN, configurado mas desnecessário na LAN |
| **TURN** | Servidor que retransmite a mídia quando não há caminho direto | Opcional, não usado na LAN |
| **DTLS** | Handshake TLS sobre UDP; gera as chaves e autentica o par pelo *fingerprint* que veio no SDP | Automático (aiortc / Unity WebRTC) |
| **SRTP** | RTP criptografado — transporta o vídeo | Vídeo PC → Quest |
| **SCTP** (sobre DTLS) | Transporte das mensagens do *DataChannel* | Canal `tracker` |
| **BUNDLE** | Vídeo e dados compartilham o mesmo par de portas UDP | Sim |

Resumo: **o WebSocket A só serve para combinar a conexão; depois disso, vídeo e poses andam
pelo UDP (B).** Mas, neste código, o A continua sendo necessário durante toda a sessão
(seção 7).

---

## 3. A negociação passo a passo

```
 Unity (Quest)                                        python_webrtc.py (PC)
   │ operador confirma IP:8765 no ConnectionMenuUI       │
   │── WebSocket connect ───────────────────────────────►│ handle_client(): cria RTCPeerConnection
   │                                                      │
   │ 1. CreateDataChannel("tracker")                      │
   │ 2. AddTransceiver(Video, RecvOnly)                   │
   │ 3. CreateOffer + SetLocalDescription                 │
   │── {"type":"offer","sdp":...} ───────────────────────►│ 4. setRemoteDescription(offer)
   │── {"type":"candidate",...}  (vários, "trickle") ────►│ 5. addIceCandidate (antes do offer: guarda)
   │                                                      │ 6. se o offer tem m=video: addTrack(vídeo)
   │                                                      │    + preferência de codec
   │                                                      │ 7. createAnswer + setLocalDescription
   │                                                      │ 8. espera a coleta de candidatos TERMINAR
   │                                                      │    (interfaces locais + STUN)
   │                                                      │ 9. limpa o SDP; aplica --ice-host
   │◄── {"type":"answer","sdp": ... com candidatos} ──────│
   │                                                      │
   │═════ 10. ICE: checagens STUN entre pares de candidatos (UDP) ══════│
   │═════ 11. DTLS handshake (chaves; confere fingerprint do SDP) ══════│
   │═════ 12. SCTP associa → DataChannel "tracker" OPEN ════════════════│ on_datachannel / on_open
   │◄════ 13. SRTP: vídeo ══════════════════════════════════════════════│
   │═════ 14. DataChannel: poses + botões a cada frame ════════════════►│ on_message
   │◄════ 15. DataChannel: feedback (torques, háptico) ═════════════════│
```

Detalhes que importam:

- **Quem decide o quê.** O Unity é quem declara que quer **receber** vídeo (`RecvOnly`) e quem
  **cria** o DataChannel. O Python só adiciona a trilha de vídeo se o offer tiver `m=video`;
  se não tiver, loga `Offer sem m=video` e a sessão sobe só com dados.
- **Trickle só num sentido.** O Unity manda candidatos à medida que os descobre. O `aiortc`
  (Python) não faz trickle: ele **espera terminar de coletar** e manda todos **dentro do SDP da
  answer**. Candidatos do Unity que chegam antes do offer ficam em `pending_candidates` e são
  aplicados logo após o passo 4. `{"type":"candidate","candidate":null}` indica fim.
- **"Limpeza" do SDP** (`clean_sdp_for_unity`): remove `a=extmap-allow-mixed` e
  `a=ice-options`, atributos que o `aiortc` gera e o Unity WebRTC não aceita bem.
- **Filtro de candidatos** (`is_valid_candidate`): descarta IPv4 link‑local (`169.254.*`) e IPv6
  local (`fe80:`, `fc00:`, `fd00:`) nos dois sentidos.
- **Ao abrir o DataChannel** o Python envia duas mensagens de teste (`Hello from Python!`,
  `Oi do Python!`) e esvazia a fila de feedback pendente.

### 3.1 O que há dentro do SDP (ilustrativo)

Trecho típico de uma *answer* (valores ilustrativos, não capturados deste sistema):

```
v=0
a=group:BUNDLE 0 1                    ← vídeo (0) e dados (1) no mesmo transporte
m=video 9 UDP/TLS/RTP/SAVPF 97 98     ← fluxo de vídeo; payloads 97/98 (ex.: VP8 e RTX)
a=sendonly                            ← Python só envia (espelho do RecvOnly do Unity)
a=rtpmap:97 VP8/90000                 ← codec escolhido
a=ice-ufrag:abcd  a=ice-pwd:...       ← credenciais das checagens ICE
a=fingerprint:sha-256 AB:CD:...       ← hash do certificado DTLS do Python
a=setup:active|passive                ← quem inicia o handshake DTLS
a=candidate:1 1 udp 2130706431 192.168.77.42 51234 typ host
m=application 9 UDP/DTLS/SCTP webrtc-datachannel   ← fluxo do DataChannel
a=sctp-port:5000
```

Para ver o SDP real, basta registrar `data["sdp"]` e `new_sdp` em `handle_client`.

---

## 4. ICE neste PC

### 4.1 Candidatos

| Tipo | De onde vem | Relevância aqui |
|---|---|---|
| `host` | Um por interface de rede local | **É o que conecta na LAN** |
| `srflx` | IP/porta públicos aprendidos via STUN | Só entre redes diferentes com NAT |
| `relay` | Endereço num servidor TURN | Só em NAT restritivo; toda a mídia passa pelo servidor |

O PC tem três interfaces com IPv4 — `wlp130s0` (Wi‑Fi, ex.: `192.168.77.42`), `tailscale0`
(`100.x.x.x`) e `docker0` (`172.17.0.1`) — e o `aiortc` gera um candidato `host` para cada.
Do Quest, só o do Wi‑Fi é alcançável.

### 4.2 O que `--ice-host` faz

`--ice-host <IP>` **troca o IP** de todos os candidatos `host` pelo IP informado, mantendo as
portas (no SDP da answer, em `rewrite_ice_host_in_sdp`, e em `force_ice_host`).

```
antes:  192.168.77.42:51234 (Wi‑Fi)   100.72.170.117:40111 (Tailscale)   172.17.0.1:38000 (Docker)
depois: 192.168.77.42:51234           192.168.77.42:40111                192.168.77.42:38000
```

O primeiro continua correto e conecta. Os outros apontam para portas que estão abertas em
outras interfaces, não no Wi‑Fi: as checagens neles falham. O efeito é forçar o caminho pelo
IP escolhido. Usos: IP do Wi‑Fi na LAN; IP do Tailscale quando o Quest está em outra rede na
mesma *tailnet*.

### 4.3 Checagens e escolha do par

Com os candidatos dos dois lados, cada agente ICE monta pares (local × remoto), envia
requisições STUN de conectividade em cada par (usando `ice-ufrag`/`ice-pwd` do SDP) e marca os
que respondem. O par nomeado vira o caminho da sessão. No log do Python:
`ICE state: checking → completed` e `Connection state: connecting → connected`.

### 4.4 STUN e rede sem internet

O passo 8 (esperar a coleta terminar) inclui consultar o STUN do Google. **Sem saída para a
internet**, a consulta não responde e a answer só sai quando a coleta desiste por timeout —
a conexão atrasa alguns segundos (**inferido do código, não medido**). Na LAN o STUN é
dispensável, mas hoje não dá para desligá‑lo por flag (`--ice-server` substitui a lista, não a
esvazia).

---

## 5. O vídeo (PC → Quest)

### 5.1 Pipeline

```
simulação: render → JPEG ─ZMQ PUB :55555─► thread SUB do ImageClient (decodifica JPEG, guarda o último)
   ─► ImageClientVideoTrack.recv() pega o último quadro ─► [recorta um olho | redimensiona]
   ─► VideoFrame(pts, time_base) ─► encoder VP8/H264 do aiortc (CPU) ─► RTP/SRTP ─► Quest
   ─► jitter buffer + decoder do Unity ─► textura na tela curva
```

### 5.2 Como a trilha funciona no aiortc

O `aiortc` usa um modelo **pull**: para cada trilha enviada, o `RTCRtpSender` fica num laço
chamando `await track.recv()`, codificando o quadro devolvido e mandando os pacotes RTP.

- `ImageClientVideoTrack.recv()` pede o quadro mais recente ao `ImageClient` numa thread
  (`asyncio.to_thread`, porque a chamada é bloqueante) — a leitura devolve **imediatamente** o
  último quadro já decodificado (buffer triplo), sem esperar um quadro novo.
- Cada quadro recebe `pts` sequencial com `time_base = 1/--video-fps`: o receptor interpreta os
  quadros como espaçados de 1/30 s.
- **Observação (a verificar):** diferente da `StaticImageVideoTrack`, que dorme `1/fps` a cada
  quadro, a trilha ao vivo **não limita o próprio ritmo**. O ritmo real fica sendo o que o
  encoder aguenta, possivelmente acima de 30 quadros/s, com quadros repetidos; e os
  timestamps (1/30 s por quadro) podem andar mais devagar que o tempo real. Isso gastaria CPU
  e pode fazer o *jitter buffer* do Unity acumular atraso. Verificação: o log
  `[ImageClientVideoTrack] sent N frames`, impresso a cada segundo, mostra quadros por
  segundo; se N ficar bem acima de 30, o ritmo não está limitado.

### 5.3 Estéreo, codec e resolução

- A simulação publica o par binocular lado a lado (480×1280). Com `--stereo-video`, a trilha
  envia o par inteiro; sem ele, recorta o olho esquerdo. O botão do app manda
  `{"type":"stereo_vision","enabled":...}` e `set_stereo_mode` troca isso **ao vivo**,
  recortando os pixels no Python (o Unity sempre exibe o que chega).
- Codec: `--video-codec auto` prefere **VP8** (H264 se VP8 não existir); `vp8`/`h264` forçam.
  Aplicado em `apply_video_codec_preferences` sobre o transceiver do vídeo.
- `--video-max-width/--video-max-height` reduzem a resolução antes de codificar (enlaces
  fracos).
- RTP tolera perda: um pacote perdido estraga parte de um quadro; o fluxo continua.

---

## 6. O DataChannel `tracker` (Quest ↔ PC)

- Criado pelo Unity com as **opções padrão: confiável e ordenado** (SCTP retransmite o que se
  perde e entrega em ordem).
- **Por que isso importa:** com perda de pacote no Wi‑Fi, as poses seguintes ficam retidas até
  a retransmissão chegar (*head‑of‑line blocking*). Em teleoperação, pose velha não serve — o
  ideal seria **não ordenado e sem retransmissão** (`ordered=false`, `maxRetransmits=0`): perde
  uma pose, a próxima chega logo em seguida. Com Wi‑Fi limpo não se nota; com interferência,
  aparecem "travadinhas" nos braços (**análise do código, não medido**). A mudança é no app.
- **Quest → PC**, a cada frame do app: poses (`head`, `left`, `right`) + botões; e
  `stereo_vision` quando o botão é usado.
- **PC → Quest**: `joint_torques` (a cada ciclo do teleop, 30 Hz) e `haptic_alert`.
- **Log das mensagens:** imprimir cada pose e cada feedback (dezenas por segundo) ocupava o
  event loop e o terminal. Agora isso só acontece com `--log-messages`; por padrão a ponte
  imprime a cada 5 s um resumo `[stats] poses N/s · feedback M/s`, que a interface usa para
  mostrar o estado da conexão. No teleop, o print por feedback (`📳 Unity bridge feedback
  queued`, 30/s) foi removido.

Formatos na seção 12.

---

## 7. Dentro do `python_webrtc.py`

### 7.1 Um único event loop

Tudo roda num **único event loop asyncio** (processo single‑thread, exceto as leituras de
imagem em `asyncio.to_thread` e as threads internas do `ImageClient`):

| Tarefa no loop | O que faz |
|---|---|
| Servidor `websockets` (8765) | uma corrotina `handle_client` por conexão de sinalização |
| `aiortc` (por sessão) | ICE, DTLS, SCTP, laço do `RTCRtpSender` do vídeo |
| `BridgeForwarder._run` | conecta ao teleop, envia poses da fila |
| `BridgeForwarder._receive` | recebe feedback do teleop e manda ao Unity |

Consequência: **qualquer trecho lento bloqueia tudo** — sinalização, vídeo, poses e feedback.
Por isso a leitura de imagem vai para thread, e por isso o log por mensagem ficou opcional
(`--log-messages`).

### 7.2 Estado global e "uma sessão por vez"

O processo guarda em variáveis globais: `video_track` (criada uma vez no início),
`unity_datachannel` (o canal da sessão mais recente), `unity_pending_messages` (feedback à
espera, no máximo 64, descartando o mais antigo) e `forwarder`.

- Cada conexão no 8765 cria um `RTCPeerConnection` novo, mas o **último** DataChannel aberto
  sobrescreve `unity_datachannel` — o feedback vai só para ele.
- A mesma `video_track` é usada por todas as sessões.
- Na prática: **um Quest por vez.** Um segundo cliente no 8765 "rouba" o canal de volta. Como o
  8765 é `ws://` sem autenticação e escuta em todas as interfaces, qualquer dispositivo da
  rede consegue fazer isso.

### 7.3 Ciclo de vida da sessão — ponto crítico

A `RTCPeerConnection` vive **dentro** da corrotina `handle_client`, que roda enquanto o
**WebSocket de sinalização** estiver aberto. Quando esse WebSocket fecha (app fechado,
`bye`, erro, **ou uma queda momentânea de TCP no Wi‑Fi**), o `finally` executa `pc.close()` e
**a sessão WebRTC inteira cai**, mesmo que o UDP estivesse funcionando.

Ou seja: apesar de, conceitualmente, a sinalização só ser necessária no começo, **neste código
o WebSocket A precisa ficar de pé durante toda a teleoperação.**

O que acontece em cada evento:

| Evento | Efeito |
|---|---|
| App fecha / Quest dorme | WebSocket fecha → `pc.close()`; poses param; `unity_datachannel` fica apontando para um canal fechado e o feedback passa a ir para a fila de 64 |
| App reabre e reconecta | nova sessão; novo DataChannel substitui o global; fila de feedback é enviada. Reuso da `video_track` na sessão nova: **a verificar** (teste E5.1 do guia) |
| Wi‑Fi oscila | se o TCP do 8765 cair, a sessão cai (acima); se só o UDP oscilar, o ICE pode se recuperar sozinho |
| `python_webrtc.py` reinicia | Quest perde tudo; reconectar pelo menu do app |
| Teleop reinicia | sessão WebRTC continua; o forwarder reconecta em ≤ 1 s (seção 8) |

---

## 8. A ponte até o teleop (conexão C)

### 8.1 Lado `python_webrtc.py`: `BridgeForwarder`

Cliente WebSocket para `--forward-url` (`ws://127.0.0.1:9876`).

- **Filtro:** só mensagens JSON com `head`, `left` e `right` são repassadas (`is_pose_payload`).
  O resto (ex.: `stereo_vision`) é tratado localmente.
- **Fila de 8 com descarte do mais antigo:** se o teleop atrasar, ele recebe a pose mais recente
  em vez de acumular atraso.
- **Reconexão a cada 1 s** enquanto o teleop não estiver no ar — os avisos
  `Forwarder disconnected: [Errno 111] ... 9876`. Por isso a ponte pode subir antes do teleop e
  o teleop pode ser reiniciado sozinho.
- **Volta:** tudo que chega do teleop e **não** é pose vai para o Unity (`send_to_unity`); se o
  DataChannel não estiver aberto, entra na fila de 64.

### 8.2 Lado teleop: `UnityTeleVuerBridge`

```
 thread "bridge" (daemon)                          thread principal do teleop (30 Hz)
 ┌───────────────────────────────┐                 ┌──────────────────────────────┐
 │ event loop asyncio próprio    │                 │                              │
 │ websockets.serve(127.0.0.1:9876)                │                              │
 │ _handle_client:               │   lock          │ get_tele_data():             │
 │   JSON → 3 matrizes (order=F) │──► estado ◄─────│   copia estado sob lock      │
 │   atualiza botões presentes   │   (último valor)│   converte → TeleData        │
 │                               │                 │                              │
 │ _broadcast_feedback  ◄────────┼─ run_coroutine_ │ send_feedback(dict)          │
 │   envia a todos os clientes   │   threadsafe ───│                              │
 └───────────────────────────────┘                 └──────────────────────────────┘
```

- **Thread e loop próprios:** o teleop é síncrono; a ponte roda seu servidor WebSocket numa
  thread daemon com event loop próprio, iniciada no construtor.
- **Estado de "último valor":** cada mensagem sobrescreve as três matrizes e os botões presentes
  (campos ausentes mantêm o valor anterior). Mensagens sem `left`/`right` ou com matriz de
  tamanho errado são ignoradas; `head` é opcional.
- **Decodificação:** cada lista de 16 números vira 4×4 com `reshape(order="F")` (column‑major,
  como o Unity envia).
- **Leitura:** o loop do teleop chama `get_tele_data()` a 30 Hz, copia o estado sob `lock` e
  aplica as conversões (seção 11). A taxa de envio do Unity e a do teleop são **independentes**:
  poses intermediárias são simplesmente sobrescritas.
- **Feedback:** `send_feedback()` é chamado da thread principal; como o socket pertence ao loop
  da ponte, o envio é agendado nesse loop com `asyncio.run_coroutine_threadsafe` e vai para
  **todos** os clientes conectados (na prática, o forwarder).
- **Antes da primeira pose:** o estado começa com poses constantes padrão; o teleop só deve
  receber `R` depois que o Quest estiver conectado e mandando poses.

---

## 9. Cenários de conexão Quest ↔ PC

| Cenário | Sinalização (A) | Mídia e dados (B) | Situação |
|---|---|---|---|
| **Wi‑Fi, mesma LAN** | `IP_PC:8765` no menu do app | UDP na LAN, candidatos `host` | **Validado.** Recomendado |
| **Cabo USB + Wi‑Fi** | `adb reverse tcp:8765 tcp:8765`; app em `127.0.0.1:8765` | UDP **pelo Wi‑Fi** | Validado. O cabo carrega só a sinalização |
| **Só cabo USB** | `adb reverse` | **não funciona** | `adb reverse` é só TCP; ICE e mídia são UDP |
| **Redes diferentes (Tailscale)** | `ws://<IP_tailscale_PC>:8765` | UDP pelo túnel, `--ice-host <IP_tailscale_PC>` | Ver [TAILSCALE_DIAGNOSTICS.md](../TAILSCALE_DIAGNOSTICS.md); não validado aqui |
| **Redes diferentes (NAT)** | 8765 exposto (IP público/túnel) | STUN (`srflx`) ou TURN (`relay`) | NAT restritivo exige TURN (`--turn-*` e campos `turnUrls` no app) |

No cenário com cabo, a queda de sinalização por Wi‑Fi (seção 7.3) deixa de ser um risco,
porque o TCP do 8765 passa pelo USB.

---

## 10. Outros canais (resumo)

**ZMQ (imagens, local):** o servidor `teleimager` dentro do `sim_main.py` publica JPEG
480×1280 em PUB `:55555` e responde a configuração das câmeras em REP `:60000`. A ponte e o
teleop são assinantes (SUB) e fazem o REQ de configuração ao iniciar — por isso só sobem
depois da simulação. PUB/SUB com `HWM=1`: só o último quadro, sem acumular atraso.

**DDS (teleop ↔ simulação, domínio 1):** tópicos `rt/lowcmd`, `rt/lowstate`,
`rt/run_command/cmd`, `rt/sim_state`, `rt/reset_pose/cmd` (e `rt/dex1/*` com garra). Dois
pontos de rede para a demo: sem `--network-interface`, a `unitree_sdk2py` usa
`autodetermine` e a descoberta sai pela interface principal (o Wi‑Fi), mesmo com os dois
processos no mesmo PC — então **outro DDS no domínio 1 na mesma rede enxerga os tópicos**, e
uma queda do Wi‑Fi pode afetar teleop ↔ simulação. O `sim_main.py` não aceita interface hoje.

**Gravação:** o teleop guarda `rt/sim_state` num bloco de memória compartilhada de 16 KB e o
anexa a cada quadro gravado (≈ 2,6 KB na tarefa das três mesas).

---

## 11. Resumo do lado de controle

- `--tracking-source unity` troca o `TeleVuerWrapper` pelo `UnityTeleVuerBridge`, com o mesmo
  `get_tele_data()`. IK, controle do braço, locomoção e gravação são o código original.
- Conversões em `get_tele_data()`: base OpenXR → robô; **offset de pitch do pulso**
  (`--unity-wrist-pitch-offset`, padrão 60°); posição relativa à cabeça; `+0,15 m` x e
  `+0,45 m` z até a cintura; gatilho 0..1 → 10..0; eixo y dos sticks invertido.
- **Por que 60°:** comparado ao TeleVuer no mesmo movimento, a orientação do pulso vinda do
  Unity tinha desvio constante de ≈ 60° em pitch (provavelmente pose *aim* em vez de *grip*).
  A IK pesa posição 50× mais que rotação, então a mão acertava e o erro ia para o cotovelo.
  Com a compensação, a diferença média das juntas caiu de 10–39° para 2–10°. Correção
  definitiva: o app enviar a pose de *grip*.
- **Replay determinístico:** o `sim_main.py --replay_data` impõe o `sim_state` gravado quadro a
  quadro, sem física. Reaplicar só os comandos não seria determinístico — os canais das seções
  6 a 10 são assíncronos e com taxas independentes.

---

## 12. Formatos de mensagem

**Sinalização (A):**
```json
{"type": "offer",  "sdp": "..."}
{"type": "answer", "sdp": "..."}
{"type": "candidate", "candidate": "candidate:...", "sdpMid": "0", "sdpMLineIndex": 0}
{"type": "candidate", "candidate": null}
{"type": "bye"}
```

**Poses (DataChannel → forwarder → teleop):**
```json
{
  "head": [16 floats], "left": [16 floats], "right": [16 floats],
  "leftTrigger": 0.0, "rightTrigger": 0.0,
  "leftStickX": 0.0, "leftStickY": 0.0, "rightStickX": 0.0, "rightStickY": 0.0,
  "leftPrimary": false, "leftSecondary": false,
  "rightPrimary": false, "rightSecondary": false,
  "leftStickClick": false, "rightStickClick": false
}
```
Matrizes 4×4 column‑major na convenção OpenXR (o Unity converte da sua convenção de mão
esquerda com `S·M·S`, `S = diag(1,1,−1,1)`).

**Controle (DataChannel, tratado na ponte):** `{"type": "stereo_vision", "enabled": true}`

**Feedback (teleop → forwarder → DataChannel):**
```json
{"type": "joint_torques", "left": [7 floats], "right": [7 floats]}
{"type": "haptic_alert", ...}
```

---

## 13. Diagnóstico da cadeia WebRTC + ponte

Siga em ordem — cada etapa depende da anterior. As mensagens são do terminal do
`python_webrtc.py`, salvo indicação.

| # | Etapa | Sucesso | Se falhar |
|---|---|---|---|
| 1 | Quest alcança o PC | `ping <IP_QUEST>` responde | redes diferentes ou isolamento de clientes |
| 2 | Sinalização | `🌐 Cliente conectado` | IP/porta errados no menu do app; firewall no 8765 |
| 3 | Offer/answer | `📥 OFFER recebida` → `📤 Answer filtrada enviada` | demora entre as duas = coleta ICE esperando STUN (4.4) |
| 4 | ICE | `ICE state: completed`, `Connection state: connected` | `--ice-host` ausente/errado; UDP bloqueado |
| 5 | DataChannel | `💬 DataChannel criado: tracker` → `🔥 PYTHON: DataChannel OPEN` | DTLS/SCTP falhou (raro se o ICE completou) |
| 6 | Poses chegando | `📥 Unity → Python: {"head":...}` contínuo | app sem tracking (controles desligados/fora de vista) |
| 7 | Vídeo | `🎥 Video track adicionada`; `sent N frames` a cada segundo; no Quest, `adb logcat -s Unity` com `textureNull=false` | offer sem `m=video`; servidor de imagens fora do ar |
| 8 | Ponte → teleop | somem os `Forwarder disconnected`; aparece `Forwarder connected` | teleop não subiu ou porta diferente de 9876 |
| 9 | Feedback | `📤 Python → Unity payload: {"type":"joint_torques"...}` | canal fechado → `📦 ... queued` |

Comandos úteis:
```bash
ss -ltnp | grep -E ':(8765|9876) '              # sinalização e ponte escutando
ss -lunp | grep python                          # sockets UDP do ICE
ip -4 -br addr                                  # IPs das interfaces (para --ice-host)
sudo tcpdump -ni wlp130s0 udp and host <IP_QUEST>   # mídia WebRTC de fato passando
```

---

## 14. Riscos para a demonstração (WebRTC e ponte)

| Risco | Efeito | Recomendação |
|---|---|---|
| Isolamento de clientes na rede do evento | Quest não alcança o 8765 | **Roteador próprio** |
| Rede sem internet | Conexão atrasa (coleta espera o STUN) | Roteador com internet, ou remover o STUN padrão no código |
| Queda momentânea do TCP de sinalização | Sessão WebRTC inteira cai (7.3) | Wi‑Fi estável e dedicado; ou sinalização pelo cabo (`adb reverse`) |
| Interferência no Wi‑Fi | "Travadinhas" nas poses (canal ordenado) e artefatos no vídeo | 5 GHz livre, Quest perto do roteador; médio prazo: DataChannel não ordenado |
| Várias interfaces no PC | ICE demora ou escolhe errado | Sempre `--ice-host <IP_Wi‑Fi>` |
| Outro cliente no 8765 | Sessão/feedback "roubados" | Rede isolada; firewall liberando só o IP do Quest |
| `--log-messages` ligado | Event loop ocupado → latência (não medido) | Deixar desligado na demo (padrão) |
| Ritmo do vídeo não limitado | CPU alta / atraso acumulado no Quest (a verificar, 5.2) | Checar o `sent N frames` impresso a cada segundo |

Portas que precisam estar acessíveis pela LAN: **8765/TCP** e **UDP efêmero** (mídia). O
9876 escuta só em `127.0.0.1`. Com `ufw` ativo:
```bash
sudo ufw allow from <IP_QUEST> to any port 8765 proto tcp
sudo ufw allow from <IP_QUEST> proto udp
```

---

## 15. Arquivos-chave

| Arquivo | O que tem |
|---|---|
| [python_webrtc.py](../python_webrtc.py) | `handle_client` (sinalização e sessão), ICE (`force_ice_host`, `rewrite_ice_host_in_sdp`, `is_valid_candidate`), `clean_sdp_for_unity`, trilhas de vídeo, `BridgeForwarder`, `send_to_unity` |
| [teleop/utils/unity_televuer_bridge.py](../teleop/utils/unity_televuer_bridge.py) | servidor 9876, estado das poses/botões, `get_tele_data`, `send_feedback` |
| [teleop/teleimager/src/teleimager/image_client.py](../teleop/teleimager/src/teleimager/image_client.py) | assinatura ZMQ e buffer do último quadro |
| `Unity/Assets/WebRTC/WebRTCSignalingUnity.cs`, `TrackerSender.cs` | lado Unity — versão **anterior** ao APK `Teleop2` (sem menu de conexão nem botões) |

---

## 16. Pendências (WebRTC e ponte)

- App: DataChannel de poses não ordenado e sem retransmissão; enviar a pose de *grip*.
- Ponte: desacoplar a vida da sessão WebRTC do WebSocket de sinalização (ou reconexão
  automática no app); opção para desligar o STUN; limitar o ritmo da trilha ao vivo ao
  `--video-fps` se a verificação da seção 5.2 confirmar o problema.
- Teleop: com `--record` e sem `--headless`, o Rerun tenta usar a porta 9876 da ponte Unity
  (a interface sobe o teleop com `--headless`; ver [gui/README.md](../gui/README.md)).
- [UNITY_TELEVUER_INTEGRATION.md](UNITY_TELEVUER_INTEGRATION.md) está parcialmente
  desatualizado (o Unity já envia botões; a conexão agora é pelo menu do app).

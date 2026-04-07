![alt text](img/arquitetura_xr_teleoperate.drawio.png)

# Cliente de Teleoperação Nativo para Meta Quest 3 / Apple Vision Pro (Unity)

Descrição do **pipeline de teleoperação XR** desenvolvido em Unity para controlar robôs reais usando headsets como o Meta Quest 3 e o Apple Vision Pro. O sistema combina **streaming de câmeras**, **cinemática inversa**, **controle postural**, **hand-tracking**, e **serviços adicionais de percepção**, permitindo teleoperação de braços, mãos e corpo com alto grau de responsividade.

# 1. Pipeline Geral de Teleoperação

O pipeline tem **4 blocos principais**:

### **1) Coleta XR no Headset (Unity)**

* Head pose (OpenXR / visionOS)
* Hand tracking (juntas completas no Quest; pontos principais no AVP)
* Controladores (se presentes)
* Inputs adicionais:

  * pinch
  * gestures
  * joystick / buttons
* Complementos (somente Unity):

  * Haptics
  * Spatial audio
  * acesso a IMU do device
  * detecção de plano / profundidade (OpenXR Extensions)

Dados são convertidos pelo `XRWrapper` → **TeleData**.

### **2) Núcleo de Teleoperação e Cinemática**

Recebe TeleData e alimenta:

* IK dos braços (Pinocchio + small residual net)
* Retargeting das mãos (modelo de retargeting Dex/Adapt)
* Solver de juntas com:

  * limites dinâmicos
  * weighted move planning
  * suavização (LP, PID)
* Controle do robô:

  * velocidade
  * posição
  * torque (em plataformas que suportam)

### **3) Teleimager (Streaming das Câmeras do Robô)**

* Streaming JPEG com metadados via ZeroMQ
* WebRTC opcional para VR direto no headset
* Câmeras:

  * cabeça
  * punho esquerdo
  * punho direito
  * câmeras adicionais (peito, traseira, etc)
* O Unity recebe via `ImageClient` e atualiza texturas em tempo real.

### **4) Mapeamento para o Robô Real**

O sistema converte todo o estado estimado para:

* braços (IK)
* mãos (retargeting)
* cabeça / tronco (opcional)
* **pés / controle postural (em desenvolvimento)**

  * Foot raycasts no Unity para sugerir ajuste do pé
  * Estimativa de deslocamento do CoM
  * “ghost feet” para prever movimento desejado do operador
  * Pode ser usado em robôs humanoides para antecipar marcha

Comunicação final via:

* DDS
* ZeroMQ
* Websocket bidirecional

# 2. Diferenças Entre Meta Quest 3 e Apple Vision Pro

## **Meta Quest 3**

**Vantagens:**

* Acesso aberto via OpenXR
* Hand tracking completo (25+ juntas por mão)
* Haptics avançado
* IMU acessível
* Melhor integração VR full-immersive

**Limitações:**

* Sem eye tracking nativo
* Hand tracking menos estável que AVP

## **Apple Vision Pro**

**Vantagens:**

* Eye tracking extremamente preciso (mas não exposto diretamente)
* Hand tracking estável
* Pass-through de alta qualidade
* Ambiente MR natural

**Limitações:**

* Apple não permite acesso direto ao raw eye tracking

  * (soluções existem, como o iTrace)
* Dados de mão menos completos
* Forte sandbox no visionOS
* Apps Unity funcionam como “volumes”, não VR full

# 3. Funcionalidades Extras Disponíveis no Unity

Usando Unity + XR Plugin conseguimos habilitar:

### **Sensores**

* IMU do headset
* Estado dos controladores (posição + botões + vibração)
* Depth / Plane Detection (quando disponível)
* Tempo real de física local (estimativa de torque e colisões)

### **Interação**

* Haptics para fornecer feedback do robô
* Raycasts XR para selecionar objetos
* Interface diegética 3D no ambiente XR
* Ajuste fino de referência de cabeça / tronco

### **Integração com o Robô**

* HUD com informações internas:

  * **Centro de massa (CoM)**
  * **Nível da bateria**
  * **Temperatura dos motores**
  * **Erro por junta**
  * **Força/torque prevista (pre-contact)**
  * **Estado do equilíbrio**

Essas informações podem aparecer como:

* um *floating panel*
* um *wrist HUD*
* overlays próximos ao robô em XR

# 4. Interface e Visualização Propostas (UI/UX)

Sugestões de interface rápida para teleoperação:

### **1. Painel de Telemetria (flutuante)**

* CoM (marker + valor numérico)
* Battery %
* Motor Temperature (heatmap simples)
* Mode: IK / Torque / Mixed
* Latência de rede
* FPS do Teleimager

### **2. Indicadores de Mão e Braço**

* Linhas de erro da IK
* Confiabilidade do hand tracking
* “Ghost arm” vs “arm real”

### **3. Indicadores de Pé / Orientação**

* marcadores do pé direito/esquerdo
* linha para centro de pressão
* avisos de estabilidade (“risk of fall”)l.

# 5. Extensão Possível: Teleoperação Full-Body Usando Avatar Unity (Simulação dos Pés)

Embora o pipeline padrão do **xr_teleoperate** seja centrado em **head + hands** (com extensões para braços e torso via IK), existe uma possibilidade interessante — ainda que não recomendada como solução principal — de criar uma versão de **teleoperação corpo-inteiro** utilizando um **avatar humanoide dentro do Unity** para estimar as poses das pernas e dos pés.

##  Ideia Geral

1. O operador é rastreado apenas com:

   * cabeça (XR)
   * mãos (XR hand tracking)

2. O Unity humanoid avatar preenche automaticamente:

   * pernas
   * joelhos
   * pés
     usando:
   * IK local (Unity Animation Rigging)
   * heurísticas de equilíbrio
   * predição baseada em postura típica humana

3. O sistema então converte essa pose virtual para comandos via:

   * IK do robô humanoide
   * limites reais das juntas
   * controlador de equilíbrio do robô

Assim, **mesmo sem trackers nas pernas**, podemos gerar “pé virtual” e enviar para o robô.

## Limitações e avisos

* **Não é a versão ideal**, pois:

  * os pés são *estímulos inferidos*, não observados
  * imprecisão aumenta conforme o movimento corporal real do humano difere da inferência
  * robôs humanoides **não toleram erros** grandes de pose de pé
* Deve ser aplicado com:

  * limites rígidos
  * filtros suaves
  * fallback para modo estático se instabilidade for detectada

# 6. Conclusão

O cliente nativo Unity para Quest/AVP fornece:

* Teleoperação responsiva
* Streaming robusto das câmeras
* IK completa com retargeting
* Suporte a robôs reais via DDS/ZMQ
* Interface rica usando dados internos do robô
* Compatibilidade multiplataforma XR

# Paper Draft — Integração Unity no `xr_teleoperate`

## 1. Introdução

Sistemas de teleoperação em realidade estendida (XR) têm evoluído para permitir controle mais preciso, imersivo e flexível de robôs. O projeto `xr_teleoperate` foi inicialmente desenvolvido para operar com dispositivos XR nativos utilizando o ecossistema `Televuer`/`Vuer`, onde o headset fornecia tanto o rastreamento quanto a interface visual. Entretanto, essa arquitetura limitava a experimentação e a extensibilidade do sistema, especialmente para pesquisas que exigem ambientes customizados ou visualizações avançadas.

Este trabalho apresenta uma nova integração que introduz **Unity como camada opcional de frontend XR**, responsável tanto pela visualização quanto pela captura de poses, **sem modificar a lógica principal de teleoperação**. O objetivo é avaliar se essa integração amplia a flexibilidade, escalabilidade e usabilidade do sistema.

---

## 2. Contexto Geral

Na arquitetura original, o XR headset fornecia poses e estados através de `TeleVuerWrapper`, que se comunicava com módulos Python responsáveis por cinemática inversa (IK), controle do braço robótico, gravação de episódios e visualização de câmera via `teleimager` ou WebRTC.

A nova arquitetura insere Unity como frontend alternativo. Unity passa a ser:

- a **fonte de tracking** de cabeça e mãos;
- o **ambiente de visualização** do robô e do cenário;
- uma interface mais flexível para experimentação XR.

O backend – incluindo IK, controle, gravação e comunicação com o robô – permanece idêntico.

---

## 3. Problema de Pesquisa

A questão explorada neste trabalho não é apenas a integração técnica de Unity, mas sim **se essa integração melhora o uso prático, a imersão e a robustez do sistema** em comparação ao pipeline original.

As perguntas de pesquisa incluem:

1. A renderização e o tracking via Unity **melhoram a imersão** percebida pelo usuário?
2. Unity **reduz o atrito de setup e depuração** em cenários experimentais?
3. A nova camada **facilita coleta de dados mais consistente e reprodutível**?
4. O sistema mantém **compatibilidade total** com os módulos originais de teleoperação?
5. A arquitetura modularizada **facilita extensões futuras**?

---

## 4. Trabalhos Anteriores e Base Técnica

### 4.1 Pipeline Original

O pipeline original era centrado no ecossistema `Televuer`. Ele fornecia:

- tracking direto de headset e controllers;
- envio contínuo de poses para o backend;
- integração com controladores de braço, efetuador e IK;
- transmissão de imagens via `teleimager`.

Essa arquitetura era eficiente e consolidada, mas **acoplada a um stack XR específico**, dificultando experimentos personalizados.

### 4.2 Nova Integração com Unity

A integração implementada adiciona uma rota paralela:

- `WebRTCSignalingUnity.cs` gerencia SDP/ICE e mídia com Python via WebRTC;
- `python_webrtc.py` negocia sessão e retransmite dados para o pipeline de teleoperação;
- `UnityTeleVuerBridge` adapta poses enviadas por Unity para o formato esperado;
- o módulo `teleop_hand_and_arm.py` passa a aceitar `--tracking-source unity`.

Essa abordagem mantém **100% da arquitetura de teleoperação intacta**, alterando apenas a origem dos dados XR.

---

## 5. Hipótese de Trabalho

A hipótese central deste paper é:

> **A integração de Unity como frontend XR melhora a experimentação e a qualidade do sistema de teleoperação, oferecendo maior controle visual, menor custo de prototipagem, maior extensibilidade e melhor potencial de coleta de dados, sem comprometer a lógica original do pipeline.**

---

## 6. Estado Atual da Implementação

A integração Unity atualmente oferece:

- comunicação WebRTC completa (SDP, ICE, vídeo);
- envio de poses Unity → Python via WebSocket;
- adaptação estruturada para o backend original;
- seleção da fonte de tracking em linha de comando;
- suporte a vídeo estéreo lado a lado.

### Limitações atuais

- tracking Unity cobre sobretudo head e wrists;
- falta suporte completo à semântica de gestos fornecida por Televuer;
- a integração cobre principalmente o caminho de braço/IK;
- ainda não oferece equivalência total ao stack original.

---

## 7. Questões de Pesquisa

### QR1 – Imersão
Unity melhora a presença, o alinhamento visual e o senso de controle?

### QR2 – Usabilidade
A separação entre frontend Unity e backend original reduz complexidade de uso?

### QR3 – Robustez
O sistema permanece estável e compatível com o pipeline legado?

### QR4 – Coleta de Dados
A arquitetura melhora consistência e qualidade de episódios gravados?

### QR5 – Extensibilidade
A modularidade adicionada facilita novos modos de interação e visualização?

---

## 8. Experimentos Propostos

### 8.1 Estudo Comparativo de Usabilidade
Comparar a tarefa em ambos pipelines (original e Unity).

**Métricas:**
- tempo para conclusão;
- número de correções manuais;
- erros de alinhamento;
- taxa de sucesso;
- carga subjetiva (NASA-TLX ou similar).

### 8.2 Avaliação de Imersão
Medir a percepção de presença e conforto visual.

**Métricas:**
- questionários de presença;
- Likert de conforto;
- preferência entre interfaces;
- clareza do ambiente.

### 8.3 Latência e Estabilidade
Avaliar desempenho do pipeline de comunicação.

**Métricas:**
- latência de ponta a ponta;
- perda de frames;
- reconexões;
- estabilidade do tracking.

### 8.4 Estudo de Coleta de Dados
Verificar consistência temporal e completude de episódios.

**Métricas:**
- sincronização pose/ação/imagem;
- completude de metadados;
- incidência de episódios corrompidos;
- reprodutibilidade.
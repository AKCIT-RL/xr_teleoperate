### **Meta Quest 3**

* **Hand tracking mais aberto**: o OpenXR expõe **todas as juntas da mão** (25+ por mão), permitindo retargeting detalhado para robôs.
* **Rastreamento menos estável** em condições de baixa luz ou com oclusões.
* **Focado em VR total**, com passthrough mais simples.
* **APIs mais abertas**: IMU, controladores, haptics completos.
* Boa precisão, mas com maior variação frame a frame.

### **Apple Vision Pro**

* **Hand tracking extremamente estável**, porém **menos granular** (não expõe todas as juntas). Ótimo para gestos, limitado para retargeting fino.
* **Lentes e passthrough muito superiores**, oferecendo percepção espacial mais natural e confortável durante teleoperação.
* **Eye tracking avançado**, mas **não acessível diretamente** (exige soluções alternativas como iTrace).
* **Interação mais suave**, porém com APIs mais fechadas e forte sandbox.

# Diferenças de Uso do *xr_teleoperate* no Apple Vision Pro vs. Meta Quest 3

Descrição das principais diferenças ao utilizar o repositório **xr_teleoperate** em dois dispositivos XR distintos: **Apple Vision Pro (AVP)** e **Meta Quest 3 (MQ3)**. O foco está nas capacidades técnicas, no acesso a sensores e nas limitações que afetam aplicações de teleoperação.


## 1. Rastreamento de Mãos

### Meta Quest 3

* Acesso nativo ao hand tracking diretamente pelo **Unity XR Hands** ou pelo **OpenXR no Quest**.
* Permite obter:

  * Pose completa da mão (joint-level)
  * Gestos
  * Confiabilidade por joint

### Apple Vision Pro

* Rastreamento de mãos funciona bem e é extremamente estável, porém:

  * A API do **visionOS** entrega *menos granularidade*.
  * Em alguns casos, não é fornecida pose de todas as juntas, apenas pontos relevantes para interação (como o “pinch”).

**Impacto no xr_teleoperate:**
→ No Quest, você pode transmitir juntas completas da mão para o robô.
→ No AVP, o estilo de interação é mais abstrato, exigindo reconstrução ou inferência de poses mais completas para teleoperação robótica.

## 2. Rastreamento Ocular (Eye Tracking)

### Meta Quest 3

* Não possui eye tracking nativo (apenas no Pro).
* Logo, o xr_teleoperate não depende disso no MQ3.

### Apple Vision Pro

* Possui eye tracking **muito avançado**, porém:

  * **A Apple não expõe acesso direto aos dados crus de eye tracking**.
  * A API permite apenas consultas indiretas (ex.: foco em UI), sem vetores contínuos.
  * Teleoperação que depende de olhar para selecionar objetos fica limitada.

**Solução possível:**
→ Sistemas como o **iTrace** permitem estimativas ou simulações de eye tracking a partir de dados disponíveis, oferecendo formas de complementar a falta de acesso direto.

**Impacto no xr_teleoperate:**
→ No AVP, “gaze-based teleop” precisa ser adaptado para usar estimativas alternativas.
→ No Quest, normalmente esse recurso já não é esperado.

## 3. Acesso ao Sistema (API / Sandbox)

### Meta Quest 3

* O Quest oferece APIs mais abertas via:

  * **OpenXR**
  * Acesso direto a:

    * Poses absolutas
    * Input detalhado
    * Hand joints completas
  * Ecossistema mais simples para Unity.

### Apple Vision Pro

* O visionOS é altamente sandboxed.
* Limitações incluem:

  * Acesso restrito a sensores
  * Restrições de processamento nativo
  * Pipeline diferente para apps Unity (especialmente renderização e interação)
  * Várias APIs só funcionam em modo “interaction-first” (UI primeiro, XR segundo)

**Impacto no xr_teleoperate:**
→ Portar scripts é simples, mas acessar dados equivalentes nem sempre é possível.
→ Alguns fluxos de teleoperação precisam ser reprojetados para o estilo de interação do AVP.

## 4. Teleoperação Corpo Inteiro / Avatar

### Meta Quest 3

* Permite:

  * Full body tracking **com extensões externas** (ex.: trackers)
  * Head + hands tracking nativos

### Apple Vision Pro

* Apenas head + hands
* Sem suporte nativo para:

  * Full body tracking
  * Lower-body inference
* Necessário:

  * Filtros
  * Inferência por modelos ML
  * Ou sistemas externos

## 5. Conclusão

Usar o **xr_teleoperate** no Meta Quest 3 é direto devido às APIs abertas e consistente com a lógica tradicional de VR.
No **Apple Vision Pro**, a experiência é diferente:

* APIs restritas
* Ausência de dados crus de eye tracking
* Interação baseada em gestos minimalistas
* Aplicações XR pensadas como extensões do ambiente real

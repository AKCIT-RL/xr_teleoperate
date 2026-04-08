# Guia de Configuração e Execução do XR Teleoperate em Simulação

## 📋 Visão Geral

Este documento descreve os passos necessários para configurar e executar o sistema XR Teleoperate integrado com o simulador IsaacLab. O guia está dividido em duas seções principais: configuração do ambiente e execução do sistema.

---

## 🚀 Configuração do Ambiente

### 1. Configuração do Ambiente de Simulação (IsaacLab)

#### Pré-requisitos
- Siga os passos de setup documentados em: https://github.com/unitreerobotics/unitree_sim_isaaclab/blob/main/doc/isaacsim5.1_install.md
- **IMPORTANTE:** Clone o fork da organização para acessar as funcionalidades desenvolvidas

#### Configuração IsaacLab 5.1

Alguns problemas comuns e suas soluções:

**Problema: Instalação do unitree_sdk2_python**
- **Solução:** Clone o repositório Cyclone em sua máquina, compile-o e configure as variáveis de ambiente. As instruções detalhadas estão no documento de instalação do IsaacLab ([aqui](https://github.com/unitreerobotics/unitree_sdk2_python?tab=readme-ov-file#faq)).

**Problema: Incompatibilidade de versão com logging_mp**
- **Solução:** Faça o downgrade para versão 0.1.6:
  ```bash
  pip install logging_mp==0.1.6
  ```

#### Preparação do Repositório

Após completar a instalação do IsaacLab:

```bash
# Mude para a branch de desenvolvimento
git checkout test/industrial_env

# Carregue os submódulos
git submodule update --init --recursive
```

#### Executar a Simulação

Execute um dos seguintes comandos conforme a tarefa desejada:

**Pick and Place com Dex1:**
```bash
python sim_main.py --device cpu --enable_cameras --task Isaac-PickPlace-Cylinder-G129-Dex1-Joint --enable_dex1_dds --robot_type g129
```

**Pick and Place com Dex3:**
```bash
python sim_main.py --device cpu --enable_cameras --task Isaac-PickPlace-Cylinder-G129-Dex3-Joint --enable_dex3_dds --robot_type g129
```

**Pick and Place com Inspire Hand:**
```bash
python sim_main.py --device cpu --enable_cameras --task Isaac-PickPlace-Cylinder-G129-Inspire-Joint --enable_inspire_dds --robot_type g129
```

**Movement com Dex1 (Full Body):**
```bash
python sim_main.py --device cpu --enable_cameras --task Isaac-Move-Cylinder-G129-Dex1-Wholebody --robot_type g129 --enable_dex1_dds
```

---

### 2. Configuração do Ambiente XR Teleoperate (Versão 1.5)

#### Clone do Repositório

```bash
git clone https://github.com/AKCIT-RL/xr_teleoperate.git
git checkout g1_binocular_v1.5
git submodule update --init --recursive
```

#### Instalação de Dependências

Siga os passos de [instalação](https://github.com/AKCIT-RL/xr_teleoperate/tree/g1_binocular_v1.5?tab=readme-ov-file#1--installation) e certifique-se de instalar as dependências de todos os repositórios:

```bash
# Criar e ativar ambiente conda
conda create -n tv python=3.10 pinocchio=3.1.0 numpy=1.26.4 -c conda-forge
conda activate tv

# Instalar teleimager
cd teleop/teleimager
pip install -e .

# Instalar televuer
cd ../televuer
pip install -e .
```

#### Configuração de Certificado SSL

```bash
# Gerar certificado SSL
openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout key.pem -out cert.pem

# Copiar para diretório de configuração
mkdir -p ~/.config/xr_teleoperate/
cp cert.pem key.pem ~/.config/xr_teleoperate/
```

#### Instalação do SDK Unitree e Dependências Principais

```bash
# Navegar até o diretório do unitree_sdk2_python
cd ../../robot_control/inspire_hand_ws/unitree_sdk2_python
pip install -e .

# Voltar para xr_teleoperate e instalar requisitos
cd ../../../
pip install -r requirements.txt
```

#### Instalação dos Modelos de Mão

**Para teleoperar com Dex Hand:**
```bash
cd robot_control/dex_retargeting
pip install -e .
```

**Para teleoperar com Inspire Hand:**
```bash
cd robot_control/inspire_hand_ws/inspire_hand_sdk
pip install -e .
```

#### Solução de Problemas de Compatibilidade

**Problema: Incompatibilidade de versão com params_proto**
- **Solução:** Instale a versão específica:
  ```bash
  pip install "params-proto==2.13.2"
  ```

---

## ▶️ Execução do Sistema

### Preparação

Abra **dois terminais**: um para a simulação e outro para a teleoperação.

```bash
# Terminal 1 - Simulação
conda activate unitree_sim_env

# Terminal 2 - Teleoperação
conda activate tv
```

### Passo 1: Iniciar a Simulação

**Terminal 1** - Execute o simulador IsaacLab:

```bash
python sim_main.py --device cpu --enable_cameras --task Isaac-Move-Cylinder-G129-Dex1-Wholebody --robot_type g129 --enable_dex1_dds
```

### Passo 2: Iniciar o Script de Teleoperação

**Terminal 2** - Execute o script de teleoperação:

```bash
cd teleop
python teleop_hand_and_arm.py --input-mode=controller --arm=G1_29 --ee=dex1 --img-server-ip="<seu_ip_wifi>" --motion --sim --record
```

> **Nota:** Substitua `<seu_ip_wifi>` pelo IP da sua interface Wi-Fi.

### Passo 3: Acessar a Interface Web (VR)

1. No seu dispositivo VR, abra um navegador web
2. Acesse o seguinte URL (substitua o IP conforme necessário):
   ```
   https://192.168.123.2:8012/?ws=wss://192.168.123.2:8012
   ```

### Controles no terminal do XR teleoperate

| Ação | Tecla |
|------|-------|
| Iniciar teleoperação | **R** |
| Parar teleoperação | **Q** |
| Gravar movimento do robô | **S** |

---

## 🎬 Reprodução de Gravações (Replay)

Para reproduzir movimentos previamente gravados, execute:

```bash
python replay.py --input-mode=controller --arm=G1_29 --ee=dex1 --motion --sim --path=utils/data/pick_cylinder/episode_0000/data.json
```

> **Nota:** Ajuste o parâmetro `--path` para o caminho do arquivo de dados que você deseja reproduzir.

---

## 📝 Resumo de Variáveis Importantes

| Variável | Opções | Descrição |
|----------|--------|-----------|
| `--arm` | `G1_29` | Modelo do braço robótico |
| `--ee` | `dex1`, `dex3`, `inspire` | Final efector (mão) |
| `--input-mode` | `controller` | Modo de entrada de controle |
| `--img-server-ip` | IP da rede | IP do servidor de imagens |
| `--device` | `cpu`, `gpu` | Dispositivo para simulação |
| `--task` | Nomes da tarefa | Tarefa a ser executada na simulação |
| `--robot_type` | `g129` | Tipo de robô (G1 com 29 DOFs) |

---

## 🔗 Referências Úteis

- [IsaacLab Installation](https://github.com/unitreerobotics/unitree_sim_isaaclab/blob/main/doc/isaacsim5.1_install.md)
- [XR Teleoperate Repository](https://github.com/AKCIT-RL/xr_teleoperate)
- [Documentação IsaacLab](https://isaac-sim.github.io/isaac-lab/)

---

**Última atualização:** 2026
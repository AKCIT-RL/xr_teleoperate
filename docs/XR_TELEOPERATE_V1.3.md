# XR Teleoperation Setup

As branches utilizadas atualmete, e que seguem esse guia, sao as branches `g1_binocular_v1.3` e `g1_monocular_v1.3`

## 1. Linkar o VR com o PC

### Comandos para rodar no shell do PC

```bash
sudo adb devices

sudo adb -s 2G0YC1ZF9J0D9D reverse tcp:8012 tcp:8012
```

### Verificar se o reverse foi criado

```bash
sudo adb -s 2G0YC1ZF9J0D9D reverse --list
```

Saída esperada:

```
UsbFfs tcp:8012 tcp:8012
```

> **OBS:**  
> É necessário configurar o certificado inicialmente.  
> O certificado dura **1 ano**, então o certificado configurado neste PC já está ativo.

---

# 2. Entrar no robô para rodar o Image Server

### Conectar via SSH

```bash
ssh -X unitree@192.168.123.164
```

ou

```bash
ssh -X unitree@192.168.123.161
```

(depende da porta ethernet utilizada)

### Rodar o servidor de imagens

```bash
cd image_server
```

**Monocular**

```bash
python image_server.py
```

**Binocular**

```bash
python image_server_binocular.py
```

---

# 3. Rodar o XR Teleoperate

### Escolher a branch

- `binocular`
- `monocular`

### Ativar o ambiente conda

```bash
conda activate tv
```

### Colocar o robô no modo de operação

Colocar no **walkmode (regular)**.

### Executar o script de teleoperação

```bash
python teleop_hand_and_arm.py --xr-mode=controller --arm=G1_29 --motion
```

---

# 4. No VR

Conectar no seguinte endereço:

Para conexao wifi
```
https://192.168.123.2:8012?ws=wss://192.168.123.2:8012
```
> Sugestão: tentar deixar esse endereço **fixo na rede**.

Caso o vr esteja conectado a cabo com o pc:
```
https://127.0.0.1:8012?ws=wss://127.0.0.1:8012
```


### Controles

- **Pressionar `r` no computador** → iniciar teleoperação  
- **Pressionar `q` no computador** → parar teleoperação
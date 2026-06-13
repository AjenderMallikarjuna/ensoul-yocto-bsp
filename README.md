# Anime.AI Yocto Workspace

Embedded Linux starting point for the Anime.AI desk companion prototype.

The pipeline per conversation turn:
**mic → Whisper STT → Claude Haiku → TTS → speaker + servo nod**

## Prototype Targets

| Target | Kas config | Use |
|--------|-----------|-----|
| `qemuarm64` | `kas/anime-ai-qemuarm64.yml` | Development, CI |
| `raspberrypi4-64` | `kas/anime-ai-rpi4.yml` | Hardware prototype |

The actuator driver auto-detects: GPIO PWM on real RPi hardware, mock (log-only) on QEMU.

## Workspace Layout

```text
.
├── kas/
│   ├── anime-ai-qemuarm64.yml
│   └── anime-ai-rpi4.yml
├── meta-anime-ai/
│   ├── conf/layer.conf
│   ├── recipes-anime/companion-daemon/
│   │   ├── companion-daemon.bb
│   │   └── files/
│   │       ├── anime-ai-companion.py   ← main daemon
│   │       ├── anime-ai-companion.service
│   │       ├── companion.toml          ← device config
│   │       └── companion/             ← Python package
│   │           ├── audio.py
│   │           ├── stt.py             ← Whisper API
│   │           ├── chat.py            ← Claude Haiku
│   │           ├── tts.py             ← OpenAI TTS / espeak-ng
│   │           ├── actuator.py        ← factory + mock driver
│   │           ├── actuator_gpio.py   ← RPi sysfs PWM servo
│   │           ├── api_server.py      ← HTTP API :8080
│   │           └── config.py
│   └── recipes-core/
│       ├── images/anime-ai-image.bb
│       └── packagegroups/packagegroup-anime-ai.bb
└── scripts/
    ├── build-qemuarm64.sh
    ├── run-qemuarm64.sh
    ├── build-rpi4.sh
    └── flash-rpi4.sh
```

## Host Requirements

Yocto builds run on Linux. On Windows, use WSL2 with Ubuntu 22.04 or 24.04.

```bash
sudo apt update
sudo apt install -y gawk wget git diffstat unzip texinfo gcc build-essential \
  chrpath socat cpio python3 python3-pip python3-pexpect xz-utils debianutils \
  iputils-ping python3-git python3-jinja2 libegl1-mesa libsdl1.2-dev pylint \
  xterm python3-subunit mesa-common-dev zstd liblz4-tool file locales
sudo locale-gen en_US.UTF-8
python3 -m pip install --user kas
```

## QEMU Build & Run

```bash
bash scripts/build-qemuarm64.sh
bash scripts/run-qemuarm64.sh
```

Test the pipeline without a microphone (dev shortcut):
```bash
curl -X POST http://localhost:8080/say \
  -H 'Content-Type: application/json' \
  -d '{"text": "Hello Aria, how are you?"}'
curl http://localhost:8080/health
```

## RPi 4 Build & Flash

```bash
bash scripts/build-rpi4.sh

# Insert SD card, find its device with lsblk, then:
bash scripts/flash-rpi4.sh /dev/sdX
```

### RPi Hardware Wiring

| Signal | RPi pin | Notes |
|--------|---------|-------|
| Servo signal | GPIO 18 (pin 12) | PWM0, enabled by `dtoverlay=pwm-2chan` |
| Servo 5 V | Pin 2 or 4 | Use external 5 V rail for >1 servo |
| Servo GND | Pin 6 | Common ground with RPi |
| USB mic | Any USB port | RPi has no built-in mic |
| Speaker | 3.5 mm jack | Or USB audio adapter |

### Setting API Keys on the Device

```bash
# On the RPi (after first boot, via SSH):
cat > /etc/anime-ai/secrets.env << 'EOF'
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
EOF
chmod 600 /etc/anime-ai/secrets.env
systemctl restart anime-ai-companion
```

## Companion Daemon HTTP API

All endpoints are on port 8080.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Uptime, state, device info |
| GET | `/status` | Current state: `idle / recording / processing / speaking` |
| POST | `/listen` | Start a full mic → response turn (async, 202) |
| POST | `/say` | Body: `{"text":"..."}` — skip STT, useful for dev |

## Production Hardware Path

For the Founders Edition product, swap the BSP layer:

- **RPi CM4 / CM5** on a custom carrier board → still `meta-raspberrypi`
- **NXP i.MX 8M** → NXP BSP layers
- **Rockchip RK3566** → vendor BSP layers

`meta-anime-ai` stays unchanged; only the BSP layer and kas config change.

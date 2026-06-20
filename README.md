# 📡 Sentinex RTSP (Cognitive Surveillance System)

**Multimodal frame analysis system using Qwen3-VL and RTSP cameras.**
Detects visual risks and sends real-time alerts via Telegram.
Built for real-world surveillance scenarios — resilient, lightweight and local-first.

---

## 🧠 Features

- 🧲 Pulls frames from any IP camera / RTSP stream (DVR/NVR compatible).
- 🔍 Sends frames to **local LLM** (e.g. Qwen3-VL via LM Studio).
- 🧠 Performs visual reasoning with a configurable system prompt.
- 🧮 Extracts structured risk score (0.0 to 1.0).
- 🚨 Sends alerts to Telegram on critical events.
- 🔄 Auto-reconnects if RTSP stream fails (resilient loop).
- 🪶 Fully stateless, fast and resource-light (runs on consumer hardware).
- 🧍 Human-presence alerts with configurable per-camera cooldown.

---

## ⚙️ Quick Setup

### Prerequisites

- **Python 3.8+**
- **LM Studio** (or any OpenAI-compatible vision LLM API)
- **IP Camera** with RTSP support
- **Telegram Bot** (optional, for alerts)

### Installation

1. **Clone the repository**
```bash
git clone https://github.com/yourusername/sentinex.git
cd sentinex
```

2. **Create virtual environment**
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
```

4. **Setup LM Studio**
   - Download and install [LM Studio](https://lmstudio.ai/)
   - Load a vision model (e.g., `qwen3-vl-8b`)
   - Start the local server (port 1234)

5. **Configure environment**
   - Copy `.env.example` to `.env` (or create `.env` manually)
   - Add your camera RTSP URLs
   - Configure Telegram bot credentials (optional)

6. **Run Sentinex**
```bash
python sentinex.py
```

---

## 🌐 Web Admin Panel

Launch the web interface to manage cameras and view captured frames:

```bash
uvicorn sentinex_admin:app --reload --port 8000
```

Then open **http://localhost:8000** in your browser.

### Features:
- ✏️ Add, edit, rename, and delete cameras
- 🎯 Configure per-camera system prompts
- 🖼️ View last captured frames from each camera
- 🔄 Auto-refresh every 15 seconds (configurable)

### Advanced Options:
```bash
# Use a different .env file
SENTINEX_ENV_FILE=.env.production uvicorn sentinex_admin:app --port 8000

# Disable auto-refresh
ADMIN_REFRESH_MS=0 uvicorn sentinex_admin:app --port 8000
```

---

## 🔐 Server Proxy (Optional)

For remote access with API key authentication:

1. **Create `.env.server`**
```env
LM_STUDIO_URL=http://localhost:1234
API_KEY=your_secret_key_here
```

2. **Start the proxy**
```bash
uvicorn server_proxy:app --host 0.0.0.0 --port 8001
```

3. **Update main `.env`**
```env
LM_STUDIO_API=http://localhost:8001
API_KEY=your_secret_key_here
```

4. **Expose with ngrok** (optional)
```bash
ngrok http 8001
```

---

## 🔐 Configuration (`.env`)

Create a `.env` file in the project root:

```env
# ============================================================
# 📡 RTSP CAMERAS (Dynamic: RTSP_URL_<NAME>)
# ============================================================
# Add as many cameras as needed. Each camera needs:
# - RTSP_URL_<NAME>: Camera stream URL
# - SYSTEM_PROMPT_<NAME>: Custom prompt (optional)

RTSP_URL_CAM1=rtsp://user:password@192.168.1.10:554/stream
RTSP_URL_ENTRANCE=rtsp://user:password@192.168.1.11:554/stream
RTSP_URL_PARKING=rtsp://user:password@192.168.1.12:554/stream

# ============================================================
# 🎞️ FRAME CAPTURE SETTINGS
# ============================================================
FRAME_WIDTH=1280
FRAME_HEIGHT=720
FRAME_MAX_WIDTH=960              # Resize frames before sending to LLM
JPEG_QUALITY=70                  # Lower quality makes the image smaller/faster
INTERVAL=60                      # Seconds between captures
LAST_FRAME_DIR=last_frames       # Directory to save frames

# Motion pre-processing
MOTION_FILTER_ENABLED=1          # Enable cheap frame pre-processing and optional motion crop
MOTION_DOWNSCALE_WIDTH=320       # Cheap motion check resolution
MOTION_DIFF_THRESHOLD=24         # Pixel difference needed to count as motion
MOTION_MIN_CHANGED_RATIO=0.002   # Minimum changed area before analyzing
MOTION_CROP_ENABLED=1            # Send only the motion crop when useful
MOTION_CROP_PADDING=0.18         # Context around the motion box
MOTION_CROP_MAX_AREA_RATIO=0.75  # Use full frame if crop is almost the whole image
MOTION_SKIP_LOW_CHANGE=0         # Optional: skip VLLM on low scene change. Off by default to avoid missed static risks
FULL_FRAME_EVERY_SECONDS=300     # Force periodic full-frame analysis
MOTION_SKIP_SLEEP_SECONDS=1      # Avoid tight loops when INTERVAL=0 and frame is skipped
MOTION_MAX_SKIPS_BEFORE_ANALYSIS=10 # Force analysis after repeated skips

# ============================================================
# 🧠 LLM CONFIGURATION
# ============================================================
LM_STUDIO_API=http://localhost:1234/v1
LM_STUDIO_PATH=/chat/completions
MODEL_NAME=qwen3-vl-8b
API_KEY=                         # Leave empty for local LM Studio
LM_TIMEOUT=60
LLM_MAX_TOKENS=220               # Keep output short; model only needs JSON

# Default system prompt (used if no camera-specific prompt)
SYSTEM_PROMPT=You are a cognitive sentinel. You observe camera images to detect human presence, anomalies, or risks. Always respond in valid JSON: {"description":"brief description", "score":0.0}

# Camera-specific prompts (optional)
SYSTEM_PROMPT_ENTRANCE=You monitor the main entrance. Detect unauthorized access, suspicious behavior, and security threats. Respond in JSON: {"description":"...", "score":0.0}
SYSTEM_PROMPT_PARKING=You monitor the parking lot. Detect vehicle incidents, unauthorized parking, and suspicious activity. Respond in JSON: {"description":"...", "score":0.0}

# ============================================================
# ⚠️ RISK SCORING & ALERTS
# ============================================================
# score < SCORE_TELEGRAM_ALERT: no external alert
# SCORE_TELEGRAM_ALERT <= score < SCORE_CRITICAL_ALERT: Telegram only
# score >= SCORE_CRITICAL_ALERT: Telegram + lights + TTS + siren
SCORE_TELEGRAM_ALERT=0.8
SCORE_CRITICAL_ALERT=0.95

# ============================================================
# 📲 TELEGRAM ALERTS
# ============================================================
ENABLE_TELEGRAM=1
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=123456789

# Critical audio alert
TTS_ENABLED=1
TTS_MESSAGE="Alarma. Alarma. Alarma. Alarma crítica en el vivero."
TTS_LANG=es
TTS_COOLDOWN=60
TTS_REPEATS=3
TTS_REPEAT_DELAY=0.4
SIREN_FILE=alarma_infernal.wav
SIREN_COOLDOWN=30
SIREN_MAX_SECONDS=4
# Use one URL in CRITICAL_LIGHTS_WEBHOOK_URL or several comma-separated URLs here.
CRITICAL_LIGHTS_WEBHOOK_URLS=
CRITICAL_LIGHTS_WEBHOOK_URL=
CRITICAL_LIGHTS_ACTION_NAME=focos_criticos
CRITICAL_LIGHTS_COOLDOWN=30
CRITICAL_LIGHTS_TIMEOUT=8
CRITICAL_LIGHTS_OFF_WEBHOOK_URLS=
CRITICAL_LIGHTS_OFF_WEBHOOK_URL=
CRITICAL_LIGHTS_OFF_ACTION_NAME=apagar_foco
CRITICAL_LIGHTS_AUTO_OFF_SECONDS=300

# ============================================================
# 📊 OMNISTATUS INTEGRATION (Optional)
# ============================================================
ENABLE_OMNISTATUS=0
OMNISTATUS_ENDPOINT=http://localhost:5000/api/status
OMNISTATUS_DEDUP_ENABLED=1
OMNISTATUS_DEDUP_WINDOW_SECONDS=30
OMNISTATUS_DEDUP_MAX_SAMPLES=3
```

When deduplication is enabled, Sentinex groups repeated events per camera and normalized text before sending them to OmniStatus. The payload keeps `text` and `score` for compatibility, and adds `event_count`, `avg_score`, `first_seen`, `last_seen`, `summary`, `dedup_key`, and `samples`.

---

## 📚 How to Get Telegram Credentials

1. **Create a bot:**
   - Message [@BotFather](https://t.me/botfather) on Telegram
   - Send `/newbot` and follow instructions
   - Copy the bot token

2. **Get your chat ID:**
   - Message [@userinfobot](https://t.me/userinfobot)
   - Copy your chat ID

3. **Start your bot:**
   - Search for your bot username in Telegram
   - Press "Start"

---

## 🚀 Usage Examples

### Basic Local Setup
```bash
# Start LM Studio (port 1234)
# Then run:
python sentinex.py
```

### With Admin Panel
```bash
# Terminal 1: Admin panel
uvicorn sentinex_admin:app --reload --port 8000

# Terminal 2: Main surveillance
python sentinex.py
```

### Production with Proxy
```bash
# Terminal 1: Server proxy
uvicorn server_proxy:app --port 8001

# Terminal 2: Admin panel
uvicorn sentinex_admin:app --port 8000

# Terminal 3: Main surveillance
python sentinex.py

# Terminal 4-6: Expose with ngrok (optional)
ngrok http 8001
ngrok http 8000
```

---

## 🐛 Troubleshooting

### Camera won't connect
- Verify RTSP URL with VLC: `vlc rtsp://user:pass@ip:554/stream`
- Check network connectivity and firewall rules
- Ensure camera supports RTSP (not all IP cameras do)

### LLM errors
- Confirm LM Studio is running on port 1234
- Check that the model supports vision (Qwen3-VL, LLaVA, etc.)
- Verify `LM_STUDIO_API` URL in `.env`

### No Telegram alerts
- Verify bot token and chat ID
- Ensure you've started the bot (sent `/start`)
- Check `ENABLE_TELEGRAM=1` in `.env`

### High resource usage
- Reduce `FRAME_WIDTH` and `FRAME_HEIGHT`
- Increase `INTERVAL` (capture less frequently)
- Lower `FRAME_MAX_WIDTH` before sending to LLM

---

## 📝 License

MIT License - feel free to use for commercial or personal projects.

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

---

> 🛠 **Developed by Oscar Aguilera**
> [LinkedIn](https://www.linkedin.com/in/oaguileraz/) | Engineering + Computer Vision + Local Cognitive Models  

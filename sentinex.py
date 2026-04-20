# sentinex.py — Multi-camera cognitive surveillance (English / Stable)
# Author: Oscar Aguilera
# Architecture: Producer-Consumer to prevent stream freezing.

import os
import cv2
import time
import base64
import requests
import json
import logging
import io
import socket
import tempfile
from collections import deque
from logging.handlers import RotatingFileHandler
from threading import Thread, Lock
from datetime import datetime


from dotenv import load_dotenv
from gtts import gTTS

# Suppress pygame support prompt
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
import pygame

load_dotenv()

# ============================================================
# CONFIGURATION
# ============================================================

def load_cameras_from_env():
    """Load all cameras defined as RTSP_URL_<NAME> in .env file."""
    cameras = {}
    for key, value in os.environ.items():
        if not key.startswith("RTSP_URL_"):
            continue
        if not value:
            continue
        name = key.replace("RTSP_URL_", "")
        cameras[name] = value
    return cameras


CAMERAS = load_cameras_from_env()

# Frame and Scaling settings
FRAME_MAX_WIDTH = int(os.getenv("FRAME_MAX_WIDTH", "960"))
INTERVAL = float(os.getenv("INTERVAL", "0")) # Set to 0 for max speed
LAST_FRAME_DIR = os.getenv("LAST_FRAME_DIR", "last_frames")

# LLM API Settings
LM_API = os.getenv("LM_STUDIO_API", "").rstrip("/")
LM_PATH = os.getenv("LM_STUDIO_PATH", "/chat/completions")
MODEL_NAME = os.getenv("MODEL_NAME", "qwen3-vl-8b")
API_KEY = os.getenv("LM_STUDIO_API_KEY", "lm-studio")  

# --- DECISION THRESHOLDS ---
SCORE_THRESHOLD = float(os.getenv("SCORE_THRESHOLD", "0.25")) # Warning
SCORE_CRITICAL = float(os.getenv("SCORE_CRITICAL", "0.45"))   # Siren

# Integrations
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ENABLE_OMNISTATUS = os.getenv("ENABLE_OMNISTATUS", "0") 
OMNISTATUS_API = os.getenv("OMNISTATUS_ENDPOINT")

# TTS (Text-to-Speech) - WARNING LEVEL
TTS_ENABLED = os.getenv("TTS_ENABLED", "0") == "1"
TTS_MESSAGE = os.getenv("TTS_MESSAGE", "Alexa enciende el desierto 15 segundos.")
TTS_LANG = os.getenv("TTS_LANG", "es") 
TTS_COOLDOWN = float(os.getenv("TTS_COOLDOWN", "60"))

# SIREN (Audio File) - CRITICAL LEVEL
# AQUI: Asegúrate que este nombre coincida con tu archivo generado
SIREN_FILE = os.getenv("SIREN_FILE", "alarma_infernal.wav") 
SIREN_COOLDOWN = float(os.getenv("SIREN_COOLDOWN", "30"))

# Video Clip Settings (for Telegram alerts)
CLIP_PRE_SECONDS = float(os.getenv("CLIP_PRE_SECONDS", "3"))   # Seconds of video BEFORE the event
CLIP_POST_SECONDS = float(os.getenv("CLIP_POST_SECONDS", "3")) # Seconds of video AFTER the event
CLIP_FPS = float(os.getenv("CLIP_FPS", "8"))                   # FPS for the output clip

# Heartbeat
HEARTBEAT_ENABLED = os.getenv("HEARTBEAT_ENABLED", "1") 
HEARTBEAT_INTERVAL = float(os.getenv("HEARTBEAT_INTERVAL", "14400"))

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FILE = os.getenv("LOG_FILE", "sentinex.log")



# ============================================================
# LOGGING SETUP
# ============================================================

logger = logging.getLogger("sentinex")
logger.setLevel(LOG_LEVEL)

ch = logging.StreamHandler()
ch.setLevel(LOG_LEVEL)
formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
ch.setFormatter(formatter)
logger.addHandler(ch)

fh = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=3)
fh.setLevel(LOG_LEVEL)
fh.setFormatter(formatter)
logger.addHandler(fh)

def log(msg, level="info"):
    if level.lower() == "error": logger.error(msg)
    elif level.lower() == "warning": logger.warning(msg)
    else: logger.info(msg)


# ============================================================
# UTILS & PRODUCER CLASS
# ============================================================

def resize_if_needed(frame):
    if FRAME_MAX_WIDTH and frame.shape[1] > FRAME_MAX_WIDTH:
        scale = FRAME_MAX_WIDTH / frame.shape[1]
        new_size = (int(frame.shape[1] * scale), int(frame.shape[0] * scale))
        frame = cv2.resize(frame, new_size, interpolation=cv2.INTER_AREA)
    return frame


def to_b64_jpg(frame):
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
    if not ok:
        raise RuntimeError("Failed to encode frame to JPEG")
    return base64.b64encode(buf).decode("utf-8")


def save_last_frame(camera_name: str, frame):
    try:
        os.makedirs(LAST_FRAME_DIR, exist_ok=True)
        safe_name = "".join(c if c.isalnum() else "_" for c in camera_name)
        path = os.path.join(LAST_FRAME_DIR, f"{safe_name}_last.jpg")
        ok = cv2.imwrite(path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        if not ok:
            log(f"⚠️ Failed to save frame for {camera_name}", "warning")
    except Exception as e:
        log(f"⚠️ Error saving frame for {camera_name}: {e}", "error")


def play_audio_tts(text: str, lang: str = "es", repeats: int = 1, delay: float = 0.0):
    """Generates TTS on the fly and plays it."""
    if not TTS_ENABLED: return
    try:
        tts = gTTS(text=text, lang=lang)
        mp3_fp = io.BytesIO()
        tts.write_to_fp(mp3_fp)
        mp3_fp.seek(0)

        if not pygame.mixer.get_init():
            pygame.mixer.init()

        pygame.mixer.music.load(mp3_fp)
        for i in range(repeats):
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.1)
            if i < repeats - 1:
                time.sleep(delay)
    except Exception as e:
        log(f"❌ TTS playback error: {e}", "error")


def play_siren_file():
    """Plays the local siren WAV/MP3 file at max volume."""
    if not os.path.exists(SIREN_FILE):
        log(f"❌ Siren file not found at: {SIREN_FILE}", "error")
        return

    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        
        # Load and play
        pygame.mixer.music.load(SIREN_FILE)
        pygame.mixer.music.set_volume(1.0) 
        pygame.mixer.music.play()
        
        log(f"🔊 SIREN ACTIVATED 🚨 ({SIREN_FILE})")
        
    except Exception as e:
        log(f"❌ Siren playback error: {e}", "error")


class CameraStream:
    """Producer: Captures frames and keeps only the most recent one.
    Also maintains a rolling buffer of recent frames for video clip generation."""
    def __init__(self, name, url):
        self.name = name
        self.url = url
        self.frame = None
        self.lock = Lock()
        self.stopped = False
        # Rolling buffer: keep enough frames for CLIP_PRE_SECONDS at CLIP_FPS
        buffer_size = int(CLIP_PRE_SECONDS * CLIP_FPS) + 10  # small margin
        self.frame_buffer = deque(maxlen=buffer_size)
        self.thread = Thread(target=self._update, daemon=True)
        self.thread.start()

    def _update(self):
        retries = 0
        while not self.stopped:
            cap = cv2.VideoCapture(self.url)
            if not cap.isOpened():
                log(f"❌ {self.name}: Failed to open stream. Retrying in 5s.", "error")
                time.sleep(5)
                retries += 1
                if retries > 10:
                    log(f"❌ {self.name}: Persistent failure. Stopping producer.", "error")
                    self.stopped = True
                continue
            
            log(f"🎥 {self.name}: Producer started.")
            retries = 0
            
            while not self.stopped:
                for _ in range(3): # Drop frames to keep latency low
                    cap.grab()
                
                ok, frame = cap.read()
                if not ok or frame is None:
                    log(f"⚠️ {self.name}: Invalid stream/frame. Forcing reconnection.", "warning")
                    cap.release()
                    break
                
                with self.lock:
                    self.frame = frame
                    self.frame_buffer.append(frame.copy())
                time.sleep(0.01)
            
            cap.release()
            
    def read(self):
        with self.lock:
            return self.frame.copy() if self.frame is not None else None

    def get_buffer_snapshot(self):
        """Return a copy of the current frame buffer."""
        with self.lock:
            return list(self.frame_buffer)

    def capture_post_event_frames(self, duration_seconds: float, fps: float) -> list:
        """Capture additional frames after an event for the specified duration."""
        num_frames = int(duration_seconds * fps)
        frames = []
        interval = 1.0 / fps if fps > 0 else 0.125
        for _ in range(num_frames):
            time.sleep(interval)
            frame = self.read()
            if frame is not None:
                frames.append(frame)
        return frames

    def stop(self):
        self.stopped = True
        self.thread.join(timeout=2)

# ============================================================
# LLM & CONSUMER (Analysis)
# ============================================================

def analyze_llm(camera_name, frame) -> dict:
    try:
        img_b64 = to_b64_jpg(frame)
        img_data_uri = f"data:image/jpeg;base64,{img_b64}"
        system_prompt = os.getenv(f"SYSTEM_PROMPT_{camera_name}", "")

        payload = {
            "model": MODEL_NAME,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": [{"type": "image_url", "image_url": {"url": img_data_uri}}]},
            ],
            "temperature": 0.1,
            "max_tokens": 300,
        }

        url = LM_API + LM_PATH
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"}

        r = requests.post(url, json=payload, headers=headers, timeout=180) 
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"]
        parsed = json.loads(raw)
        return {"score": float(parsed.get("score", 0.0)), "text": str(parsed.get("description") or ""), "b64": img_b64}
    except Exception as e:
        log(f"❌ LLM Error ({camera_name}): {e}", "error")
        b64_val = img_b64 if 'img_b64' in locals() else ""
        return {"score": 0.0, "text": "LLM Analysis Error", "b64": b64_val}


def process_camera_analysis(stream: CameraStream):
    """Consumer: Pulls frame, analyzes it, triggers alerts based on SCORE.
    On alert, captures a mini video clip and sends it to Telegram."""
    name = stream.name
    log(f"🧠 Consumer {name} started.")
    last_tts_alert_at = 0.0
    last_siren_alert_at = 0.0

    while not stream.stopped:
        try:
            frame = stream.read() 
            if frame is None:
                time.sleep(1)
                continue
            
            frame = resize_if_needed(frame)
            res = analyze_llm(name, frame) 
            save_last_frame(name, frame)

            score = res["score"]
            text = res["text"]
            log(f"[{name}] score={score:.2f} | {text}")

            # === LEVEL 1: CRITICAL THREAT (SIREN) ===
            if score >= SCORE_CRITICAL:
                caption = f"🚨🔴 CRITICAL: {name} | Score={score:.2f}\n{text}"
                # Capture video clip in background thread to not block siren
                Thread(
                    target=_capture_and_send_video_clip,
                    args=(stream, name, caption, res["b64"]),
                    daemon=True
                ).start()
                
                now = time.time()
                if now - last_siren_alert_at >= SIREN_COOLDOWN:
                    play_siren_file()
                    last_siren_alert_at = now
                else:
                    log("⏳ Siren cooling down...")

            # === LEVEL 2: WARNING (TTS) ===
            elif score >= SCORE_THRESHOLD: 
                caption = f"⚠️ {name}: {text} | Risk={score:.2f}"
                Thread(
                    target=_capture_and_send_video_clip,
                    args=(stream, name, caption, res["b64"]),
                    daemon=True
                ).start()
                if TTS_ENABLED:
                    now = time.time()
                    if now - last_tts_alert_at >= TTS_COOLDOWN:
                        log(f"🔊 Playing TTS for {name}")
                        play_audio_tts(TTS_MESSAGE, TTS_LANG, repeats=2, delay=1.0)
                        last_tts_alert_at = now
            
            inject_omnistatus(name, text, score)
            
        except Exception as e:
            log(f"❌ Unexpected Error in consumer loop ({name}): {e}", "error")

        time.sleep(INTERVAL)

# ============================================================
# MAIN
# ============================================================

def _capture_and_send_video_clip(stream: CameraStream, camera_name: str, caption: str, fallback_b64: str):
    """Captures pre+post event frames, builds a video clip, and sends it to Telegram.
    Falls back to sending a photo if video generation fails."""
    try:
        log(f"🎬 [{camera_name}] Capturing video clip ({CLIP_PRE_SECONDS}s pre + {CLIP_POST_SECONDS}s post)...")
        
        # 1. Get pre-event frames from the rolling buffer
        pre_frames = stream.get_buffer_snapshot()
        
        # 2. Capture post-event frames (this blocks for CLIP_POST_SECONDS)
        post_frames = stream.capture_post_event_frames(CLIP_POST_SECONDS, CLIP_FPS)
        
        # 3. Combine all frames
        all_frames = pre_frames + post_frames
        
        if len(all_frames) < 4:
            log(f"⚠️ [{camera_name}] Not enough frames for video ({len(all_frames)}). Sending photo instead.", "warning")
            send_telegram_photo(fallback_b64, caption)
            return
        
        # 4. Resize all frames consistently
        all_frames = [resize_if_needed(f) for f in all_frames]
        
        # 5. Build MP4 clip
        video_path = build_video_clip(all_frames, camera_name, CLIP_FPS)
        
        if video_path and os.path.exists(video_path):
            send_telegram_video(video_path, caption)
            # Clean up temp file
            try:
                os.remove(video_path)
            except OSError:
                pass
        else:
            log(f"⚠️ [{camera_name}] Video build failed. Sending photo instead.", "warning")
            send_telegram_photo(fallback_b64, caption)
            
    except Exception as e:
        log(f"❌ [{camera_name}] Video clip error: {e}. Sending photo.", "error")
        send_telegram_photo(fallback_b64, caption)


def build_video_clip(frames: list, camera_name: str, fps: float) -> str:
    """Writes a list of frames to a temporary MP4 file. Returns the file path."""
    if not frames:
        return None
    
    try:
        h, w = frames[0].shape[:2]
        
        # Create temp file for the video
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".mp4", prefix=f"sentinex_{camera_name}_")
        os.close(tmp_fd)
        
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        writer = cv2.VideoWriter(tmp_path, fourcc, fps, (w, h))
        
        if not writer.isOpened():
            log(f"❌ Failed to open VideoWriter for {camera_name}", "error")
            return None
        
        for frame in frames:
            # Ensure frame matches expected dimensions
            if frame.shape[:2] != (h, w):
                frame = cv2.resize(frame, (w, h))
            writer.write(frame)
        
        writer.release()
        
        file_size = os.path.getsize(tmp_path)
        duration = len(frames) / fps if fps > 0 else 0
        log(f"🎬 [{camera_name}] Video clip ready: {len(frames)} frames, {duration:.1f}s, {file_size/1024:.0f}KB")
        
        return tmp_path
        
    except Exception as e:
        log(f"❌ Video build error ({camera_name}): {e}", "error")
        return None


def send_telegram_video(video_path: str, caption: str):
    """Send a video clip to Telegram using sendVideo API."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo"
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "caption": caption[:1024],
            "supports_streaming": "true",
        }
        with open(video_path, "rb") as vf:
            files = {"video": ("alert_clip.mp4", vf, "video/mp4")}
            r = requests.post(url, data=data, files=files, timeout=60)
        
        if r.status_code == 200:
            log(f"📤 Telegram video sent successfully.")
        else:
            log(f"⚠️ Telegram sendVideo returned {r.status_code}: {r.text[:200]}", "warning")
    except Exception as e:
        log(f"❌ Telegram video send error: {e}", "error")


def send_telegram_photo(img_b64: str, caption: str):
    """Send a photo to Telegram (fallback when video fails)."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID: return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        data = {"chat_id": TELEGRAM_CHAT_ID, "caption": caption[:1024]}
        files = {"photo": ("frame.jpg", base64.b64decode(img_b64), "image/jpeg")}
        requests.post(url, data=data, files=files, timeout=20)
    except Exception:
        pass

def inject_omnistatus(source: str, text: str, score: float):
    if not ENABLE_OMNISTATUS or not OMNISTATUS_API: return
    
    # Ensure URL ends with /event
    # If the user put just binary URL (localhost:8001), append /event
    # If they put full URL, leave it. Check if it ends in /event or has query params
    target_url = OMNISTATUS_API
    if not target_url.endswith("/event") and not target_url.endswith("/events"):
        target_url = target_url.rstrip("/") + "/event"

    try:
        payload = {"source": source, "text": text, "score": score}
        # Debug log for 422 investigation
        # log(f"Drafting OmniStatus payload: {json.dumps(payload)}", "debug")
        
        r = requests.post(target_url, json=payload, timeout=5)
        
        if r.status_code == 422:
            log(f"❌ OmniStatus 422 Unprocessable Entity! Response: {r.text} | Payload: {json.dumps(payload)}", "error")
        elif r.status_code != 200:
            log(f"⚠️ OmniStatus returned {r.status_code}: {r.text}", "warning")
            
    except Exception as e:
        log(f"❌ OmniStatus Error: {e}", "error")

def heartbeat_loop():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or not HEARTBEAT_ENABLED: return
    hostname = socket.gethostname()
    instance_name = os.getenv("SENTINEX_INSTANCE_NAME", f"Sentinex-{hostname}")

    while True:
        try:
            now_str = time.strftime("%Y-%m-%d %H:%M:%S")
            msg = f"🟢 {instance_name} Online | 📅 {now_str}"
            
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            data = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
            requests.post(url, data=data, timeout=20)
            log(f"💓 Heartbeat sent: {msg}")
        except Exception as e:
            log(f"❌ Heartbeat Error: {e}", "error")
        
        time.sleep(HEARTBEAT_INTERVAL)

def main():
    if not CAMERAS:
        log("No cameras in .env. Exiting.", "error")
        return

    streams = {}
    for name, url in CAMERAS.items():
        if url:
            stream = CameraStream(name, url)
            streams[name] = stream
            Thread(target=process_camera_analysis, args=(stream,), daemon=True).start()

    log("Sentinex started. Ctrl+C to exit.")
    Thread(target=heartbeat_loop, daemon=True).start()
    
    while True:
        try: time.sleep(1)
        except KeyboardInterrupt:
            for s in streams.values(): s.stop()
            break

if __name__ == "__main__":
    main()
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
import re
from logging.handlers import RotatingFileHandler
from threading import Thread, Lock
from datetime import datetime
from typing import List, Optional


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


def env_str(name: str, required: bool = True) -> str:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        if required:
            raise RuntimeError(f"Missing required environment variable: {name}")
        return ""
    return value.strip()


def env_str_first(*names: str, required: bool = True) -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip() != "":
            return value.strip()
    if required:
        joined = " or ".join(names)
        raise RuntimeError(f"Missing required environment variable: {joined}")
    return ""


def env_str_first_default(default: str, *names: str) -> str:
    return env_str_first(*names, required=False) or default


def env_int(name: str) -> int:
    return int(env_str(name))


def env_float(name: str) -> float:
    return float(env_str(name))


def env_float_first(*names: str) -> float:
    return float(env_str_first(*names))


def env_bool(name: str) -> bool:
    value = env_str(name).lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value: 1/0, true/false, yes/no, on/off")


# Frame and Scaling settings
FRAME_MAX_WIDTH = env_int("FRAME_MAX_WIDTH")
INTERVAL = env_float("INTERVAL") # Set to 0 for max speed
JPEG_QUALITY = env_int("JPEG_QUALITY")
LAST_FRAME_DIR = env_str("LAST_FRAME_DIR")
MOTION_FILTER_ENABLED = env_bool("MOTION_FILTER_ENABLED")
MOTION_DOWNSCALE_WIDTH = env_int("MOTION_DOWNSCALE_WIDTH")
MOTION_DIFF_THRESHOLD = env_int("MOTION_DIFF_THRESHOLD")
MOTION_MIN_CHANGED_RATIO = env_float("MOTION_MIN_CHANGED_RATIO")
MOTION_CROP_ENABLED = env_bool("MOTION_CROP_ENABLED")
MOTION_CROP_PADDING = env_float("MOTION_CROP_PADDING")
MOTION_CROP_MAX_AREA_RATIO = env_float("MOTION_CROP_MAX_AREA_RATIO")
MOTION_SKIP_LOW_CHANGE = env_bool("MOTION_SKIP_LOW_CHANGE")
FULL_FRAME_EVERY_SECONDS = env_float("FULL_FRAME_EVERY_SECONDS")
MOTION_SKIP_SLEEP_SECONDS = env_float("MOTION_SKIP_SLEEP_SECONDS")
MOTION_MAX_SKIPS_BEFORE_ANALYSIS = env_int("MOTION_MAX_SKIPS_BEFORE_ANALYSIS")

# LLM API Settings
LM_API = env_str("LM_STUDIO_API").rstrip("/")
LM_PATH = env_str("LM_STUDIO_PATH")
MODEL_NAME = env_str("MODEL_NAME")
API_KEY = env_str("API_KEY", required=False)
LM_TIMEOUT = env_float("LM_TIMEOUT")
LLM_MAX_TOKENS = env_int("LLM_MAX_TOKENS")
SYSTEM_PROMPT = env_str("SYSTEM_PROMPT")

# Persistent HTTP session to reuse keep-alive connections and avoid repeated TCP handshakes
HTTP_SESSION = requests.Session()
HTTP_SESSION.trust_env = False

# Alert levels:
# score < SCORE_TELEGRAM_ALERT => no external alert
# SCORE_TELEGRAM_ALERT <= score < SCORE_CRITICAL_ALERT => Telegram only
# score >= SCORE_CRITICAL_ALERT => Telegram + lights + TTS + siren
SCORE_TELEGRAM_ALERT = env_float_first("SCORE_TELEGRAM_ALERT", "SCORE_THRESHOLD")
SCORE_CRITICAL_ALERT = env_float_first("SCORE_CRITICAL_ALERT", "SCORE_CRITICAL")
if SCORE_TELEGRAM_ALERT >= SCORE_CRITICAL_ALERT:
    raise RuntimeError("SCORE_TELEGRAM_ALERT must be lower than SCORE_CRITICAL_ALERT")

# Integrations
ENABLE_TELEGRAM = os.getenv("ENABLE_TELEGRAM", "0") == "1"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ENABLE_OMNISTATUS = os.getenv("ENABLE_OMNISTATUS", "0") 
OMNISTATUS_API = os.getenv("OMNISTATUS_ENDPOINT")
OMNISTATUS_DEDUP_ENABLED = os.getenv("OMNISTATUS_DEDUP_ENABLED", "1") == "1"
OMNISTATUS_DEDUP_WINDOW_SECONDS = float(os.getenv("OMNISTATUS_DEDUP_WINDOW_SECONDS", "30"))
OMNISTATUS_DEDUP_MAX_SAMPLES = int(os.getenv("OMNISTATUS_DEDUP_MAX_SAMPLES", "3"))

# TTS (Text-to-Speech) - CRITICAL LEVEL
TTS_ENABLED = env_bool("TTS_ENABLED")
TTS_MESSAGE = env_str("TTS_MESSAGE")
TTS_LANG = env_str("TTS_LANG")
TTS_COOLDOWN = float(env_str_first_default("60", "TTS_COOLDOWN"))
TTS_REPEATS = int(env_str_first_default("2", "TTS_REPEATS"))
TTS_REPEAT_DELAY = float(env_str_first_default("1.0", "TTS_REPEAT_DELAY"))

# SIREN (Audio File) - CRITICAL LEVEL
# AQUI: Asegúrate que este nombre coincida con tu archivo generado
SIREN_FILE = env_str_first_default("alarma_infernal.wav", "SIREN_FILE")
SIREN_COOLDOWN = float(env_str_first_default("30", "SIREN_COOLDOWN"))
SIREN_MAX_SECONDS = float(env_str_first_default("0", "SIREN_MAX_SECONDS"))

# Heartbeat
HEARTBEAT_ENABLED = env_bool("HEARTBEAT_ENABLED")
HEARTBEAT_INTERVAL = env_float("HEARTBEAT_INTERVAL")
SENTINEX_INSTANCE_NAME = env_str("SENTINEX_INSTANCE_NAME")

# Logging
LOG_LEVEL = env_str("LOG_LEVEL").upper()
LOG_FILE = env_str("LOG_FILE")


def parse_webhook_urls(*raw_values: str) -> List[str]:
    urls = []
    seen = set()
    for raw_value in raw_values:
        for url in (raw_value or "").split(","):
            url = url.strip()
            if url and url not in seen:
                urls.append(url)
                seen.add(url)
    return urls


CRITICAL_LIGHTS_WEBHOOK_URLS = parse_webhook_urls(
    env_str("CRITICAL_LIGHTS_WEBHOOK_URLS", required=False),
    env_str_first("CRITICAL_LIGHTS_WEBHOOK_URL", "CRITICAL_WEBHOOK_URL", required=False),
)
CRITICAL_LIGHTS_OFF_WEBHOOK_URLS = parse_webhook_urls(
    env_str("CRITICAL_LIGHTS_OFF_WEBHOOK_URLS", required=False),
    env_str_first("CRITICAL_LIGHTS_OFF_WEBHOOK_URL", "CRITICAL_CLEAR_WEBHOOK_URL", required=False),
)
CRITICAL_LIGHTS_ACTION_NAME = env_str_first_default("focos_criticos", "CRITICAL_LIGHTS_ACTION_NAME")
CRITICAL_LIGHTS_OFF_ACTION_NAME = env_str_first_default("apagar_foco", "CRITICAL_LIGHTS_OFF_ACTION_NAME")
CRITICAL_LIGHTS_COOLDOWN = float(env_str_first_default("30", "CRITICAL_LIGHTS_COOLDOWN", "CRITICAL_WEBHOOK_COOLDOWN"))
CRITICAL_LIGHTS_TIMEOUT = float(env_str_first_default("8", "CRITICAL_LIGHTS_TIMEOUT"))
CRITICAL_LIGHTS_AUTO_OFF_SECONDS = float(env_str_first_default("0", "CRITICAL_LIGHTS_AUTO_OFF_SECONDS"))


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


_omnistatus_groups = {}
_omnistatus_groups_lock = Lock()


def normalize_event_text(text: str) -> str:
    normalized = re.sub(r"\W+", " ", (text or "").lower(), flags=re.UNICODE)
    return re.sub(r"\s+", " ", normalized).strip()


def utc_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def new_omnistatus_group(source: str, text: str, score: float, image_b64: Optional[str], now: float) -> dict:
    return {
        "source": source,
        "text": text,
        "score_sum": float(score),
        "score_max": float(score),
        "count": 1,
        "first_seen": utc_iso(),
        "last_seen": utc_iso(),
        "first_seen_ts": now,
        "last_seen_ts": now,
        "image_b64": image_b64,
        "samples": [text] if text else [],
    }


def update_omnistatus_group(group: dict, text: str, score: float, image_b64: Optional[str], now: float) -> None:
    group["count"] += 1
    group["score_sum"] += float(score)
    group["score_max"] = max(float(group["score_max"]), float(score))
    group["last_seen"] = utc_iso()
    group["last_seen_ts"] = now
    if image_b64:
        group["image_b64"] = image_b64
    if text and text not in group["samples"] and len(group["samples"]) < OMNISTATUS_DEDUP_MAX_SAMPLES:
        group["samples"].append(text)


def group_to_omnistatus_payload(group: dict) -> dict:
    count = int(group["count"])
    avg_score = group["score_sum"] / count if count else 0.0
    text = group["text"]
    if count > 1:
        text = f"{text} (repeated {count} times)"

    payload = {
        "source": group["source"],
        "text": text,
        "summary": text,
        "score": round(float(group["score_max"]), 4),
        "avg_score": round(avg_score, 4),
        "event_count": count,
        "first_seen": group["first_seen"],
        "last_seen": group["last_seen"],
        "dedup_key": normalize_event_text(group["text"]),
        "samples": group["samples"],
    }
    if group.get("image_b64"):
        payload["image_b64"] = group["image_b64"]
    return payload


def collect_omnistatus_payloads(source: str, text: str, score: float, image_b64: Optional[str] = None) -> List[dict]:
    if not OMNISTATUS_DEDUP_ENABLED:
        payload = {"source": source, "text": text, "score": score, "event_count": 1}
        if image_b64:
            payload["image_b64"] = image_b64
        return [payload]

    now = time.time()
    key = (source, normalize_event_text(text))
    ready = []

    with _omnistatus_groups_lock:
        current = _omnistatus_groups.get(source)
        if current and (source, normalize_event_text(current["text"])) == key:
            update_omnistatus_group(current, text, score, image_b64, now)
            if now - current["first_seen_ts"] >= OMNISTATUS_DEDUP_WINDOW_SECONDS:
                ready.append(group_to_omnistatus_payload(current))
                _omnistatus_groups.pop(source, None)
            return ready

        if current:
            ready.append(group_to_omnistatus_payload(current))

        _omnistatus_groups[source] = new_omnistatus_group(source, text, score, image_b64, now)

    return ready


def flush_due_omnistatus_payloads() -> List[dict]:
    if not OMNISTATUS_DEDUP_ENABLED:
        return []

    now = time.time()
    ready = []
    with _omnistatus_groups_lock:
        for source, group in list(_omnistatus_groups.items()):
            if now - group["last_seen_ts"] >= OMNISTATUS_DEDUP_WINDOW_SECONDS:
                ready.append(group_to_omnistatus_payload(group))
                _omnistatus_groups.pop(source, None)
    return ready


def flush_all_omnistatus_payloads() -> List[dict]:
    ready = []
    with _omnistatus_groups_lock:
        for source, group in list(_omnistatus_groups.items()):
            ready.append(group_to_omnistatus_payload(group))
            _omnistatus_groups.pop(source, None)
    return ready


# ============================================================
# UTILS & PRODUCER CLASS
# ============================================================

def resize_if_needed(frame):
    if FRAME_MAX_WIDTH and frame.shape[1] > FRAME_MAX_WIDTH:
        scale = FRAME_MAX_WIDTH / frame.shape[1]
        new_size = (int(frame.shape[1] * scale), int(frame.shape[0] * scale))
        frame = cv2.resize(frame, new_size, interpolation=cv2.INTER_AREA)
    return frame


def to_b64_jpg(frame, quality: int = JPEG_QUALITY):
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
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


class FramePreprocessor:
    """Keeps cheap per-camera state so repeated frames do not hit the VLLM."""
    def __init__(self):
        self.previous_gray = None
        self.last_full_analysis_at = 0.0
        self.consecutive_skips = 0

    def _small_gray(self, frame):
        height, width = frame.shape[:2]
        if MOTION_DOWNSCALE_WIDTH and width > MOTION_DOWNSCALE_WIDTH:
            scale = MOTION_DOWNSCALE_WIDTH / width
            frame = cv2.resize(frame, (MOTION_DOWNSCALE_WIDTH, max(1, int(height * scale))), interpolation=cv2.INTER_AREA)
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    def prepare(self, frame):
        if not MOTION_FILTER_ENABLED:
            return frame, {"skipped": False, "reason": "disabled", "crop": False, "changed_ratio": 1.0}

        now = time.time()
        gray = self._small_gray(frame)
        force_full = FULL_FRAME_EVERY_SECONDS > 0 and now - self.last_full_analysis_at >= FULL_FRAME_EVERY_SECONDS
        force_after_skips = (
            MOTION_MAX_SKIPS_BEFORE_ANALYSIS > 0
            and self.consecutive_skips >= MOTION_MAX_SKIPS_BEFORE_ANALYSIS
        )

        if self.previous_gray is None or self.previous_gray.shape != gray.shape:
            self.previous_gray = gray
            self.last_full_analysis_at = now
            self.consecutive_skips = 0
            return frame, {"skipped": False, "reason": "first_frame", "crop": False, "changed_ratio": 1.0}

        diff = cv2.absdiff(gray, self.previous_gray)
        _, mask = cv2.threshold(diff, MOTION_DIFF_THRESHOLD, 255, cv2.THRESH_BINARY)
        mask = cv2.medianBlur(mask, 5)
        changed_ratio = cv2.countNonZero(mask) / mask.size
        self.previous_gray = gray

        low_change = changed_ratio < MOTION_MIN_CHANGED_RATIO
        if low_change and MOTION_SKIP_LOW_CHANGE and not force_full and not force_after_skips:
            self.consecutive_skips += 1
            return None, {
                "skipped": True,
                "reason": "no_motion",
                "crop": False,
                "changed_ratio": changed_ratio,
            }

        self.last_full_analysis_at = now
        self.consecutive_skips = 0
        if low_change or force_full or force_after_skips or not MOTION_CROP_ENABLED:
            return frame, {
                "skipped": False,
                "reason": (
                    "low_change_full"
                    if low_change
                    else "periodic_full"
                    if force_full
                    else "skip_limit_full"
                    if force_after_skips
                    else "motion"
                ),
                "crop": False,
                "changed_ratio": changed_ratio,
            }

        points = cv2.findNonZero(mask)
        if points is None:
            return frame, {"skipped": False, "reason": "motion", "crop": False, "changed_ratio": changed_ratio}

        small_x, small_y, small_w, small_h = cv2.boundingRect(points)
        full_h, full_w = frame.shape[:2]
        scale_x = full_w / mask.shape[1]
        scale_y = full_h / mask.shape[0]

        x1 = int(small_x * scale_x)
        y1 = int(small_y * scale_y)
        x2 = int((small_x + small_w) * scale_x)
        y2 = int((small_y + small_h) * scale_y)

        pad_x = int((x2 - x1) * MOTION_CROP_PADDING)
        pad_y = int((y2 - y1) * MOTION_CROP_PADDING)
        x1 = max(0, x1 - pad_x)
        y1 = max(0, y1 - pad_y)
        x2 = min(full_w, x2 + pad_x)
        y2 = min(full_h, y2 + pad_y)

        crop_area_ratio = ((x2 - x1) * (y2 - y1)) / (full_w * full_h)
        if crop_area_ratio <= 0 or crop_area_ratio >= MOTION_CROP_MAX_AREA_RATIO:
            return frame, {"skipped": False, "reason": "motion_full", "crop": False, "changed_ratio": changed_ratio}

        return frame[y1:y2, x1:x2], {
            "skipped": False,
            "reason": "motion_crop",
            "crop": True,
            "changed_ratio": changed_ratio,
            "crop_area_ratio": crop_area_ratio,
        }


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


_siren_sound = None
_siren_sound_path = None


def play_siren_file():
    """Plays the local siren WAV/MP3 file at max volume."""
    global _siren_sound, _siren_sound_path

    if not os.path.exists(SIREN_FILE):
        log(f"❌ Siren file not found at: {SIREN_FILE}", "error")
        return

    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init()

        maxtime = int(SIREN_MAX_SECONDS * 1000) if SIREN_MAX_SECONDS > 0 else 0
        if _siren_sound is None or _siren_sound_path != SIREN_FILE:
            _siren_sound = pygame.mixer.Sound(SIREN_FILE)
            _siren_sound_path = SIREN_FILE

        _siren_sound.set_volume(1.0)
        _siren_sound.play(maxtime=maxtime)
        
        log(f"🔊 SIREN ACTIVATED 🚨 ({SIREN_FILE}, max {SIREN_MAX_SECONDS:.1f}s)")
        
    except Exception as e:
        log(f"❌ Siren playback error: {e}", "error")


def call_webhook_urls(webhook_urls: List[str], action_name: str, camera_name: str, score: float, text: str) -> int:
    payload = {
        "value1": camera_name,
        "value2": f"{score:.2f}",
        "value3": text[:512],
    }
    sent_count = 0

    for idx, webhook_url in enumerate(webhook_urls, start=1):
        try:
            r = HTTP_SESSION.post(
                webhook_url,
                json=payload,
                timeout=CRITICAL_LIGHTS_TIMEOUT,
            )
            if r.status_code >= 400:
                log(f"⚠️ Webhook {action_name} #{idx} returned {r.status_code}: {r.text[:200]}", "warning")
                continue
            sent_count += 1
        except Exception as e:
            log(f"❌ Webhook {action_name} #{idx} error: {e}", "error")

    return sent_count


def call_critical_lights_webhook(camera_name: str, score: float, text: str):
    """Calls the configured IFTTT webhook for critical light-on actions."""
    if not CRITICAL_LIGHTS_WEBHOOK_URLS:
        return

    sent_count = call_webhook_urls(
        CRITICAL_LIGHTS_WEBHOOK_URLS,
        CRITICAL_LIGHTS_ACTION_NAME,
        camera_name,
        score,
        text,
    )

    if sent_count:
        log(f"💡 Critical lights action sent: {CRITICAL_LIGHTS_ACTION_NAME} ({sent_count}/{len(CRITICAL_LIGHTS_WEBHOOK_URLS)})")


def call_critical_lights_off_webhook(camera_name: str, score: float, text: str):
    """Calls the configured IFTTT webhook for critical light-off actions."""
    if not CRITICAL_LIGHTS_OFF_WEBHOOK_URLS:
        return

    sent_count = call_webhook_urls(
        CRITICAL_LIGHTS_OFF_WEBHOOK_URLS,
        CRITICAL_LIGHTS_OFF_ACTION_NAME,
        camera_name,
        score,
        text,
    )

    if sent_count:
        log(f"💡 Critical lights off action sent: {CRITICAL_LIGHTS_OFF_ACTION_NAME} ({sent_count}/{len(CRITICAL_LIGHTS_OFF_WEBHOOK_URLS)})")


def schedule_critical_lights_off(camera_name: str, score: float, text: str, action_state: dict):
    if not CRITICAL_LIGHTS_OFF_WEBHOOK_URLS or CRITICAL_LIGHTS_AUTO_OFF_SECONDS <= 0:
        return

    action_state["lights_off_generation"] = action_state.get("lights_off_generation", 0) + 1
    generation = action_state["lights_off_generation"]
    delay = CRITICAL_LIGHTS_AUTO_OFF_SECONDS

    def delayed_off():
        time.sleep(delay)
        if action_state.get("lights_off_generation") != generation:
            return
        call_critical_lights_off_webhook(camera_name, score, text)

    Thread(target=delayed_off, daemon=True).start()
    log(f"⏲️ Critical lights off scheduled in {delay:.0f}s")


def run_critical_lights_action(name: str, score: float, text: str, action_state: dict):
    if CRITICAL_LIGHTS_WEBHOOK_URLS:
        run_with_cooldown(
            action_state,
            "lights",
            CRITICAL_LIGHTS_COOLDOWN,
            "⏳ Critical lights webhook cooling down...",
            lambda: call_critical_lights_webhook(name, score, text),
        )
    schedule_critical_lights_off(name, score, text, action_state)


def run_with_cooldown(action_state: dict, action_key: str, cooldown: float, cooldown_message: str, action):
    now = time.time()
    if now - action_state.get(action_key, 0.0) < cooldown:
        log(cooldown_message)
        return

    action_state[action_key] = now
    action()


def run_action_sequence(sequence_name: str, actions: list):
    log(f"⚡ Running action sequence: {sequence_name}")
    for action_name, action in actions:
        try:
            action()
        except Exception as e:
            log(f"❌ Action failed ({action_name}): {e}", "error")


def run_critical_action_sequence(name: str, res: dict, score: float, text: str, action_state: dict):
    actions = [
        (
            "telegram",
            lambda: send_telegram(res["b64"], f"🚨🔴 CRITICAL: {name} | Score={score:.2f}\n{text}"),
        ),
    ]

    if CRITICAL_LIGHTS_WEBHOOK_URLS or CRITICAL_LIGHTS_OFF_WEBHOOK_URLS:
        actions.append((
            "lights",
            lambda: run_critical_lights_action(name, score, text, action_state),
        ))

    if TTS_ENABLED:
        actions.append((
            "tts",
            lambda: run_with_cooldown(
                action_state,
                "tts",
                TTS_COOLDOWN,
                "⏳ Critical TTS cooling down...",
                lambda: play_audio_tts(TTS_MESSAGE, TTS_LANG, repeats=TTS_REPEATS, delay=TTS_REPEAT_DELAY),
            ),
        ))

    actions.append(
        (
            "siren",
            lambda: run_with_cooldown(
                action_state,
                "siren",
                SIREN_COOLDOWN,
                "⏳ Siren cooling down...",
                play_siren_file,
            ),
        ),
    )
    run_action_sequence("critical_edge", actions)


class CameraStream:
    """Producer: Captures frames and keeps only the most recent one."""
    def __init__(self, name, url):
        self.name = name
        self.url = url
        self.frame = None
        self.lock = Lock()
        self.stopped = False
        self.thread = Thread(target=self._update, daemon=True)
        self.thread.start()

    def _update(self):
        retries = 0
        while not self.stopped:
            cap = cv2.VideoCapture(self.url)
            if not cap.isOpened():
                log(f"❌ [{self.name}] Failed to open stream. Retrying in 5s.", "error")
                time.sleep(5)
                retries += 1
                if retries > 10:
                    log(f"❌ [{self.name}] Persistent failure. Stopping producer.", "error")
                    self.stopped = True
                continue
            
            log(f"🎥 [{self.name}] Producer started.")
            retries = 0
            
            while not self.stopped:
                for _ in range(3): # Drop frames to keep latency low
                    cap.grab()
                
                ok, frame = cap.read()
                if not ok or frame is None:
                    log(f"⚠️ [{self.name}] Invalid stream/frame. Forcing reconnection.", "warning")
                    cap.release()
                    break
                
                with self.lock:
                    self.frame = frame
                time.sleep(0.01)
            
            cap.release()
            
    def read(self):
        with self.lock:
            return self.frame.copy() if self.frame is not None else None

    def stop(self):
        self.stopped = True
        self.thread.join(timeout=2)

# ============================================================
# LLM & CONSUMER (Analysis)
# ============================================================

def analyze_llm(camera_name, frame) -> dict:
    img_b64 = to_b64_jpg(frame)
    img_data_uri = f"data:image/jpeg;base64,{img_b64}"
    system_prompt = env_str(f"SYSTEM_PROMPT_{camera_name}", required=False) or SYSTEM_PROMPT

    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": [{"type": "image_url", "image_url": {"url": img_data_uri}}]},
        ],
        "temperature": 0.1,
        "max_tokens": LLM_MAX_TOKENS,
    }

    url = LM_API + LM_PATH
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"}

    try:
        r = HTTP_SESSION.post(url, json=payload, headers=headers, timeout=LM_TIMEOUT)
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"]
        parsed = json.loads(raw)
        return {"score": float(parsed.get("score", 0.0)), "text": str(parsed.get("description") or ""), "b64": img_b64}
    except Exception as e:
        log(f"❌ LLM Error ({camera_name}): {e}", "error")
        return {"score": 0.0, "text": "LLM Analysis Error", "b64": img_b64}


def process_camera_analysis(stream: CameraStream):
    """Consumer: Pulls frame, analyzes it, triggers alerts based on SCORE."""
    name = stream.name
    log(f"🧠 [{name}] Consumer started.")
    last_tts_alert_at = 0.0
    last_siren_alert_at = 0.0
    preprocessor = FramePreprocessor()

    while not stream.stopped:
        frame = stream.read()
        if frame is None:
            time.sleep(1)
            continue

        frame = resize_if_needed(frame)
        save_last_frame(name, frame)
        analysis_frame, frame_meta = preprocessor.prepare(frame)

        if analysis_frame is None:
            log(f"⏭️ [{name}] LLM skipped: low scene change ({frame_meta['changed_ratio']:.4f})")
            for payload in flush_due_omnistatus_payloads():
                send_omnistatus_payload(payload)
            time.sleep(max(INTERVAL, MOTION_SKIP_SLEEP_SECONDS))
            continue

        res = analyze_llm(name, analysis_frame)

        score = res["score"]
        text = res["text"]
        log(f"")
        log(f"───────────────────────────────────────────────")
        log(f"📷  CAM: {name}")
        if frame_meta.get("crop"):
            log(f"   Frame: motion crop ({frame_meta.get('crop_area_ratio', 0):.1%} area, Δ={frame_meta['changed_ratio']:.4f})")
        else:
            log(f"   Frame: full ({frame_meta['reason']}, Δ={frame_meta['changed_ratio']:.4f})")
        log(f"   Score: {score:.2f}  |  {text}")
        log(f"───────────────────────────────────────────────")

        # === CRITICAL ALERT: TELEGRAM + LIGHTS + TTS + SIREN ===
        if score >= SCORE_CRITICAL_ALERT:
            run_critical_action_sequence(name, res, score, text, critical_action_state)

        # === LEVEL 2: WARNING (TTS) ===
        elif score >= SCORE_THRESHOLD: 
            send_telegram(res["b64"], f"⚠️ {name}: {text} | Risk={score:.2f}")
            if TTS_ENABLED:
                now = time.time()
                if now - last_tts_alert_at >= TTS_COOLDOWN:
                    log(f"🔊 Playing TTS for {name}")
                    play_audio_tts(TTS_MESSAGE, TTS_LANG, repeats=2, delay=1.0)
                    last_tts_alert_at = now
        
        inject_omnistatus(name, text, score, image_b64=res["b64"])
        for payload in flush_due_omnistatus_payloads():
            send_omnistatus_payload(payload)
        


        time.sleep(INTERVAL)

# ============================================================
# MAIN
# ============================================================

def send_telegram(img_b64: str, caption: str):
    if not ENABLE_TELEGRAM or not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID: return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        data = {"chat_id": TELEGRAM_CHAT_ID, "caption": caption[:1024]}
        files = {"photo": ("frame.jpg", base64.b64decode(img_b64), "image/jpeg")}
        HTTP_SESSION.post(url, data=data, files=files, timeout=20)
    except Exception:
        pass


def send_alert_webhook(url: Optional[str], level: str, source: str, score: float, text: str):
    if not url:
        return

    payload = {
        "source": source,
        "score": score,
        "text": text,
        "level": level,
        "ts": datetime.utcnow().isoformat() + "Z",
    }

    try:
        response = HTTP_SESSION.post(url, json=payload, timeout=10)
        if response.status_code >= 400:
            log(f"⚠️ {level} webhook returned {response.status_code}", "warning")
        else:
            log(f"💡 {level} webhook sent")
    except Exception as e:
        log(f"❌ {level} webhook error: {e}", "error")


def send_omnistatus_payload(payload: dict):
    if not ENABLE_OMNISTATUS or not OMNISTATUS_API: return
    
    # Ensure URL ends with /event
    # If the user put just binary URL (localhost:8001), append /event
    # If they put full URL, leave it. Check if it ends in /event or has query params
    target_url = OMNISTATUS_API
    if not target_url.endswith("/event") and not target_url.endswith("/events"):
        target_url = target_url.rstrip("/") + "/event"

    try:
        r = HTTP_SESSION.post(target_url, json=payload, timeout=5)
        
        if r.status_code == 422:
            log(f"❌ OmniStatus 422 Unprocessable Entity! Response: {r.text} | Payload: {json.dumps(payload)}", "error")
        elif r.status_code != 200:
            log(f"⚠️ OmniStatus returned {r.status_code}: {r.text}", "warning")
        elif payload.get("event_count", 1) > 1:
            log(f"📦 OmniStatus grouped payload sent: {payload['source']} x{payload['event_count']}")
            
    except Exception as e:
        log(f"❌ OmniStatus Error: {e}", "error")


def inject_omnistatus(source: str, text: str, score: float, image_b64: str = None):
    for payload in collect_omnistatus_payloads(source, text, score, image_b64):
        send_omnistatus_payload(payload)

def heartbeat_loop():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or not HEARTBEAT_ENABLED: return

    while True:
        try:
            now_str = time.strftime("%Y-%m-%d %H:%M:%S")
            msg = f"🟢 {SENTINEX_INSTANCE_NAME} Online | 📅 {now_str}"
            
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            data = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
            HTTP_SESSION.post(url, data=data, timeout=20)
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
            for payload in flush_all_omnistatus_payloads():
                send_omnistatus_payload(payload)
            for s in streams.values(): s.stop()
            break

if __name__ == "__main__":
    main()

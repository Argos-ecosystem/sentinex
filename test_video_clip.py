#!/usr/bin/env python3
"""
test_video_clip.py — Prueba del envío de mini video por Telegram.
Genera un clip sintético (frames de colores con texto) y lo envía.
No necesita cámaras RTSP ni LLM activo.
"""

import os
import cv2
import numpy as np
import tempfile
import requests
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CLIP_FPS = float(os.getenv("CLIP_FPS", "8"))
CLIP_PRE_SECONDS = float(os.getenv("CLIP_PRE_SECONDS", "3"))
CLIP_POST_SECONDS = float(os.getenv("CLIP_POST_SECONDS", "3"))

def generate_test_frames(num_frames=48, width=480, height=360):
    """Genera frames sintéticos que simulan pre-evento, evento y post-evento."""
    frames = []
    total = num_frames
    pre_count = total // 3
    event_count = total // 3
    post_count = total - pre_count - event_count

    for i in range(total):
        frame = np.zeros((height, width, 3), dtype=np.uint8)

        if i < pre_count:
            # Pre-evento: verde (normal)
            frame[:] = (40, 120, 40)
            phase = "PRE-EVENTO (Normal)"
            color = (100, 255, 100)
        elif i < pre_count + event_count:
            # Evento: rojo (alerta)
            intensity = int(80 + 175 * abs(np.sin(i * 0.3)))
            frame[:] = (30, 30, intensity)
            phase = "⚠ ALERTA DETECTADA"
            color = (50, 50, 255)
        else:
            # Post-evento: amarillo (seguimiento)
            frame[:] = (30, 100, 120)
            phase = "POST-EVENTO"
            color = (80, 200, 255)

        # Texto del timestamp
        timestamp = f"Frame {i+1}/{total}"
        cv2.putText(frame, "SENTINEX TEST", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
        cv2.putText(frame, phase, (20, 90),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
        cv2.putText(frame, timestamp, (20, 140),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
        cv2.putText(frame, datetime.now().strftime("%H:%M:%S"), (20, 180),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)

        # Simular movimiento
        cx = int(width * 0.3 + 150 * np.sin(i * 0.15))
        cy = int(height * 0.6 + 50 * np.cos(i * 0.2))
        cv2.circle(frame, (cx, cy), 25, (255, 255, 255), 2)
        cv2.putText(frame, "?", (cx - 8, cy + 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        frames.append(frame)

    return frames


def build_test_video(frames, fps):
    """Genera el MP4 temporal."""
    h, w = frames[0].shape[:2]
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".mp4", prefix="sentinex_test_")
    os.close(tmp_fd)

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(tmp_path, fourcc, fps, (w, h))

    if not writer.isOpened():
        print("❌ Error: No se pudo abrir VideoWriter")
        return None

    for frame in frames:
        writer.write(frame)

    writer.release()

    size_kb = os.path.getsize(tmp_path) / 1024
    duration = len(frames) / fps
    print(f"✅ Video generado: {tmp_path}")
    print(f"   📊 {len(frames)} frames | {duration:.1f}s | {size_kb:.0f}KB | {fps} FPS")
    return tmp_path


def send_video_telegram(video_path, caption):
    """Envía el video a Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID no configurados en .env")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "caption": caption[:1024],
        "supports_streaming": "true",
    }

    print(f"📤 Enviando video a Telegram (chat: {TELEGRAM_CHAT_ID})...")

    with open(video_path, "rb") as vf:
        files = {"video": ("test_alert.mp4", vf, "video/mp4")}
        r = requests.post(url, data=data, files=files, timeout=60)

    if r.status_code == 200:
        print("✅ ¡Video enviado exitosamente! Revisa tu Telegram.")
        return True
    else:
        print(f"❌ Error {r.status_code}: {r.text[:300]}")
        return False


def main():
    print("=" * 50)
    print("🎬 SENTINEX — Test de Video Clip para Telegram")
    print("=" * 50)

    total_seconds = CLIP_PRE_SECONDS + CLIP_POST_SECONDS
    total_frames = int(total_seconds * CLIP_FPS)

    print(f"\n📋 Configuración:")
    print(f"   Pre-evento:  {CLIP_PRE_SECONDS}s")
    print(f"   Post-evento: {CLIP_POST_SECONDS}s")
    print(f"   FPS:          {CLIP_FPS}")
    print(f"   Total:        {total_seconds}s ({total_frames} frames)")

    # 1. Generar frames
    print(f"\n🎨 Generando {total_frames} frames de prueba...")
    frames = generate_test_frames(num_frames=total_frames)
    print(f"   ✅ {len(frames)} frames generados")

    # 2. Crear video
    print(f"\n🎬 Creando video MP4...")
    video_path = build_test_video(frames, CLIP_FPS)

    if not video_path:
        print("❌ Fallo al crear el video. Abortando.")
        return

    # 3. Enviar a Telegram
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    caption = f"🧪 TEST Sentinex Video Alert\n📅 {now}\n⚠️ Alerta simulada | Score=0.85\n📹 Clip: {total_seconds}s @ {CLIP_FPS}fps"

    success = send_video_telegram(video_path, caption)

    # 4. Limpiar
    try:
        os.remove(video_path)
        print(f"🧹 Archivo temporal eliminado")
    except OSError:
        pass

    print("\n" + "=" * 50)
    if success:
        print("🎉 ¡Test completado! Revisa tu chat de Telegram.")
    else:
        print("⚠️  Test falló. Revisa los tokens de Telegram en .env")
    print("=" * 50)


if __name__ == "__main__":
    main()

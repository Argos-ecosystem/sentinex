import html
import os
from pathlib import Path
from urllib.parse import quote

from dotenv import dotenv_values, load_dotenv, set_key, unset_key
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.responses import FileResponse


ENV_FILE = Path(os.environ.get("SENTINEX_ENV_FILE") or ".env")
load_dotenv(ENV_FILE)


def env_required(name: str) -> str:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value.strip()


_last_dir = Path(env_required("LAST_FRAME_DIR"))
LAST_FRAME_DIR = _last_dir if _last_dir.is_absolute() else Path(__file__).resolve().parent / _last_dir
REFRESH_MS = int(env_required("ADMIN_REFRESH_MS"))
APP_TITLE = "Sentinex Admin"

app = FastAPI(title=APP_TITLE)


def normalize_name(raw: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in raw.strip())
    return cleaned.upper()


def load_cameras():
    data = dotenv_values(ENV_FILE)
    cams = {}
    for key, value in data.items():
        if not key.startswith("RTSP_URL_"):
            continue
        name = key.replace("RTSP_URL_", "", 1)
        cams[name] = {
            "url": value or "",
            "prompt": data.get(f"SYSTEM_PROMPT_{name}", "") or "",
        }
    return cams


def list_last_frames():
    frames = []
    if not LAST_FRAME_DIR.exists():
        return frames
    for path in LAST_FRAME_DIR.glob("*_last.jpg"):
        name = path.stem.replace("_last", "")
        frames.append({"name": name, "path": path.name})
    return sorted(frames, key=lambda x: x["name"])


def set_env_value(key: str, value: str):
    set_key(ENV_FILE, key, value, quote_mode="always")


def unset_env(key: str):
    unset_key(ENV_FILE, key)


def rename_camera(old_name: str, new_name: str):
    """Copy URL/prompt to new name and delete old keys."""
    data = dotenv_values(ENV_FILE)
    url = data.get(f"RTSP_URL_{old_name}")
    prompt = data.get(f"SYSTEM_PROMPT_{old_name}")
    if not url:
        return False, "Camera not found"
    # Overwrite destination if it already exists
    set_env_value(f"RTSP_URL_{new_name}", url)
    if prompt:
        set_env_value(f"SYSTEM_PROMPT_{new_name}", prompt)
    unset_env(f"RTSP_URL_{old_name}")
    unset_env(f"SYSTEM_PROMPT_{old_name}")
    return True, f"{old_name} -> {new_name}"


def render_page(cams: dict, message: str | None = None, status: str = "ok"):
    badge_color = "#0f172a" if status == "ok" else "#7f1d1d"
    msg_html = ""
    if message:
        msg_html = f"""
        <div class="toast" style="background:{badge_color};border:1px solid #94a3b8;">
            {html.escape(message)}
        </div>
        """

    cards_html = ""
    for name, cfg in sorted(cams.items()):
        prompt_short = (cfg["prompt"][:120] + "...") if len(cfg["prompt"]) > 120 else cfg["prompt"]
        cards_html += f"""
        <div class="card">
            <div class="card-header">
                <div class="pill">{html.escape(name)}</div>
                <form action="/cameras/{quote(name)}/delete" method="post" onsubmit="return confirm('Delete {html.escape(name)}?');">
                    <button class="ghost" type="submit">Delete</button>
                </form>
            </div>
            <div class="card-body">
                <form action="/cameras/{quote(name)}" method="post">
                    <label>RTSP URL</label>
                    <input name="url" value="{html.escape(cfg['url'])}" required />
                    <label>System Prompt</label>
                    <textarea name="prompt" rows="4" placeholder="System prompt for the LLM">{html.escape(cfg['prompt'])}</textarea>
                    <div class="hint">Preview: {html.escape(prompt_short)}</div>
                    <button type="submit">Save</button>
                </form>
                <form class="rename" action="/cameras/{quote(name)}/rename" method="post">
                    <label>Rename camera (copies URL/prompt and deletes the old one)</label>
                    <div class="rename-row">
                        <input name="new_name" placeholder="New name" required />
                        <button type="submit">Rename</button>
                    </div>
                </form>
            </div>
        </div>
        """

    frames = list_last_frames()

    frames_html = ""
    if frames:
        for f in frames:
            frames_html += f"""
            <div class="frame-card">
                <div class="frame-name">{html.escape(f['name'])}</div>
                <img src="/frames/{quote(f['path'])}" loading="lazy" />
            </div>
            """

    html_page = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>{APP_TITLE}</title>
        <style>
            :root {{
                --bg: #0b1220;
                --panel: #0f172a;
                --accent: #10b981;
                --accent-2: #eab308;
                --border: #1e293b;
                --text: #e2e8f0;
                --muted: #94a3b8;
            }}
            * {{ box-sizing: border-box; }}
            body {{
                margin: 0;
                min-height: 100vh;
                font-family: "JetBrains Mono", "SFMono-Regular", Menlo, Consolas, monospace;
                background: radial-gradient(circle at 20% 20%, rgba(16,185,129,0.12), transparent 30%),
                            radial-gradient(circle at 80% 0%, rgba(234,179,8,0.12), transparent 35%),
                            var(--bg);
                color: var(--text);
                padding: 24px;
            }}
            h1 {{
                letter-spacing: -0.02em;
                font-size: 28px;
                margin: 0 0 8px;
            }}
            .sub {{
                color: var(--muted);
                margin-bottom: 24px;
            }}
            .grid {{
                display: grid;
                gap: 16px;
                grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            }}
            .card {{
                background: var(--panel);
                border: 1px solid var(--border);
                border-radius: 12px;
                padding: 16px;
                box-shadow: 0 12px 30px rgba(0,0,0,0.35);
                display: flex;
                flex-direction: column;
                gap: 10px;
            }}
            .card-header {{
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 8px;
            }}
            .pill {{
                background: linear-gradient(135deg, var(--accent), #22d3ee);
                color: #0b1220;
                padding: 6px 12px;
                border-radius: 999px;
                font-weight: 700;
                font-size: 14px;
            }}
            label {{
                display: block;
                font-size: 12px;
                color: var(--muted);
                margin-bottom: 4px;
            }}
            input, textarea {{
                width: 100%;
                border-radius: 8px;
                border: 1px solid var(--border);
                background: #0b1629;
                color: var(--text);
                padding: 10px;
                font-family: inherit;
                font-size: 14px;
            }}
            textarea {{ min-height: 100px; }}
            button {{
                background: var(--accent);
                color: #0b1220;
                border: none;
                border-radius: 10px;
                padding: 10px 14px;
                font-weight: 700;
                cursor: pointer;
                transition: transform 120ms ease, box-shadow 120ms ease;
            }}
            button:hover {{ transform: translateY(-1px); box-shadow: 0 8px 20px rgba(16,185,129,0.35); }}
            button:active {{ transform: translateY(0); }}
            button.ghost {{
                background: transparent;
                color: var(--muted);
                border: 1px solid var(--border);
                box-shadow: none;
            }}
            .new-card {{
                border: 1px dashed var(--border);
                background: rgba(16,185,129,0.05);
            }}
            .hint {{
                color: var(--muted);
                font-size: 12px;
            }}
            .rename {{
                border-top: 1px solid var(--border);
                padding-top: 10px;
                margin-top: 6px;
            }}
            .rename-row {{
                display: flex;
                gap: 8px;
                align-items: center;
            }}
            .rename-row input {{
                flex: 1;
            }}
            .toast {{
                padding: 12px 16px;
                border-radius: 10px;
                margin-bottom: 16px;
                color: #e2e8f0;
            }}
            .footer {{
                margin-top: 32px;
                color: var(--muted);
                font-size: 13px;
            }}
            .badge {{
                display: inline-block;
                padding: 6px 10px;
                border-radius: 8px;
                background: #0b1629;
                border: 1px solid var(--border);
                margin-left: 8px;
            }}
            .frames {{
                margin-top: 24px;
            }}
            .frames h2 {{
                font-size: 18px;
                margin: 0 0 12px;
            }}
            .frames-grid {{
                display: grid;
                gap: 12px;
                grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            }}
            .frame-card {{
                border: 1px solid var(--border);
                border-radius: 10px;
                background: #0b1629;
                padding: 8px;
            }}
            .frame-name {{
                font-size: 12px;
                color: var(--muted);
                margin-bottom: 4px;
            }}
            .frame-card img {{
                width: 100%;
                display: block;
                border-radius: 8px;
                border: 1px solid var(--border);
                background: #020617;
                cursor: zoom-in;
                transition: transform 160ms ease, box-shadow 160ms ease;
            }}
            .frame-card img:hover {{
                transform: scale(1.01);
                box-shadow: 0 10px 30px rgba(0,0,0,0.4);
            }}
            .lightbox {{
                position: fixed;
                inset: 0;
                background: rgba(5,7,12,0.82);
                display: none;
                align-items: center;
                justify-content: center;
                padding: 24px;
                z-index: 9999;
            }}
            .lightbox img {{
                max-width: 90vw;
                max-height: 90vh;
                border-radius: 12px;
                border: 1px solid var(--border);
                box-shadow: 0 20px 60px rgba(0,0,0,0.6);
                background: #020617;
            }}
            .lightbox.show {{ display: flex; }}
        </style>
    </head>
    <body>
        <h1>{APP_TITLE}</h1>
        <div class="sub">Manage RTSP cameras and prompts in {html.escape(str(ENV_FILE))}</div>
        {msg_html}
        <div class="grid">
            <div class="card new-card">
                <div class="card-header">
                    <div class="pill">New camera</div>
                </div>
                <form action="/cameras" method="post">
                    <label>Name (will be converted to UPPERCASE_WITH_UNDERSCORES)</label>
                    <input name="name" placeholder="e.g: main_entrance" required />
                    <label>RTSP URL</label>
                    <input name="url" placeholder="rtsp://user:pass@ip:554/stream" required />
                    <label>System Prompt</label>
                    <textarea name="prompt" rows="4" placeholder="System prompt for the LLM"></textarea>
                    <button type="submit">Create</button>
                </form>
            </div>
            {cards_html}
        </div>
        <div class="frames">
            <h2>Last saved frames ({len(frames)})</h2>
            <div class="frames-grid">
                {frames_html if frames_html else '<div class="hint">No frames saved yet. Check that LAST_FRAME_DIR has *_last.jpg images.</div>'}
            </div>
        </div>
        <div class="footer">
            Active file: <span class="badge">{html.escape(str(ENV_FILE))}</span>
            | Reload the capture app to pick up changes.
        </div>
        <div id="lightbox" class="lightbox" onclick="this.classList.remove('show')">
            <img id="lightbox-img" src="" alt="frame" />
        </div>
        <script>
            const lb = document.getElementById('lightbox');
            const lbImg = document.getElementById('lightbox-img');
            document.querySelectorAll('.frame-card img').forEach(img => {{
                img.addEventListener('click', (e) => {{
                    lbImg.src = img.src;
                    lb.classList.add('show');
                }});
            }});
            document.addEventListener('keyup', (e) => {{
                if (e.key === 'Escape') lb.classList.remove('show');
            }});
            const REFRESH_MS = {REFRESH_MS};
            if (REFRESH_MS > 0) {{
                setInterval(() => window.location.reload(), REFRESH_MS);
            }}
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_page)


@app.get("/", response_class=HTMLResponse)
async def dashboard(msg: str | None = None, status: str = "ok"):
    cams = load_cameras()
    return render_page(cams, msg, status)


@app.post("/cameras", response_class=HTMLResponse)
async def create_camera(name: str = Form(...), url: str = Form(...), prompt: str = Form("")):
    ENV_FILE.touch(exist_ok=True)
    norm_name = normalize_name(name)
    set_env_value(f"RTSP_URL_{norm_name}", url.strip())
    if prompt.strip():
        set_env_value(f"SYSTEM_PROMPT_{norm_name}", prompt.strip())
    msg = quote(f"Camera {norm_name} saved")
    return RedirectResponse(url=f"/?msg={msg}&status=ok", status_code=303)


@app.post("/cameras/{name}", response_class=HTMLResponse)
async def update_camera(name: str, url: str = Form(...), prompt: str = Form("")):
    norm_name = normalize_name(name)
    set_env_value(f"RTSP_URL_{norm_name}", url.strip())
    if prompt.strip():
        set_env_value(f"SYSTEM_PROMPT_{norm_name}", prompt.strip())
    else:
        unset_env(f"SYSTEM_PROMPT_{norm_name}")
    msg = quote(f"Camera {norm_name} updated")
    return RedirectResponse(url=f"/?msg={msg}&status=ok", status_code=303)


@app.post("/cameras/{name}/delete", response_class=HTMLResponse)
async def delete_camera(name: str):
    norm_name = normalize_name(name)
    unset_env(f"RTSP_URL_{norm_name}")
    unset_env(f"SYSTEM_PROMPT_{norm_name}")
    msg = quote(f"Camera {norm_name} deleted")
    return RedirectResponse(url=f"/?msg={msg}&status=ok", status_code=303)


@app.post("/cameras/{name}/rename", response_class=HTMLResponse)
async def rename(name: str, new_name: str = Form(...)):
    old = normalize_name(name)
    new = normalize_name(new_name)
    ok, info = rename_camera(old, new)
    status = "ok" if ok else "error"
    msg = quote(info)
    return RedirectResponse(url=f"/?msg={msg}&status={status}", status_code=303)


@app.get("/frames/{filename}")
async def get_frame(filename: str):
    path = LAST_FRAME_DIR / filename
    if not path.exists():
        return HTMLResponse(status_code=404, content="Frame not found")
    return FileResponse(path, media_type="image/jpeg")

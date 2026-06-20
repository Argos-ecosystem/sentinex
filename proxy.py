import os
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import httpx

# Load .env.server configuration
load_dotenv(".env.server")


def env_required(name: str) -> str:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        raise RuntimeError(f"Missing required environment variable in .env.server: {name}")
    return value.strip()


# Base URL of LM Studio (WITHOUT /v1 suffix!)
LM_STUDIO_URL = env_required("LM_STUDIO_URL").rstrip("/")

# Internal API KEY (can be any string)
API_KEY = env_required("API_KEY")

app = FastAPI()


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(request: Request, path: str):

    # Get raw request body
    body = await request.body()

    # Build target URL
    target_url = f"{LM_STUDIO_URL}/{path.lstrip('/')}"  # avoid double slash

    # Headers to forward to LM Studio
    headers = {
        "Content-Type": request.headers.get("Content-Type", "application/json"),
        "Authorization": f"Bearer {API_KEY}"
    }

    # HTTP client with extended timeout
    async with httpx.AsyncClient(timeout=120) as client:
        try:
            resp = await client.request(
                request.method,
                target_url,
                headers=headers,
                content=body
            )
        except Exception as e:
            return JSONResponse(
                status_code=500,
                content={"error": f"Proxy error: {str(e)}"}
            )

    # Return EXACT response from LM Studio
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers={"Content-Type": resp.headers.get("Content-Type", "application/json")}
    )

from __future__ import annotations

import asyncio
import base64
import io

import httpx


async def generate_lineart(image_url: str, mode: str = "fine") -> str:
    """Fetch image_url, run lineart extraction, return base64 PNG."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            image_url,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; FindArt/0.1; +https://example.invalid/findart)",
                "Referer": "https://commons.wikimedia.org/",
            },
        )
        resp.raise_for_status()

    fn = _canny_lineart if mode == "canny" else _fine_lineart
    processed = await asyncio.to_thread(fn, resp.content)
    return base64.b64encode(processed).decode()


def _canny_lineart(image_bytes: bytes) -> bytes:
    import cv2
    import numpy as np

    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 50, 150)
    lineart = 255 - edges
    _, buf = cv2.imencode(".png", lineart)
    return buf.tobytes()


_detector = None


def _get_detector():
    global _detector
    if _detector is None:
        from controlnet_aux import LineartDetector
        _detector = LineartDetector.from_pretrained("lllyasviel/Annotators")
    return _detector


def _fine_lineart(image_bytes: bytes) -> bytes:
    from PIL import Image as PILImage

    img = PILImage.open(io.BytesIO(image_bytes)).convert("RGB")
    result = _get_detector()(img)
    buf = io.BytesIO()
    result.save(buf, format="PNG")
    return buf.getvalue()

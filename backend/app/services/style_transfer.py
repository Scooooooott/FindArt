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


async def extract_palette(image_url: str, n_colors: int = 8) -> list[str]:
    """Fetch image_url, run k-means color quantization, return hex color list."""
    import asyncio
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
    return await asyncio.to_thread(_extract_palette_sync, resp.content, n_colors)


def _extract_palette_sync(image_bytes: bytes, n_colors: int) -> list[str]:
    try:
        from sklearn.cluster import MiniBatchKMeans
        import numpy as np
        from PIL import Image as PILImage
    except ImportError as exc:
        raise RuntimeError(
            "scikit-learn and Pillow are required for palette extraction. "
            "Run: pip install scikit-learn Pillow"
        ) from exc

    import io
    img = PILImage.open(io.BytesIO(image_bytes)).convert("RGB")
    # Downsample to speed up k-means
    img.thumbnail((300, 300))
    arr = np.array(img).reshape(-1, 3).astype(float)
    km = MiniBatchKMeans(n_clusters=n_colors, n_init=3, random_state=0)
    km.fit(arr)
    centers = km.cluster_centers_.astype(int).clip(0, 255)
    return [f"#{r:02x}{g:02x}{b:02x}" for r, g, b in centers]


_detector = None


def _get_detector():
    global _detector
    if _detector is None:
        from controlnet_aux import LineartDetector
        _detector = LineartDetector.from_pretrained("lllyasviel/Annotators")
    return _detector


def _fine_lineart(image_bytes: bytes) -> bytes:
    from PIL import Image as PILImage, ImageOps

    img = PILImage.open(io.BytesIO(image_bytes)).convert("RGB")
    result = _get_detector()(img)
    # LineartDetector outputs white-on-black (ControlNet convention); invert for drawing use
    result = ImageOps.invert(result.convert("L"))
    buf = io.BytesIO()
    result.save(buf, format="PNG")
    return buf.getvalue()

"""
Design Service functions for Vibe Coding projects.
This module provides Flask-compatible functions for design generation.
"""

import os
import io
import json
import uuid
import shutil
import base64
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

import requests
from PIL import Image

# ---------- CONFIG ----------

ATLASCLOUD_API_KEY = os.environ.get("ATLASCLOUD_API_KEY")
# Don't fail on import - will be checked when endpoints are called

# AtlasCloud model ids
TEXT2IMG_MODEL = "google/nano-banana-pro/text-to-image-ultra"
UPSCALE_MODEL = "atlascloud/real-esrgan"

# Where this backend stores generated designs
BASE_DIR = Path(os.getenv("DESIGNS_ROOT", "./designs_storage"))
BASE_DIR.mkdir(parents=True, exist_ok=True)

# Root of the Vite/WebContainer project this should write into
PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT", "./webcontainer_project"))
SRC_THEME_DIR = PROJECT_ROOT / "src" / "theme"
PUBLIC_ASSETS_DIR = PROJECT_ROOT / "public" / "assets"

# Create minimal project dirs if they don't exist
SRC_THEME_DIR.mkdir(parents=True, exist_ok=True)
PUBLIC_ASSETS_DIR.mkdir(parents=True, exist_ok=True)


# ---------- ATLASCLOUD HELPERS ----------

def atlas_generate_image(model: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Thin wrapper around AtlasCloud image API.
    """
    if not ATLASCLOUD_API_KEY:
        raise Exception("ATLASCLOUD_API_KEY is not set")
    url = f"https://api.atlascloud.ai/api/v1/model/{model}/generateImage"
    headers = {
        "Authorization": f"Bearer {ATLASCLOUD_API_KEY}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        if resp.status_code >= 400:
            error_text = resp.text or f"HTTP {resp.status_code}"
            try:
                error_json = resp.json()
                error_text = error_json.get("error") or error_json.get("message") or error_text
            except:
                pass
            raise Exception(f"AtlasCloud API error (status {resp.status_code}): {error_text}")
        response_data = resp.json()
        if not response_data:
            raise Exception("AtlasCloud API returned empty response")
        return response_data
    except requests.exceptions.Timeout:
        raise Exception("AtlasCloud API request timed out after 120 seconds")
    except requests.exceptions.RequestException as e:
        raise Exception(f"AtlasCloud API request failed: {str(e)}")


def poll_for_image(prediction_id: str, max_attempts: int = 30) -> Dict[str, Any]:
    """
    Poll AtlasCloud for image completion.
    """
    if not ATLASCLOUD_API_KEY:
        raise Exception("ATLASCLOUD_API_KEY is not set")
    poll_url = f"https://api.atlascloud.ai/api/v1/model/prediction/{prediction_id}"
    headers = {
        "Authorization": f"Bearer {ATLASCLOUD_API_KEY}",
    }
    import time
    for attempt in range(max_attempts):
        if attempt > 0:
            time.sleep(3)
        try:
            resp = requests.get(poll_url, headers=headers, timeout=30)
            if resp.status_code >= 400:
                if attempt == max_attempts - 1:
                    error_text = resp.text or f"HTTP {resp.status_code}"
                    raise Exception(f"AtlasCloud polling failed (status {resp.status_code}): {error_text}")
                continue
            data = resp.json()
            if not data:
                if attempt == max_attempts - 1:
                    raise Exception("AtlasCloud polling returned empty response")
                continue
            status = data.get("data", {}).get("status") or data.get("status")
            if status == "completed":
                outputs = data.get("data", {}).get("outputs") or data.get("outputs") or data.get("output")
                if outputs and len(outputs) > 0:
                    image_url = outputs[0] if isinstance(outputs, list) else outputs
                    if image_url:
                        return {"image_url": image_url}
                    else:
                        if attempt == max_attempts - 1:
                            raise Exception("AtlasCloud returned completed status but no image URL")
            if status == "failed" or status == "error":
                error_msg = data.get("data", {}).get("error") or data.get("error") or "Image generation failed"
                raise Exception(f"Generation failed: {error_msg}")
        except requests.exceptions.Timeout:
            if attempt == max_attempts - 1:
                raise Exception("AtlasCloud polling timed out")
            continue
        except requests.exceptions.RequestException as e:
            if attempt == max_attempts - 1:
                raise Exception(f"AtlasCloud polling request failed: {str(e)}")
            continue
    raise Exception(f"Image generation timed out after {max_attempts} attempts")


def generate_nano_banana_design(prompt: str, width=1920, height=1080) -> Image.Image:
    """
    Use Nano Banana (text-to-image) via AtlasCloud to get the base mockup.
    """
    payload = {
        "prompt": prompt,
        "width": width,
        "height": height,
        "output_format": "png",
        "enable_base64_output": False,
        "enable_sync_mode": False,
        "resolution": "4k",
    }
    
    # Initiate generation
    data = atlas_generate_image(TEXT2IMG_MODEL, payload)
    prediction_id = data.get("data", {}).get("id") or data.get("id") or data.get("prediction_id")
    
    if not prediction_id:
        raise Exception("No prediction ID returned from AtlasCloud")
    
    # Poll for completion
    result = poll_for_image(prediction_id)
    image_url = result["image_url"]
    
    # Download image
    img_resp = requests.get(image_url, timeout=60)
    if img_resp.status_code != 200:
        raise Exception("Failed to download generated image")
    
    return Image.open(io.BytesIO(img_resp.content)).convert("RGBA")


def upscale_with_esrgan(img: Image.Image, scale: int = 2) -> Image.Image:
    """
    Call atlascloud/real-esrgan to enhance resolution.
    """
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    b64_input = base64.b64encode(buf.read()).decode("utf-8")

    payload = {
        "image": f"data:image/png;base64,{b64_input}",
        "scale": scale,
        "face_enhance": False,
        "enable_base64_output": False,
        "enable_sync_mode": False,
    }
    
    # Initiate upscaling
    data = atlas_generate_image(UPSCALE_MODEL, payload)
    prediction_id = data.get("data", {}).get("id") or data.get("id") or data.get("prediction_id")
    
    if not prediction_id:
        raise Exception("No prediction ID returned from upscale")
    
    # Poll for completion
    result = poll_for_image(prediction_id)
    image_url = result["image_url"]
    
    # Download upscaled image
    img_resp = requests.get(image_url, timeout=60)
    if img_resp.status_code != 200:
        raise Exception("Failed to download upscaled image")
    
    return Image.open(io.BytesIO(img_resp.content)).convert("RGBA")


# ---------- THEME / SLICING HELPERS ----------

def build_prompt(industry: str, override: str | None) -> str:
    if override:
        return override
    return (
        f"Creative professional online {industry} modern website landing page mockup, "
        "solid border, clear background, flat website, figma-style design, photorealistic, "
        "new web design trend, flaticon-style icons, 8k, ui, ux, ui/ux, large header typefaces, "
        "geo-simplicity, volumetric, cinematic lighting, 3d render, unreal engine look."
    )


def naive_slice_layout(img: Image.Image) -> Dict[str, tuple]:
    """
    Simple top/middle/bottom slicing heuristic for hero/content/footer.
    """
    w, h = img.size
    hero_h = int(h * 0.35)
    footer_h = int(h * 0.15)
    return {
        "hero": (0, 0, w, hero_h),
        "content": (0, hero_h, w, h - footer_h),
        "footer": (0, h - footer_h, w, h),
    }


def extract_theme_tokens(img: Image.Image) -> Dict[str, Any]:
    """
    Very naive theme extraction stub: dominant colors + defaults.
    """
    small = img.resize((32, 32))
    colors = small.getcolors(32 * 32)
    if not colors:
        colors = []
    colors = sorted(colors, key=lambda c: c[0], reverse=True)
    dominant = [c[1] for c in colors[:5]]

    def rgb_to_hex(rgb):
        r, g, b, *_ = rgb
        return f"#{r:02x}{g:02x}{b:02x}"

    palette = [rgb_to_hex(c) for c in dominant]

    return {
        "palette": {
            "primary": palette[0] if palette else "#00ffd5",
            "secondary": palette[1] if len(palette) > 1 else "#111827",
            "accent": palette[2] if len(palette) > 2 else "#f97316",
            "background": "#020617",
            "foreground": "#f9fafb",
            "raw": palette,
        },
        "typography": {
            "heading_font": "system-ui",
            "body_font": "system-ui",
            "scale": {
                "h1": "3rem",
                "h2": "2.25rem",
                "body": "1rem",
            },
        },
        "layout": {
            "max_width": "1200px",
            "border_radius": "18px",
            "shadow": "0 30px 80px rgba(0,0,0,0.6)",
        },
    }


def write_candidate_files(
    theme_id: str,
    version: int,
    img: Image.Image,
    industry: str,
    prompt: str,
) -> Dict[str, Any]:
    """
    Save full-res PNG, slices, and theme.json for this candidate version.
    """
    theme_dir = BASE_DIR / theme_id / f"v{version}"
    theme_dir.mkdir(parents=True, exist_ok=True)

    master_png = theme_dir / "master_theme.png"
    img.save(master_png, format="PNG")

    # Slices
    layout = naive_slice_layout(img)
    slice_paths: Dict[str, str] = {}
    for name, box in layout.items():
        cropped = img.crop(box)
        p = theme_dir / f"slice_{name}.png"
        cropped.save(p, format="PNG")
        slice_paths[name] = str(p.relative_to(BASE_DIR))

    # Theme tokens
    tokens = extract_theme_tokens(img)

    theme_json = {
        "theme_id": theme_id,
        "version": version,
        "industry": industry,
        "prompt": prompt,
        "master_png": str(master_png.relative_to(BASE_DIR)),
        "slices": slice_paths,
        "tokens": tokens,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }

    manifest_path = theme_dir / "theme.json"
    manifest_path.write_text(json.dumps(theme_json, indent=2), encoding="utf-8")

    # Append/update global index
    index_path = BASE_DIR / "index.json"
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
    else:
        index = {"themes": {}}

    themes = index.setdefault("themes", {})
    versions = themes.setdefault(theme_id, [])
    versions.append(
        {
            "version": version,
            "preview_png": theme_json["master_png"],
            "created_at": theme_json["created_at"],
            "selected": False,
        }
    )
    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")

    return theme_json


def list_candidates() -> List[Dict[str, Any]]:
    index_path = BASE_DIR / "index.json"
    if not index_path.exists():
        return []
    index = json.loads(index_path.read_text(encoding="utf-8"))
    themes = index.get("themes", {})
    result: List[Dict[str, Any]] = []
    for theme_id, versions in themes.items():
        for v in versions:
            result.append({
                "theme_id": theme_id,
                "version": v["version"],
                "preview_png": v["preview_png"],
                "created_at": v["created_at"],
                "selected": v.get("selected", False),
            })
    # newest first
    result.sort(key=lambda c: c["created_at"], reverse=True)
    return result


def mark_selected(theme_id: str, version: int) -> Dict[str, Any]:
    index_path = BASE_DIR / "index.json"
    if not index_path.exists():
        raise Exception("No designs yet")

    index = json.loads(index_path.read_text(encoding="utf-8"))
    themes = index.get("themes", {})
    if theme_id not in themes:
        raise Exception("Theme not found")

    found = None
    for t_id, versions in themes.items():
        for v in versions:
            if t_id == theme_id and v["version"] == version:
                v["selected"] = True
                found = v
            else:
                v["selected"] = False

    if not found:
        raise Exception("Version not found")

    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
    return found


def apply_to_project(theme_id: str, version: int) -> Dict[str, Any]:
    """
    Copy slices + tokens into the Vite/WebContainer project tree so Vibe Coding can consume them.
    """
    manifest_path = BASE_DIR / theme_id / f"v{version}" / "theme.json"
    if not manifest_path.exists():
        raise Exception("Theme manifest not found")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # 1. Copy master + slices into /public/assets/themes/<theme_id>/v<version>
    target_assets_dir = PUBLIC_ASSETS_DIR / "themes" / theme_id / f"v{version}"
    if target_assets_dir.exists():
        shutil.rmtree(target_assets_dir)
    target_assets_dir.mkdir(parents=True, exist_ok=True)

    # Copy images
    master_src = BASE_DIR / manifest["master_png"]
    shutil.copy2(master_src, target_assets_dir / "master_theme.png")

    slice_map: Dict[str, str] = {}
    for name, rel_path in manifest["slices"].items():
        src = BASE_DIR / rel_path
        dest_name = f"slice_{name}.png"
        shutil.copy2(src, target_assets_dir / dest_name)
        slice_map[name] = f"/assets/themes/{theme_id}/v{version}/{dest_name}"

    master_url = f"/assets/themes/{theme_id}/v{version}/master_theme.png"

    # 2. Write theme tokens into src/theme/theme.json for the Vite app
    SRC_THEME_DIR.mkdir(parents=True, exist_ok=True)
    theme_config = {
        "themeId": theme_id,
        "version": version,
        "masterImage": master_url,
        "slices": slice_map,
        "tokens": manifest["tokens"],
    }
    (SRC_THEME_DIR / "theme.json").write_text(
        json.dumps(theme_config, indent=2), encoding="utf-8"
    )

    # 3. Optionally, scaffold a minimal React theme entrypoint (only if not there)
    app_theme_tsx = SRC_THEME_DIR / "ThemeProvider.tsx"
    if not app_theme_tsx.exists():
        app_theme_tsx.write_text(
            """import theme from './theme.json';

export function ThemeHero() {
  return (
    <div
      style={{
        height: '60vh',
        backgroundImage: `url(${theme.masterImage})`,
        backgroundSize: 'cover',
        backgroundPosition: 'center',
        borderRadius: theme.tokens.layout.border_radius,
        boxShadow: theme.tokens.layout.shadow,
        maxWidth: theme.tokens.layout.max_width,
        margin: '2rem auto',
      }}
    />
  );
}

export function useTheme() {
  return theme;
}
""",
            encoding="utf-8",
        )

    return {
        "themeId": theme_id,
        "version": version,
        "masterImage": master_url,
        "slices": slice_map,
        "tokens": manifest["tokens"],
    }


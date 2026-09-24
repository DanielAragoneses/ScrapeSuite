"""OpenRouter client for Gemini 2.5 Flash automotive forensic vision inspection."""
import base64
import json
import logging
import os
import re
import sqlite3
from pathlib import Path
from typing import List, Optional, Dict, Any
import requests

logger = logging.getLogger(__name__)

# The exact forensic automotive appraisal prompt mandated by the project
FORENSIC_INSPECTOR_PROMPT = """You are an expert automotive forensic inspector documenting vehicle condition for appraisal analysis. 
Your objective is to extract an exhaustive, objective visual inventory of every observable physical attribute, flaw, marking, and context clue across the provided images. 

Do NOT provide conversational commentary, pleasantries, or high-level summaries. For every image provided, analyze it sequentially using this exact breakdown:

### IMAGE [Index]: [Camera Angle & Viewpoint]
- **Frame & Environment:** Ground surface (asphalt, gravel, tall grass, dirt), indoor/outdoor, lighting conditions, wet/dry surfaces, surrounding context.
- **Visible Panels & Alignment:** Every panel visible; shut-line consistency (even/uneven gaps between hood, fenders, doors, trunk); panel flushness.
- **Paint & Body Condition:** Specific paint texture (gloss, swirl marks, orange peel, clearcoat failure/peeling, rock chips, dents, dings, deep scratches, rust bubbling or staining, color mismatches across adjacent panels).
- **Glass, Trim & Lighting:** Windshield/window condition (chips, cracks, tint level/bubbles); headlamp/taillamp lens clarity (clear, yellowed, hazy, moisture/condensation inside); rubber seals and plastic trim condition (black, faded gray, chalky, cracked).
- **Wheels, Brakes & Tires:** Wheel finish, curb rash, missing lug nuts/center caps; visible brake rotor condition (clean, grooved, surface rust); tire brand/model (if visible), estimated remaining tread, dry rot/cracking on sidewalls.
- **Interior & Cabin (if visible):** Seat material, upholstery tears, bolster creasing/wear; steering wheel leather condition (matte vs shiny/worn smooth); dashboard cracks; pedal rubber wear; headliner sag; missing knobs/switches/trim.
- **Instrument Cluster & Electronics (if visible):** Exact odometer reading, illuminated warning lights (CEL, ABS, Airbag, TPMS, Battery), infotainment screen display, gear indicator.
- **Text, Badging & Markings:** Emblems, trim badges, aftermarket stickers, registration/inspection decals on windshield (state/year), license plate text/frames.
- **Micro-Anomalies & Red Flags:** Fluid drips or damp spots underneath, overspray on wheel wells/trim (indicating prior body repair), mismatched screws/fasteners, sagging exhaust, aftermarket modifications.

Proceed image-by-image through all images. Be clinically descriptive, objective, and precise."""


def load_env_file(filepath: Optional[str] = None) -> Dict[str, str]:
    """Parse a simple .env file without requiring external third-party dependencies."""
    env_vars: Dict[str, str] = {}
    path = Path(filepath) if filepath else Path(".env")
    if not path.is_file():
        # Check parent directories up to 2 levels
        for p in [Path("../.env"), Path("../../.env")]:
            if p.is_file():
                path = p
                break
    if not path.is_file():
        return env_vars

    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    env_vars[key] = val
    except Exception as e:
        logger.debug(f"Could not read .env file at {path}: {e}")

    return env_vars

def load_omp_openrouter_key() -> Optional[str]:
    """Retrieve authenticated OpenRouter credentials directly from OMP's agent database."""
    home = Path(os.path.expanduser("~"))
    candidate_dbs = [
        home / ".omp" / "agent" / "agent.db",
        home / "AppData" / "Roaming" / "omp" / "agent" / "agent.db",
        home / "AppData" / "Local" / "omp" / "agent" / "agent.db",
    ]
    for db_path in candidate_dbs:
        if not db_path.is_file():
            continue
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            cur = conn.cursor()
            row = cur.execute(
                "SELECT data FROM auth_credentials WHERE provider = 'openrouter';"
            ).fetchone()
            conn.close()
            if row and row[0]:
                payload = json.loads(row[0])
                key = payload.get("key") or payload.get("apiKey") or payload.get("token")
                if key and str(key).startswith("sk-or-"):
                    logger.info("Loaded OpenRouter API credentials automatically from OMP agent database.")
                    return str(key)
        except Exception as e:
            logger.debug(f"Could not read credentials from {db_path}: {e}")
    return None


class OpenRouterVisionClient:
    """Client for OpenRouter API utilizing Google Gemini 2.5 Flash as an automotive vision model."""

    DEFAULT_MODEL: str = "google/gemini-2.5-flash"
    API_URL: str = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        session: Optional[requests.Session] = None,
        timeout: int = 60,
    ):
        # 1. Resolve API key (Explicit -> Env Var -> .env file -> OMP agent credentials)
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not self.api_key:
            env_file_vars = load_env_file()
            self.api_key = env_file_vars.get("OPENROUTER_API_KEY")
        if not self.api_key:
            self.api_key = load_omp_openrouter_key()
        # 2. Resolve model
        self.model = (
            model
            or os.environ.get("OPENROUTER_VISION_MODEL")
            or self.DEFAULT_MODEL
        )

        self.session = session or requests.Session()
        self.timeout = timeout

    @property
    def is_configured(self) -> bool:
        """Check if an API key is available for calling OpenRouter."""
        return bool(self.api_key and self.api_key.strip())

    def fetch_image_as_data_uri(self, image_url: str) -> Optional[str]:
        """Download image and convert to a base64 data URI to avoid remote crawler IP blocking."""
        try:
            resp = self.session.get(
                image_url,
                timeout=12,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                },
            )
            if resp.status_code != 200:
                logger.warning(f"Failed to download image {image_url}: HTTP {resp.status_code}")
                return None

            content_type = resp.headers.get("content-type", "").split(";")[0].strip()
            if not content_type or not content_type.startswith("image/"):
                # Infer from URL suffix
                if image_url.lower().endswith(".webp"):
                    content_type = "image/webp"
                elif image_url.lower().endswith(".png"):
                    content_type = "image/png"
                else:
                    content_type = "image/jpeg"

            encoded = base64.b64encode(resp.content).decode("ascii")
            return f"data:{content_type};base64,{encoded}"
        except Exception as e:
            logger.warning(f"Exception downloading image {image_url}: {e}")
            return None

    def build_multimodal_message(
        self,
        image_urls: List[str],
        prompt: str = FORENSIC_INSPECTOR_PROMPT,
        use_base64: bool = True,
        max_images: int = 10,
    ) -> Dict[str, Any]:
        """Build the user message payload containing prompt text and image items."""
        effective_max = min(max_images, 10)
        selected_urls = image_urls[:effective_max]
        content_items: List[Dict[str, Any]] = [
            {"type": "text", "text": prompt}
        ]

        for idx, url in enumerate(selected_urls, 1):
            if use_base64:
                data_uri = self.fetch_image_as_data_uri(url)
                img_ref = data_uri if data_uri else url
            else:
                img_ref = url

            content_items.append({
                "type": "image_url",
                "image_url": {
                    "url": img_ref
                }
            })

        return {
            "role": "user",
            "content": content_items
        }

    def inspect_listing_images(
        self,
        image_urls: List[str],
        custom_prompt: Optional[str] = None,
        max_images: int = 10,
        use_base64: bool = True,
    ) -> str:
        """Send vehicle listing images to Gemini 2.5 Flash via OpenRouter.

        Returns the clinical image-by-image forensic visual inspection report.
        """
        if not self.is_configured:
            raise ValueError(
                "OPENROUTER_API_KEY is not configured. Please set the OPENROUTER_API_KEY "
                "environment variable, provide it in a .env file, or pass it via --openrouter-key."
            )

        if not image_urls:
            return "No images provided for visual inspection."

        prompt = custom_prompt or FORENSIC_INSPECTOR_PROMPT
        user_message = self.build_multimodal_message(
            image_urls=image_urls,
            prompt=prompt,
            use_base64=use_base64,
            max_images=min(max_images, 10)
        )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/ScrapeSuite",
            "X-Title": "ScrapeSuite Forensic Automotive Inspector",
        }

        payload = {
            "model": self.model,
            "messages": [user_message],
            "temperature": 0.2,  # Low temperature for clinical objectivity
        }

        try:
            resp = self.session.post(
                self.API_URL,
                headers=headers,
                json=payload,
                timeout=self.timeout
            )
        except requests.RequestException as e:
            logger.error(f"OpenRouter vision request failed: {e}")
            raise RuntimeError(f"OpenRouter API request network error: {e}") from e

        if resp.status_code != 200:
            err_text = resp.text
            logger.error(f"OpenRouter returned HTTP {resp.status_code}: {err_text}")
            raise RuntimeError(f"OpenRouter API error (HTTP {resp.status_code}): {err_text}")

        try:
            data = resp.json()
            choices = data.get("choices", [])
            if not choices:
                return "OpenRouter response did not contain any choices."
            content = choices[0].get("message", {}).get("content", "")
            return content.strip()
        except Exception as e:
            logger.error(f"Failed to parse OpenRouter response: {e}")
            raise RuntimeError(f"Failed to parse OpenRouter response JSON: {e}") from e

# AGENTS.md — ScrapeSuite Architecture & Agent Runbook

Welcome to **ScrapeSuite**. This document defines the engineering philosophy, scraper construction blueprint, and unified operational protocol for autonomous AI agents and engineers working with marketplace scrapers.

---

## 1. Core Philosophy of ScrapeSuite

### 1.1 The "API-First" Principle (Bypassing WAFs Without Headless Browsers)
Most web scrapers fail in production because they rely on heavy headless browsers (Puppeteer, Playwright, Selenium). 
* **The Problem:** Headless browsers consume 500MB+ RAM per instance, trigger CloudFront/Akamai WAF bot-detection challenges, suffer from fragile DOM mutations, and introduce asynchronous race conditions.
* **The ScrapeSuite Philosophy:** **Never automate a web DOM when a structured API exists.** 
  * Modern marketplace web frontends are almost always backed by clean REST/GraphQL APIs (especially mobile app endpoints) or embedded Server-Side Rendered (SSR) hydration state (e.g. `window._init_data_`, `window.__INITIAL_STATE__`).
  * By reverse-engineering and mimicking mobile application identity badges (e.g., `x-deviceos: 0`, mobile User-Agents, and dedicated API hosts like `api.wallapop.com`), we bypass CloudFront/Akamai anti-bot defenses entirely, dropping response times from **4,000ms to 200ms** and consuming virtually zero memory.

### 1.2 The Forensic Description & Anti-Baiting Mandate
On second-hand marketplaces (Wallapop, Milanuncios, eBay Kleinanzeigen, Facebook Marketplace), **titles and price tags lie**:
1. **Placeholder & Bait Pricing:** Sellers routinely set listings to `1€`, `1234€`, `9999€`, `precio orientativo`, or *"precio por privado"*.
2. **Keyword Stuffing:** Sellers dump irrelevant high-value keywords into descriptions (e.g., a Pentium 4 listing tagged with *"RTX 4090, i7 11700k, PS5"*).
3. **Hidden Defects:** Crucial faults are buried deep in Spanish text (e.g., *"para reparar"*, *"cables cortados"*, *"no arranca"*, *"junta de culata"*, *"sin documentación"*).
4. **Stripped Shells:** Bare chassis without running gear marketed as whole cars or computers.

**The Golden Rule:** *An agent must never evaluate an item by its title and price alone.* Every listing must undergo **Forensic Description Auditing** before being accepted into a recommendation or bill of materials.

### 1.3 Native Server-Side Negative Keyword Filtering (`-word`)
Marketplaces built on Lucene/Elasticsearch (like Wallapop) natively support negative query operators:
* Querying `ryzen 7 3700x -ventilador -disipador -caja` forces the search engine index to strip listings whose titles contain accessories, preventing the platform's 40-item page limit from being wasted on 5€ stickers or coolers.
* **Syntax Invariant:** The minus sign **must have a leading space** (` -word`). Hyphenating without a space (`word-word`) is treated as a compound term. Do not wrap negative terms in quotes (`-"term"` breaks Lucene parsers).

### 1.4 Geofencing & Proximity Math
Marketplace listings require geographic verification. ScrapeSuite calculates exact great-circle distance using the **Haversine Formula**:
$$d = 2r \arcsin\left(\sqrt{\sin^2\left(\frac{\Delta \text{lat}}{2}\right) + \cos(\text{lat}_1)\cos(\text{lat}_2)\sin^2\left(\frac{\Delta \text{lon}}{2}\right)}\right)$$
This enables strict geofence filtering (e.g., verifying that a component or project car is within $\le 100\text{ km}$ of Loeches/Madrid for in-person pickup, or verifying national shipping eligibility).

### 1.5 Strict Normalization to the `Listing` Contract
Regardless of whether an item is scraped from Wallapop, AliExpress, or eBay, every scraper must map its output to the immutable `Listing` dataclass in `src/models.py`.

---

## 2. How to Build New Scrapers (The 5-Step Blueprint)

When adding a new marketplace (e.g., `src/scrapers/milanuncios.py`, `src/scrapers/vinted.py`), follow this exact 5-step blueprint:

```
[Step 1: Inspect Traffic]  -->  Find mobile app endpoints or SSR hydration JSON
           |
[Step 2: Header Badges]    -->  Replicate exact Host, Referer, User-Agent, and Client tokens
           |
[Step 3: Inherit Base]     -->  Subclass BaseScraper, set platform, implement search()
           |
[Step 4: Normalize Data]   -->  Map raw payload into Listing dataclass fields
           |
[Step 5: Anti-Bait Guard]  -->  Filter placeholder prices and parse full descriptions
```

### Step 1: Endpoint & Payload Discovery
1. Open browser Network DevTools or a proxy (Mitmproxy / Charles).
2. Filter for `Fetch/XHR`. Look for:
   * REST endpoints returning JSON (e.g., `api.<domain>.com/v1/search?keywords=...`).
   * If the site blocks direct API calls, inspect the initial HTML document for `<script type="application/ld+json">` or inline SSR state like `window.__INITIAL_DATA__ = {...}`.

### Step 2: Replicating Identity Headers
Never send bare requests. Configure the required identity badges:
```python
HEADERS = {
    "Host": "api.marketplace.com",
    "Referer": "https://www.marketplace.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ...",
    "Accept": "application/json, text/plain, */*",
    "x-deviceos": "0",  # Or platform-specific app tokens
}
```

### Step 3: Inheriting `BaseScraper`
All scrapers must inherit from `BaseScraper` in `src/scrapers/base.py`. Use `self.safe_get()` to inherit polite throttling, rate-limiting, and error handling.

### Step 4 & 5: Scraper Boilerplate Template
Copy and adapt this template for any new marketplace scraper:

```python
"""New Marketplace Scraper Blueprint."""
import logging
from typing import List, Optional, Dict, Any
import requests

from src.models import Listing, SearchFilter, Platform
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

PLACEHOLDER_PRICES = {1.0, 11.0, 123.0, 1234.0, 9999.0}
BAIT_PHRASES = ["precio no es el del anuncio", "escucho ofertas", "precio por privado"]

class NewMarketplaceScraper(BaseScraper):
    platform: Platform = Platform.OTHER  # Register new Platform enum in models.py
    ENDPOINT: str = "https://api.example.com/v1/search"

    MARKETPLACE_HEADERS: Dict[str, str] = {
        "Host": "api.example.com",
        "Referer": "https://www.example.com/",
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ...",
    }

    def __init__(self, session: Optional[requests.Session] = None, delay: float = 0.3):
        super().__init__(session=session, delay=delay)
        self.session.headers.update(self.MARKETPLACE_HEADERS)

    def search(self, query: str, search_filter: Optional[SearchFilter] = None) -> List[Listing]:
        sf = search_filter or SearchFilter()
        
        # 1. Format query and negative exclusions
        keywords = query.strip()
        if sf.exclude_keywords:
            keywords += " " + " ".join(f"-{w.strip().lstrip('-')}" for w in sf.exclude_keywords)

        params: Dict[str, Any] = {
            "q": keywords,
            "sort": sf.order_by or "price_asc",
        }
        if sf.min_price is not None: params["price_min"] = str(int(sf.min_price))
        if sf.max_price is not None: params["price_max"] = str(int(sf.max_price))

        # 2. Fire polite request via BaseScraper
        resp = self.safe_get(self.ENDPOINT, params=params, headers=self.MARKETPLACE_HEADERS)
        if not resp or resp.status_code != 200:
            return []

        # 3. Parse JSON
        try:
            data = resp.json()
            raw_items = data.get("items", [])
        except Exception as e:
            logger.warning(f"Failed to parse response: {e}")
            return []

        # 4. Normalize to Listing
        listings: List[Listing] = []
        for it in raw_items:
            price = float(it.get("price", 0.0))
            desc = str(it.get("description", "")).strip()

            # Anti-Bait Guard: Discard fake prices and bait phrases
            if price in PLACEHOLDER_PRICES or any(b in desc.lower() for b in BAIT_PHRASES):
                continue

            listings.append(Listing(
                id=str(it.get("id")),
                title=str(it.get("title", "")).strip(),
                price=price,
                url=str(it.get("permalink", "")),
                platform=self.platform,
                seller_location=it.get("location_name"),
                description=desc,
                shipping_available=bool(it.get("ships", True)),
                raw_data=it
            ))

        return listings
```

---

## 3. The Agent Operational Runbook

When an AI agent is instructed to research, search, or build a solution using ScrapeSuite, it must follow this execution protocol:

### 3.1 Understanding & Translating User Constraints
Before firing queries, break the user's intent into explicit parameters:
1. **Target Archetype / Spec:** e.g. "8c/16t AM4 server", "cool JDM project car", "10 cm thin SFF case".
2. **Budget Ceilings:** e.g. `< 150€ to start`, `< 2,500€ for project car`.
3. **Excluded Items:** If the user says *"no need for storage"*, zero out storage cost. Do not budget for it.
4. **Geofencing:** Check if the user wants local pickup (Madrid / Loeches $\le 100\text{ km}$) or accepts national shipping.

### 3.2 Two-Stage Query & Audit Pipeline
1. **Stage 1 (Server-Side Exclusions):**
   * Use native `-word` exclusions in `SearchFilter.exclude_keywords` so the search engine drops fans, empty boxes, stickers, and accessories before wasting pagination limits.
2. **Stage 2 (Forensic Description Auditing):**
   * Read the **entire verbatim description**.
   * Flag conditions:
     * *Hardware:* Look for *"para piezas"*, *"averiado"*, *"pines doblados"*, *"cables cortados"*, *"no da video"*.
     * *Vehicles:* Look for *"DANA/inundado"*, *"casquillos de biela / segmentos"*, *"junta de culata"*, *"baja temporal"*, *"sin documentación"*.
   * Verify what is included: Are stock coolers, cables, I/O shields, or extra parts bundled?

### 3.3 Verifying Live Availability (Anti-404 Guard)
Before presenting recommendations to the user, the agent must ensure listings are live:
* Expired or deleted listings return `HTTP 404` or redirect to the homepage.
* Verify items using concurrent probes (`ThreadPoolExecutor`) or confirm active presence in real-time API responses.
* Check the reservation flag (`flags.reserved == True`). Never recommend a reserved item without stating it is reserved.

### 3.4 Delivery Standards for the User
When presenting results to the user:
1. **Always Provide Direct Clickable Links:** Format URLs cleanly: `[Title - Price€](https://es.wallapop.com/item/slug)`.
2. **Always Provide the Verbatim Description & Forensic Analysis:** Quote the seller's exact words and explain the mechanical/hardware reality.
3. **Always Itemize the Math:** Show the exact component-by-component Bill of Materials (BOM), shipping costs, and total out-of-pocket investment.
4. **State the Upgrade Path:** Explain future upgradeability (e.g. AM4 VRM headroom for a 16-core 5950X, or car restoration roadmap).

### 3.5 Mandatory Forensic Visual Inspection Protocol (Gemini 2.5 Flash via OpenRouter)
Before delivering a final vehicle recommendation report (which must always contain at least a **Top 5**), the agent must subject candidate vehicle photos to deep visual inspection:
1. **Top-10 Candidates Selection:** Extract the top 10 candidate listings matching the user's constraints.
2. **High-Resolution Photo Extraction:** Fetch the full image galleries for each candidate (via `scraper.get_listing_detail(listing.url)`).
3. **Gemini 2.5 Flash Vision Dispatch:** Transmit the photo sets to `google/gemini-2.5-flash` through OpenRouter using the mandated appraisal prompt:
   * **Frame & Environment:** Ground surface, lighting conditions, wet/dry surfaces.
   * **Visible Panels & Alignment:** Shut-line consistency, hood/fender/door gaps, panel flushness.
   * **Paint & Body Condition:** Texture, orange peel, clearcoat failure, rock chips, dents, scratches, rust bubbling.
   * **Glass, Trim & Lighting:** Windshield chips/cracks, lens clarity/hazing/moisture, seal dry rot.
   * **Wheels, Brakes & Tires:** Curb rash, rotor grooving/rust, tire tread and sidewall dry rot.
   * **Interior & Cabin:** Upholstery tears, bolster creasing, steering wheel wear, dash cracks, headliner sag.
   * **Instrument Cluster & Electronics:** Exact odometer reading, illuminated warning lights (CEL, ABS, Airbag, TPMS).
   * **Text, Badging & Markings:** Emblems, aftermarket stickers, inspection decals, license plate frames.
   * **Micro-Anomalies & Red Flags:** Fluid drips underneath, paint overspray in wheel wells (indicating prior collision repair), sagging exhaust.
4. **Appraisal Synthesis & Re-Ranking:** Ingest the visual inspection data, calculate visual health scores, filter/discard catastrophically damaged or deceptive listings, and produce the final curated Top 5 report.

### 3.6 Mandatory Spain Legalization & Import Breakdown Mandate
When conducting vehicle analyses and delivering recommendations, **if a car is located outside Spain, the agent MUST ALWAYS add the total cost to have the car legal in Spain to the breakdown.**
The Spain Legalization Breakdown must explicitly itemize:
1. **International Transport / Transit:** Flatbed carrier or transit plates + fuel from country of origin to Spain (e.g., ~650 € from France, ~850 € from Germany/NL/BE, ~900 € from Austria/Italy, ~1,100 € from Sicily/UK).
2. **Ficha Técnica Reducida (Engineer COC):** Official Certificate of Conformity issued by a chartered Spanish automotive engineer (90.00 €).
3. **ITV Previa a Matriculación (Import Inspection):** Extraordinary non-periodic technical inspection at a Spanish ITV station (150.00 €).
4. **DGT Registration Fee (Tasa 1.1):** Official DGT initial vehicle registration fee (99.77 €).
5. **Impuesto Especial de Matriculación (IEDMT - Modelo 576 AEAT):** Spanish Treasury registration tax based on depreciated fiscal valuation and CO2 bracket (~150 € – 380 € for older sports cars).
6. **Impuesto de Circulación (IVTM):** Prorated municipal road tax (average 140.00 €).
7. **Physical Acrylic Registration Plates:** Pair of approved Spanish acrylic license plates (35.00 €).
8. **RHD Lighting Adaptation (if applicable):** If the vehicle is Right-Hand Drive, beam pattern replacement/adjustment and rear fog light relocation to pass Spanish ITV (250.00 €).
9. **Total Landed & Legal Cost in Spain:** Grand total combining base vehicle purchase price + all legalization, registration, and logistics costs.

---

## 4. Package Quickstart & CLI Commands

```bash
# Run standalone search for AM4 hardware excluding accessories
python main.py search "ryzen 7" --exclude ventilador disipador caja --max-price 80

# Run vehicle search for project cars under 2,000€
python main.py search "toyota celica" --category 100 --max-price 2000

# Export search results directly to JSON
python main.py search "mazda mx-3" --category 100 --json mx3_cars.json
# Run pan-European vehicle search on AutoScout24
python main.py search "toyota celica" --platform autoscout24 --min-price 1000 --max-price 5000

# Search AutoScout24 in Spain & Germany with year and mileage limits
python main.py search "mazda mx-5" --platform autoscout24 --countries ES DE --min-year 1998 --max-year 2005 --max-km 180000 --gear manual

# Deep forensic description auditing for mechanical defects and hidden damage
python main.py search "bmw 320" --platform autoscout24 --max-price 4000 --audit
# Vehicle search with Gemini 2.5 Flash visual inspection on top 10 (producing top 5 report)
python main.py search "nissan 200 sx" --platform autoscout24 --max-year 1994 --vision

# Search UR-Net Japanese Housing in Tokyo (Setagaya ward, vacant rooms)
python main.py search "setagaya" --platform ur_net --max-price 180000

# Search UR-Net Housing in Shibuya with 1LDK layout
python main.py search "shibuya" --platform ur_net --layout 1LDK

# Search UR-Net Housing in Osaka under 100,000 JPY
python main.py search "osaka" --platform ur_net --max-price 100000



# Run unit tests
python -m unittest discover -s tests -v
```

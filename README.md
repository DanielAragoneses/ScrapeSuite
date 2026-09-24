# ScrapeSuite

**ScrapeSuite** is an API-first marketplace scraper, automotive forensic appraisal framework, and public housing intelligence suite built in Python.

It bypasses WAF anti-bot defenses (Akamai, CloudFront, F5 BIG-IP) without heavyweight headless browsers, consuming minimal memory while delivering rapid response times.

---

## Key Features

1. **Marketplace & Housing Scrapers**
   * **AutoScout24 (Pan-European Vehicles):** Reverse-engineers Next.js SSR hydration payloads (`__NEXT_DATA__`) across Europe with multi-country selection, smart make/model query decomposition, and multilingual defect auditing.
   * **UR-Net (UR Housing / 都市再生機構 — Japan):** Directly interfaces with UR-Net's internal REST API (`chintai.r6.ur-net.go.jp`) with F5 BIG-IP session pre-warming, Tokyo 23-ward routing, vacancy tracking, and UR's signature **0 Key Money (礼金0)**, **0 Agency Fee (仲介手数料0)**, **0 Renewal Fee (更新料0)**, and **No Guarantor (保証人不要)** guarantees.
   * **Wallapop (Spain & Southern Europe):** Connects to native mobile REST endpoints with mobile identity badges (`x-deviceos: 0`) and Haversine distance geofencing.

2. **Automotive Forensic Appraisal Vision (Gemini 2.5 Flash via OpenRouter)**
   * Sequentially inspects high-resolution vehicle photo sets (up to 10 photos/listing) with Google Gemini 2.5 Flash.
   * Extracts visual condition across 9 clinical dimensions: *Frame & Environment*, *Visible Panels & Alignment*, *Paint & Body Condition*, *Glass & Lighting*, *Wheels & Tires*, *Interior*, *Instrument Cluster*, *Badging*, and *Micro-Anomalies (Fluid Leaks / Overspray)*.
   * Dynamically re-ranks listings based on visual health scores (0–10).
   * Automatically discovers authenticated OpenRouter credentials from local OMP agent sessions.

3. **Spain Legalization & Import Cost Framework**
   * Automatically calculates exact line-by-line administrative, fiscal, and logistical costs for importing European vehicles into Spain:
     * International flatbed transport / transit plates
     * Ficha Técnica Reducida (Chartered automotive engineer COC)
     * Extraordinary import ITV inspection (Inspección previa a matriculación)
     * Official DGT registration fee (Tasa 1.1)
     * AEAT Hacienda registration tax (IEDMT Modelo 576) based on depreciated fiscal base
     * Municipal road tax (IVTM)
     * Approved acrylic license plates
     * RHD continental lighting beam adaptation

4. **Forensic Description Auditing & Anti-Bait Guard**
   * Discards placeholder and bait prices (`1€`, `1234€`, `9999€`, `consultar precio`).
   * Detects hidden mechanical flaws, blown head gaskets, accident damage, rust rot, and missing documentation across 6 European languages (ES, DE, EN, FR, IT, NL).

---

## Installation & Setup

```bash
# Clone the repository
git clone https://github.com/DanielAragoneses/ScrapeSuite.git
cd ScrapeSuite

# Install dependencies
pip install -r requirements.txt
```

---

## Quickstart CLI Commands

### 1. Vehicle Searches (AutoScout24 Europe)

```bash
# Search for Japanese project cars across Europe
python main.py search "toyota celica" --platform autoscout24 --min-price 1000 --max-price 5000

# Search Nissan S13/S14 with visual inspection and Spain legalization breakdown
python main.py search "nissan 200 sx" --platform autoscout24 --max-year 1994 --vision

# Search Mazda MX-5 in Spain and Germany with mileage and gearbox filters
python main.py search "mazda mx-5" --platform autoscout24 --countries ES DE --max-km 180000 --gear manual
```

### 2. Japanese Housing Searches (UR-Net)

```bash
# Search vacant apartments in Tokyo (Setagaya Ward) under 180,000 JPY
python main.py search "setagaya" --platform ur_net --max-price 180000

# Search 1LDK apartments in Shibuya
python main.py search "shibuya" --platform ur_net --layout 1LDK

# Search Osaka housing under 100,000 JPY
python main.py search "osaka" --platform ur_net --max-price 100000

# List all complexes in Shinjuku including 0-vacancy waitlists
python main.py search "shinjuku" --platform ur_net --all-properties
```

---

## Running Tests

ScrapeSuite includes unit and integration tests covering scrapers, vision pipelines, models, and fiscal calculators:

```bash
python -m unittest discover -s tests -v
```

---

## License

MIT License

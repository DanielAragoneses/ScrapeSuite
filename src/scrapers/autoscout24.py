"""AutoScout24 European marketplace scraper for ScrapeSuite.

Extracts vehicle listings across Europe using AutoScout24's Next.js SSR hydration
payload (__NEXT_DATA__), bypassing anti-bot challenges without headless browsers.
Includes query decomposition, anti-bait filtering, multilingual forensic defect auditing,
and European geofencing math.
"""
import json
import logging
import math
import re
from typing import List, Optional, Dict, Any, Tuple
from urllib.parse import urlencode, quote

import requests

from src.models import Listing, SearchFilter, Platform
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

# Known placeholder / bait prices used on vehicle marketplaces
PLACEHOLDER_PRICES = {
    0.0, 1.0, 2.0, 10.0, 11.0, 12.0, 100.0, 111.0, 123.0, 500.0,
    999.0, 1111.0, 1234.0, 12345.0, 9999.0, 99999.0, 111111.0, 123456.0, 999999.0
}

# Multilingual bait phrases where the advertised price is not genuine
BAIT_PHRASES = [
    # Spanish
    "precio no es el del anuncio",
    "el precio no es el que marca",
    "no es el precio",
    "precio orientativo",
    "escucho ofertas",
    "precio por privado",
    "preguntar precio",
    "consultar precio",
    "precio simbólico",
    "precio simbolico",
    "no vale 1234",
    "no es 1234",
    # German
    "preis auf anfrage",
    "vb auf anfrage",
    "symbolischer preis",
    "symbolischer euro",
    "preis ist verhandlungssache",
    "bitte angebot machen",
    "kein 1 euro",
    "nicht für 1 euro",
    "kein 1€",
    # English
    "price on request",
    "make an offer",
    "poa",
    "not the actual price",
    "not 1 euro",
    "placeholder price",
    "send offers",
    # French
    "prix sur demande",
    "faire offre",
    "prix à débattre",
    "prix symbolique",
    "pas 1 euro",
    "pas 1€",
    # Italian
    "prezzo su richiesta",
    "valuto offerte",
    "prezzo simbolico",
    "non è 1 euro",
    "non è 1€",
    "trattativa riservata",
    # Dutch
    "prijs op aanvraag",
    "bieden",
    "symbolische prijs",
    "prijs n.o.t.k.",
    "geen 1 euro",
]

# Multilingual forensic defect patterns (mechanical, structural, legal, and severe damage)
FORENSIC_DEFECT_PATTERNS: Dict[str, List[str]] = {
    "ENGINE_DEFECT": [
        "motorschaden", "moteur hs", "motore fuso", "motore rotto", "motor roto",
        "motorschade", "engine damage", "blown engine", "engine seized", "motor defekt",
        "junta de culata", "zylinderkopfdichtung", "joint de culasse", "head gasket",
        "guarnizione testata", "koppakking", "biela", "casquillos", "segmentos",
        "hoher ölverbrauch", "ölverbrauch", "oelverbrauch", "consommation huile",
    ],
    "GEARBOX_DEFECT": [
        "getriebeschaden", "boite hs", "boîte hs", "cambio rotto", "caja rota",
        "caja de cambios rota", "gearbox damage", "transmission failure", "versnellingsbak defect",
        "embrayage hs", "embrague roto", "kupplung defekt",
    ],
    "ACCIDENT_DAMAGE": [
        "unfallwagen", "unfallfahrzeug", "unfall", "accidenté", "accidentee",
        "incidentata", "incidentato", "siniestro", "siniestrado", "golpe",
        "accident damaged", "salvage", "schadeauto", "schadevoertuig", "totalverlust",
        "carrosserie à revoir", "chapa tocada",
    ],
    "NON_RUNNER": [
        "nicht fahrbereit", "non roulant", "non marciante", "no arranca",
        "niet rijdend", "not running", "non runner", "para reparar", "da riparare",
        "à réparer", "en panne", "guasto", "averiado", "defekt",
    ],
    "PARTS_ONLY": [
        "für export", "fuer export", "nur export", "export only", "pour export",
        "solo export", "export", "bastlerfahrzeug", "bastler", "für bastler",
        "pour pièces", "pour pieces", "per ricambi", "para piezas", "o piezas",
        "piezas", "despiece", "voor onderdelen", "spares or repair", "parts only",
        "teilespender", "teileträger", "zum ausschlachten", "épave", "demolizione", "sloop",
    ],
    "WATER_FLOOD": [
        "inundado", "dana", "wasserschaden", "inondé", "alluvionato", "waterschade",
        "flood damage", "water damage",
    ],
    "DOCUMENTATION_ISSUE": [
        "sin documentación", "sin documentacion", "sin papeles", "sans carte grise",
        "senza documenti", "senza libretto", "geen kenteken", "no papers", "no logbook",
        "ohne fahrzeugbrief", "ohne papiere", "ohne tüv", "ohne tuv", "sans contrôle",
        "geen apk", "sin itv",
    ],
}

# AutoScout24 European Country Code Mapping
AUTOSCOUT_COUNTRY_MAP: Dict[str, str] = {
    "DE": "D", "GERMANY": "D", "D": "D",
    "FR": "F", "FRANCE": "F", "F": "F",
    "IT": "I", "ITALY": "I", "I": "I",
    "ES": "E", "SPAIN": "E", "E": "E",
    "BE": "B", "BELGIUM": "B", "B": "B",
    "NL": "NL", "NETHERLANDS": "NL",
    "AT": "A", "AUSTRIA": "A", "A": "A",
    "LU": "L", "LUXEMBOURG": "L", "L": "L",
}

# Reverse map from AutoScout single-letter code to ISO 3166-1 alpha-2
AUTOSCOUT_TO_ISO_COUNTRY: Dict[str, str] = {
    "D": "DE", "F": "FR", "I": "IT", "E": "ES",
    "B": "BE", "NL": "NL", "A": "AT", "L": "LU",
}

# Approximate geographic centroid coordinates for European countries (for distance estimations)
EUROPE_COUNTRY_CENTROIDS: Dict[str, Tuple[float, float]] = {
    "ES": (40.4168, -3.7038),   # Madrid
    "DE": (51.1657, 10.4515),   # Germany center
    "FR": (46.2276, 2.2137),    # France center
    "IT": (41.8719, 12.5674),   # Italy center
    "BE": (50.5039, 4.4699),    # Belgium center
    "NL": (52.1326, 5.2913),    # Netherlands center
    "AT": (47.5162, 14.5501),   # Austria center
    "LU": (49.8153, 6.1296),    # Luxembourg center
    "CH": (46.8182, 8.2275),    # Switzerland center
}

# Major European cities coordinates for refined proximity calculation
EUROPE_CITY_COORDINATES: Dict[str, Tuple[float, float]] = {
    # Spain
    "madrid": (40.4168, -3.7038), "barcelona": (41.3851, 2.1734), "valencia": (39.4699, -0.3763),
    "sevilla": (37.3891, -5.9845), "zaragoza": (41.6488, -0.8891), "malaga": (36.7213, -4.4214),
    "bilbao": (43.2630, -2.9350), "loeches": (40.3850, -3.3140), "alcala de henares": (40.4819, -3.3635),
    # Germany
    "berlin": (52.5200, 13.4050), "munich": (48.1351, 11.5820), "münchen": (48.1351, 11.5820),
    "frankfurt": (50.1109, 8.6821), "hamburg": (53.5511, 9.9937), "cologne": (50.9375, 6.9603),
    "köln": (50.9375, 6.9603), "stuttgart": (48.7758, 9.1829), "düsseldorf": (51.2277, 6.7735),
    "dortmund": (51.5136, 7.4653), "leipzig": (51.3397, 12.3731), "nürnberg": (49.4521, 11.0767),
    # France
    "paris": (48.8566, 2.3522), "lyon": (45.7640, 4.8357), "marseille": (43.2965, 5.3698),
    "toulouse": (43.6047, 1.4442), "nice": (43.7102, 7.2620), "nantes": (47.2184, -1.5536),
    "strasbourg": (48.5734, 7.7521), "bordeaux": (44.8378, -0.5792), "lille": (50.6292, 3.0573),
    # Italy
    "rome": (41.9028, 12.4964), "roma": (41.9028, 12.4964), "milan": (45.4642, 9.1900),
    "milano": (45.4642, 9.1900), "naples": (40.8518, 14.2681), "napoli": (40.8518, 14.2681),
    "turin": (45.0703, 7.6869), "torino": (45.0703, 7.6869), "florence": (43.7696, 11.2558),
    "firenze": (43.7696, 11.2558), "bologna": (44.4949, 11.3426), "venice": (45.4408, 12.3155),
    # Netherlands & Belgium
    "amsterdam": (52.3676, 4.9041), "rotterdam": (51.9244, 4.4777), "the hague": (52.0705, 4.3007),
    "utrecht": (52.0907, 5.1214), "brussels": (50.8503, 4.3517), "antwerp": (51.2194, 4.4025),
    "ghent": (51.0543, 3.7174), "liège": (50.6326, 5.5797),
    # Austria
    "vienna": (48.2082, 16.3738), "wien": (48.2082, 16.3738), "salzburg": (47.8095, 13.0550),
    "innsbruck": (47.2692, 11.4041), "graz": (47.0707, 15.4395),
}

# Common vehicle make aliases and canonical slugs in AutoScout24
MAKE_ALIASES: Dict[str, str] = {
    "vw": "volkswagen",
    "volks": "volkswagen",
    "mercedes": "mercedes-benz",
    "mercedesbenz": "mercedes-benz",
    "mercedes benz": "mercedes-benz",
    "mercedes-benz": "mercedes-benz",
    "benz": "mercedes-benz",
    "alfa": "alfa-romeo",
    "alfa romeo": "alfa-romeo",
    "alfa-romeo": "alfa-romeo",
    "chevy": "chevrolet",
    "landrover": "land-rover",
    "land rover": "land-rover",
    "land-rover": "land-rover",
    "aston": "aston-martin",
    "astonmartin": "aston-martin",
    "aston martin": "aston-martin",
    "aston-martin": "aston-martin",
    "rolls": "rolls-royce",
    "rollsroyce": "rolls-royce",
    "rolls royce": "rolls-royce",
    "rolls-royce": "rolls-royce",
}

# Standalone iconic models mapped to their respective makes
ICONIC_MODEL_TO_MAKE: Dict[str, Tuple[str, str]] = {
    "celica": ("toyota", "celica"),
    "supra": ("toyota", "supra"),
    "mr2": ("toyota", "mr-2"),
    "yaris": ("toyota", "yaris"),
    "corolla": ("toyota", "corolla"),
    "rav4": ("toyota", "rav-4"),
    "mx-5": ("mazda", "mx-5"),
    "mx5": ("mazda", "mx-5"),
    "miata": ("mazda", "mx-5"),
    "rx-7": ("mazda", "rx-7"),
    "rx7": ("mazda", "rx-7"),
    "rx-8": ("mazda", "rx-8"),
    "rx8": ("mazda", "rx-8"),
    "golf": ("volkswagen", "golf"),
    "passat": ("volkswagen", "passat"),
    "polo": ("volkswagen", "polo"),
    "scirocco": ("volkswagen", "scirocco"),
    "beetle": ("volkswagen", "beetle"),
    "civic": ("honda", "civic"),
    "s2000": ("honda", "s2000"),
    "nsx": ("honda", "nsx"),
    "accord": ("honda", "accord"),
    "crx": ("honda", "crx"),
    "cr-x": ("honda", "crx"),
    "impreza": ("subaru", "impreza"),
    "wrx": ("subaru", "impreza"),
    "forester": ("subaru", "forester"),
    "mustang": ("ford", "mustang"),
    "focus": ("ford", "focus"),
    "fiesta": ("ford", "fiesta"),
    "escort": ("ford", "escort"),
    "mondeo": ("ford", "mondeo"),
    "clio": ("renault", "clio"),
    "megane": ("renault", "megane"),
    "twingo": ("renault", "twingo"),
    "scenic": ("renault", "scenic"),
    "leon": ("seat", "leon"),
    "ibiza": ("seat", "ibiza"),
    "cupra": ("seat", "cupra"),
    "350z": ("nissan", "350z"),
    "370z": ("nissan", "370z"),
    "skyline": ("nissan", "skyline"),
    "gt-r": ("nissan", "gt-r"),
    "gtr": ("nissan", "gt-r"),
    "silvia": ("nissan", "silvia"),
    "200sx": ("nissan", "200-sx"),
    "200-sx": ("nissan", "200-sx"),
    "180sx": ("nissan", "200-sx"),
    "240sx": ("nissan", "200-sx"),
    "s13": ("nissan", "200-sx"),
    "s14": ("nissan", "200-sx"),
    "s15": ("nissan", "silvia"),
    "911": ("porsche", "911"),
    "boxster": ("porsche", "boxster"),
    "cayman": ("porsche", "cayman"),
    "cayenne": ("porsche", "cayenne"),
    "panamera": ("porsche", "panamera"),
    "prelude": ("honda", "prelude"),
    "eclipse": ("mitsubishi", "eclipse"),
    "100nx": ("nissan", "100-nx"),
    "100-nx": ("nissan", "100-nx"),
    "3000gt": ("mitsubishi", "3000-gt"),
    "3000-gt": ("mitsubishi", "3000-gt"),
    "300zx": ("nissan", "300-zx"),
    "300-zx": ("nissan", "300-zx"),
    "350-z": ("nissan", "350z"),
    "370-z": ("nissan", "370z"),
    "copen": ("daihatsu", "copen"),
    "svx": ("subaru", "svx"),
    "cappuccino": ("suzuki", "cappuccino"),
}

# Fuel type mapping to AutoScout24 query codes
FUEL_MAP: Dict[str, str] = {
    "gasoline": "B", "petrol": "B", "gasolina": "B", "benzin": "B", "essence": "B", "benzina": "B", "b": "B",
    "diesel": "D", "gasoleo": "D", "gaspóleo": "D", "diésel": "D", "d": "D",
    "electric": "E", "electrico": "E", "eléctrico": "E", "elektro": "E", "electrique": "E", "eettrico": "E", "ev": "E", "e": "E",
    "hybrid": "2", "hibrido": "2", "híbrido": "2", "hybrid-petrol": "2",
    "lpg": "L", "glp": "L", "autogas": "L", "l": "L",
    "cng": "C", "gnc": "C", "erdgas": "C", "c": "C",
}

# Gearbox mapping to AutoScout24 query codes
GEARBOX_MAP: Dict[str, str] = {
    "manual": "M", "m": "M", "man": "M",
    "automatic": "A", "auto": "A", "a": "A", "aut": "A",
}


class AutoScout24Scraper(BaseScraper):
    """Production-grade scraper for AutoScout24 across Europe.

    Extracts vehicle listings directly from the Next.js SSR state (__NEXT_DATA__)
    embedded in AutoScout24 pages. Implements forensic defect analysis, placeholder
    price rejection, European proximity math, and negative keyword filtering.
    """
    platform: Platform = Platform.AUTOSCOUT24
    DEFAULT_BASE_URL: str = "https://www.autoscout24.com"

    # Browser identity headers designed to avoid anti-bot challenges
    HEADERS: Dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9,es-ES;q=0.8,de-DE;q=0.7",
        "Sec-Ch-Ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }

    def __init__(
        self,
        session: Optional[requests.Session] = None,
        base_url: str = DEFAULT_BASE_URL,
        delay: float = 0.3
    ):
        super().__init__(session=session, delay=delay)
        self.base_url = base_url.rstrip("/")
        self.session.headers.update(self.HEADERS)

    @classmethod
    def parse_query_slug(cls, query: str) -> Tuple[Optional[str], Optional[str], List[str]]:
        """Parse free-form search query into (make_slug, model_slug, remaining_keywords).

        Examples:
          "toyota celica"       -> ("toyota", "celica", [])
          "mazda mx-5 nb"       -> ("mazda", "mx-5", ["nb"])
          "vw golf gti"         -> ("volkswagen", "golf", ["gti"])
          "alfa romeo 147"      -> ("alfa-romeo", "147", [])
          "mercedes c 220"      -> ("mercedes-benz", "c-220", [])
          "miata"               -> ("mazda", "mx-5", [])
          "bmw 320d"            -> ("bmw", "320", ["d"])
          "camper"              -> (None, None, ["camper"])
        """
        raw = query.strip().lower()
        if not raw:
            return None, None, []

        tokens = re.split(r"[\s_]+", raw)
        if not tokens:
            return None, None, []

        # 0. Check for special multi-token patterns (e.g. "s13 nissan", "nissan s13", "nissan 200 sx", "200 sx")
        token_set = set(tokens)
        if "nissan" in token_set:
            for s_code, target_model in [("s13", "200-sx"), ("s14", "200-sx"), ("s15", "silvia"), ("180sx", "200-sx"), ("240sx", "200-sx"), ("200sx", "200-sx")]:
                if s_code in token_set:
                    rem = [t for t in tokens if t not in ("nissan", s_code)]
                    return "nissan", target_model, rem

        if len(tokens) >= 2 and tokens[0] in ("200", "180", "240") and tokens[1] == "sx":
            rem = tokens[2:]
            return "nissan", "200-sx", rem

        if len(tokens) >= 3 and tokens[0] == "nissan" and tokens[1] in ("200", "180", "240") and tokens[2] == "sx":
            rem = tokens[3:]
            return "nissan", "200-sx", rem
        if len(tokens) >= 3 and tokens[0] == "nissan" and tokens[1] == "100" and tokens[2] == "nx":
            return "nissan", "100-nx", tokens[3:]

        if len(tokens) >= 3 and tokens[0] == "nissan" and tokens[1] == "350" and tokens[2] == "z":
            return "nissan", "350z", tokens[3:]

        if len(tokens) >= 3 and tokens[0] == "nissan" and tokens[1] == "300" and tokens[2] == "zx":
            return "nissan", "300-zx", tokens[3:]

        if len(tokens) >= 3 and tokens[0] == "mitsubishi" and tokens[1] == "3000" and tokens[2] == "gt":
            return "mitsubishi", "3000-gt", tokens[3:]

        if len(tokens) >= 3 and tokens[0] == "toyota" and tokens[1] == "mr" and tokens[2] == "2":
            return "toyota", "mr-2", tokens[3:]


        # 1. Check for single-token iconic model (e.g. "celica", "miata", "mustang", "s13")
        if len(tokens) == 1 and tokens[0] in ICONIC_MODEL_TO_MAKE:
            make, model = ICONIC_MODEL_TO_MAKE[tokens[0]]
            return make, model, []
        # 2. Check for multi-word makes (e.g. "alfa romeo", "mercedes benz", "land rover")
        if len(tokens) >= 2:
            two_word_prefix = f"{tokens[0]} {tokens[1]}"
            if two_word_prefix in MAKE_ALIASES:
                make = MAKE_ALIASES[two_word_prefix]
                model = tokens[2] if len(tokens) > 2 else None
                rem = tokens[3:] if len(tokens) > 3 else []
                # Clean model slug
                if model:
                    model = cls._normalize_model_slug(model)
                return make, model, rem

        # 3. Check first token as make or alias
        first = tokens[0]
        make_candidate = MAKE_ALIASES.get(first, first)

        # Check if first token is iconic model with extra tokens (e.g. "celica t23")
        if first in ICONIC_MODEL_TO_MAKE:
            make, model = ICONIC_MODEL_TO_MAKE[first]
            return make, model, tokens[1:]

        # Special handling for brands like "bmw", "mercedes", "audi" followed by model
        if len(tokens) >= 2:
            second = tokens[1]
            # Handle cases like "mercedes c 220" -> model is "c-220"
            if make_candidate in ("mercedes-benz", "bmw", "audi") and len(tokens) >= 3 and len(second) == 1:
                model = f"{second}-{tokens[2]}"
                rem = tokens[3:]
                return make_candidate, model, rem

            # Standard make + model
            model = cls._normalize_model_slug(second)
            rem = tokens[2:]
            return make_candidate, model, rem

        # Single word make (e.g. "toyota")
        return make_candidate, None, []

    @staticmethod
    def _normalize_model_slug(model: str) -> str:
        """Normalize vehicle model name into AutoScout24 URL format."""
        m = model.strip().lower()
        if m in ("mx5", "mx-5", "miata"):
            return "mx-5"
        if m in ("rx7", "rx-7"):
            return "rx-7"
        if m in ("rx8", "rx-8"):
            return "rx-8"
        if m in ("gt-r", "gtr"):
            return "gt-r"
        if m in ("mr2", "mr-2"):
            return "mr-2"
        if m in ("rav4", "rav-4"):
            return "rav-4"
        # Standardize alphanumeric hyphens
        m = re.sub(r"[^\w\-]", "", m)
        return m

    @classmethod
    def audit_defect_flags(cls, text: str) -> List[str]:
        """Perform multilingual forensic defect analysis on listing text.

        Scans for mechanical faults, accident damage, non-running conditions,
        missing documentation, flood/DANA damage, and stripped/parts-only units.
        Returns a list of detected defect tags (e.g., ['ENGINE_DEFECT:motorschaden']).
        """
        if not text:
            return []

        lower_text = text.lower()
        flags: List[str] = []

        for category, patterns in FORENSIC_DEFECT_PATTERNS.items():
            for p in patterns:
                # Word boundary match to avoid partial substrings
                escaped = re.escape(p)
                if re.search(r"(?:^|[\s,.;:!?\(\)\/\-])" + escaped + r"(?:$|[\s,.;:!?\(\)\/\-])", lower_text):
                    flags.append(f"{category}:{p}")

        return sorted(list(set(flags)))

    @classmethod
    def is_placeholder_price(cls, price: float) -> bool:
        """Determine if a numeric price is a known placeholder/bait value."""
        return price in PLACEHOLDER_PRICES or price <= 2.0

    @classmethod
    def has_bait_phrases(cls, text: str) -> bool:
        """Check if description contains known phrases signifying fake/placeholder pricing."""
        if not text:
            return False
        lower = text.lower()
        return any(phrase in lower for phrase in BAIT_PHRASES)

    def extract_next_data(self, html: str) -> Optional[Dict[str, Any]]:
        """Extract and parse the JSON payload from the <script id="__NEXT_DATA__"> tag."""
        match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(1))
        except Exception as e:
            logger.warning(f"Failed to decode __NEXT_DATA__ JSON: {e}")
            return None

    def build_search_url_and_params(
        self,
        query: str,
        search_filter: Optional[SearchFilter] = None,
        page: int = 1
    ) -> Tuple[str, Dict[str, Any], List[str]]:
        """Construct the target URL path and query parameters for AutoScout24 search."""
        sf = search_filter or SearchFilter()
        make_slug, model_slug, rem_keywords = self.parse_query_slug(query)

        # Assemble URL path
        if make_slug and model_slug:
            path = f"/lst/{quote(make_slug)}/{quote(model_slug)}"
        elif make_slug:
            path = f"/lst/{quote(make_slug)}"
        else:
            path = "/lst"

        url = f"{self.base_url}{path}"
        params: Dict[str, Any] = {
            "atype": "C",  # Passenger car
        }

        # Sorting
        order = sf.order_by or "price_low_to_high"
        if order in ("price_low_to_high", "price_asc"):
            params["sort"] = "price"
            params["desc"] = "0"
        elif order in ("price_high_to_low", "price_desc"):
            params["sort"] = "price"
            params["desc"] = "1"
        elif order in ("newest", "age_desc"):
            params["sort"] = "age"
            params["desc"] = "1"
        elif order in ("mileage_asc",):
            params["sort"] = "mileage"
            params["desc"] = "0"
        else:
            params["sort"] = "standard"
            params["desc"] = "0"

        # Price range
        if sf.min_price is not None:
            params["pricefrom"] = str(int(sf.min_price))
        if sf.max_price is not None:
            params["priceto"] = str(int(sf.max_price))

        # Year range
        if sf.min_year is not None:
            params["fregfrom"] = str(int(sf.min_year))
        if sf.max_year is not None:
            params["fregto"] = str(int(sf.max_year))

        # Mileage limit
        if sf.max_mileage_km is not None:
            params["kmto"] = str(int(sf.max_mileage_km))

        # Fuel type
        if sf.fuel_type:
            fuel_code = FUEL_MAP.get(sf.fuel_type.strip().lower())
            if fuel_code:
                params["fuel"] = fuel_code

        # Gearbox
        if sf.gearbox:
            gear_code = GEARBOX_MAP.get(sf.gearbox.strip().lower())
            if gear_code:
                params["gear"] = gear_code

        # Countries
        target_countries = sf.countries
        if target_countries:
            codes = []
            for c in target_countries:
                c_clean = c.strip().upper()
                mapped = AUTOSCOUT_COUNTRY_MAP.get(c_clean)
                if mapped and mapped not in codes:
                    codes.append(mapped)
            if codes:
                params["cy"] = ",".join(codes)

        # Pagination
        if page > 1:
            params["page"] = str(page)

        return url, params, rem_keywords

    def estimate_distance(
        self,
        listing_loc: Dict[str, Any],
        origin_lat: Optional[float],
        origin_lon: Optional[float]
    ) -> Optional[float]:
        """Calculate great-circle distance using exact coords or European city/centroid table."""
        if origin_lat is None or origin_lon is None:
            return None

        # 1. Exact coordinates if present in listing payload
        lat = listing_loc.get("latitude")
        lon = listing_loc.get("longitude")
        if lat is not None and lon is not None:
            try:
                return self.haversine_distance(origin_lat, origin_lon, float(lat), float(lon))
            except (ValueError, TypeError):
                pass

        # 2. City lookup table
        city = str(listing_loc.get("city", "")).strip().lower()
        if city in EUROPE_CITY_COORDINATES:
            c_lat, c_lon = EUROPE_CITY_COORDINATES[city]
            return self.haversine_distance(origin_lat, origin_lon, c_lat, c_lon)

        # 3. Country centroid fallback
        country_code = str(listing_loc.get("countryCode", "")).strip().upper()
        # Handle single letter AutoScout codes
        iso_code = AUTOSCOUT_TO_ISO_COUNTRY.get(country_code, country_code)
        if iso_code in EUROPE_COUNTRY_CENTROIDS:
            cnt_lat, cnt_lon = EUROPE_COUNTRY_CENTROIDS[iso_code]
            return self.haversine_distance(origin_lat, origin_lon, cnt_lat, cnt_lon)

        return None

    def search(
        self,
        query: str,
        search_filter: Optional[SearchFilter] = None,
        max_pages: int = 1
    ) -> List[Listing]:
        """Perform search across AutoScout24 Europe and return normalized Listing objects."""
        sf = search_filter or SearchFilter()
        listings: List[Listing] = []
        page = 1

        while page <= max_pages:
            url, params, rem_keywords = self.build_search_url_and_params(query, sf, page=page)
            resp = self.safe_get(url, params=params, headers=self.HEADERS)
            if not resp or resp.status_code != 200:
                logger.warning(f"AutoScout24 search request failed for URL {url} with params {params}")
                break

            data = self.extract_next_data(resp.text)
            if not data:
                logger.warning("Could not extract __NEXT_DATA__ payload from AutoScout24 response")
                break

            page_props = data.get("props", {}).get("pageProps", {})
            raw_listings = page_props.get("listings", [])
            if not raw_listings:
                break

            for it in raw_listings:
                listing = self._parse_listing_item(it, sf, rem_keywords)
                if listing is not None:
                    listings.append(listing)

            # Check if further pages exist
            total_pages = page_props.get("numberOfPages", 1)
            if page >= total_pages or page >= max_pages:
                break
            page += 1

        # Perform forensic audit on descriptions if requested
        if sf.audit_descriptions:
            for item in listings:
                self.audit_listing_detail(item)

        return listings

    def _parse_listing_item(
        self,
        item: Dict[str, Any],
        sf: SearchFilter,
        rem_keywords: List[str]
    ) -> Optional[Listing]:
        """Parse raw AutoScout24 listing dictionary into normalized Listing object."""
        listing_id = str(item.get("id", ""))
        if not listing_id:
            return None

        # Price parsing
        price_obj = item.get("price", {})
        price_raw = price_obj.get("priceRaw")
        if price_raw is None:
            # Fallback parse from formatted string
            p_formatted = price_obj.get("priceFormatted", "")
            digits = re.sub(r"[^\d.]", "", p_formatted.replace(".", "").replace(",", "."))
            try:
                price_raw = float(digits)
            except ValueError:
                price_raw = 0.0
        price = float(price_raw)

        # Vehicle attributes
        v = item.get("vehicle", {})
        make = v.get("make") or ""
        model = v.get("model") or ""
        version = v.get("modelVersionInput") or ""
        title = f"{make} {model} {version}".strip()
        if not title:
            title = f"{make} {model}".strip() or f"AutoScout24 Listing {listing_id}"

        # URL
        rel_url = item.get("url", "")
        full_url = f"{self.DEFAULT_BASE_URL}{rel_url}" if rel_url.startswith("/") else rel_url

        # Location
        loc = item.get("location", {})
        country_code = loc.get("countryCode") or ""
        city = loc.get("city") or ""
        zip_code = loc.get("zip") or ""
        street = loc.get("street") or ""
        location_parts = [p for p in [city, country_code, zip_code] if p]
        seller_location = ", ".join(location_parts) if location_parts else None

        # Distance calculation
        dist_km = self.estimate_distance(loc, sf.latitude, sf.longitude)

        # Distance filter
        if sf.max_distance_km is not None and dist_km is not None:
            if dist_km > sf.max_distance_km:
                return None

        # Details list (mileage, gearbox, year, fuel, power)
        vehicle_details = item.get("vehicleDetails", [])
        detail_map: Dict[str, str] = {}
        for d in vehicle_details:
            icon = d.get("iconName", "")
            val = d.get("data", "")
            if icon and val:
                detail_map[icon] = val

        # Parse mileage
        mileage_str = detail_map.get("mileage_odometer", v.get("mileageInKm", ""))
        mileage_km: Optional[int] = None
        if mileage_str:
            clean_km = re.sub(r"[^\d]", "", str(mileage_str))
            if clean_km.isdigit():
                mileage_km = int(clean_km)

        # Parse registration year
        reg_str = detail_map.get("calendar", "")
        year: Optional[int] = None
        if reg_str:
            year_match = re.search(r"(\d{4})", reg_str)
            if year_match:
                year = int(year_match.group(1))

        # Parse transmission and fuel
        transmission = detail_map.get("gearbox", v.get("transmission", ""))
        fuel = detail_map.get("gas_pump", v.get("fuel", ""))
        power_str = detail_map.get("speedometer", "")

        power_kw: Optional[int] = None
        power_hp: Optional[int] = None
        if power_str:
            kw_match = re.search(r"(\d+)\s*kW", power_str, re.IGNORECASE)
            hp_match = re.search(r"(\d+)\s*(?:hp|ch|cv|pk|ps)", power_str, re.IGNORECASE)
            if kw_match:
                power_kw = int(kw_match.group(1))
            if hp_match:
                power_hp = int(hp_match.group(1))

        # Anti-Bait Guard: Placeholder price detection
        is_placeholder = self.is_placeholder_price(price)

        # Audit forensic defect flags in title & version
        defect_flags = self.audit_defect_flags(title)

        # Remaining keywords client filtering
        if rem_keywords:
            text_corpus = f"{title} {fuel} {transmission}".lower()
            if not all(kw in text_corpus for kw in rem_keywords):
                return None

        # Server-side / Client negative keywords filtering (-word / sf.exclude_keywords)
        if sf.exclude_keywords:
            text_corpus = f"{title} {fuel} {transmission} {seller_location or ''}".lower()
            for exc in sf.exclude_keywords:
                clean_exc = exc.strip().lstrip("-").lower()
                if clean_exc and clean_exc in text_corpus:
                    return None

        # Specifications dictionary
        seller_info = item.get("seller", {})
        seller_type = seller_info.get("type", "Unknown")

        specs: Dict[str, Any] = {
            "make": make,
            "model": model,
            "version": version,
            "year": year,
            "first_registration": reg_str or None,
            "mileage_km": mileage_km,
            "power_kw": power_kw,
            "power_hp": power_hp,
            "fuel": fuel,
            "transmission": transmission,
            "seller_type": seller_type,
            "country_code": country_code,
            "city": city,
            "zip": zip_code,
            "street": street,
            "is_placeholder_price": is_placeholder,
            "forensic_flags": defect_flags,
            "images": item.get("images", []),
            "super_deal": bool(item.get("superDeal", {}).get("isEligible", False)),
        }

        return Listing(
            id=listing_id,
            title=title,
            price=price,
            shipping_cost=0.0,
            total_price=price,
            currency="EUR",
            url=full_url,
            platform=self.platform,
            seller_location=seller_location,
            distance_km=dist_km,
            shipping_available=False,
            is_reserved=False,
            description="",
            specs=specs,
            raw_data=item,
        )

    def get_listing_detail(self, listing_or_url: Any) -> Optional[Dict[str, Any]]:
        """Fetch full details and description for an AutoScout24 vehicle listing."""
        if isinstance(listing_or_url, Listing):
            url = listing_or_url.url
        elif isinstance(listing_or_url, str):
            url = listing_or_url
            if not url.startswith("http"):
                url = f"{self.DEFAULT_BASE_URL}{url}"
        else:
            return None

        resp = self.safe_get(url, headers=self.HEADERS)
        if not resp or resp.status_code != 200:
            return None

        data = self.extract_next_data(resp.text)
        if not data:
            return None

        ld = data.get("props", {}).get("pageProps", {}).get("listingDetails", {})
        return ld

    def audit_listing_detail(self, listing: Listing) -> Listing:
        """Deeply inspect listing detail page to extract verbatim description, exact GPS coordinates,

        and perform forensic defect auditing.
        """
        detail = self.get_listing_detail(listing.url)
        if not detail:
            return listing

        # Extract full description
        raw_desc = detail.get("description") or ""
        # Clean HTML breaks if present
        clean_desc = re.sub(r"<br\s*/?>", "\n", raw_desc)
        clean_desc = re.sub(r"<[^>]+>", " ", clean_desc).strip()
        listing.description = clean_desc

        # Extract exact GPS coordinates
        # Extract full gallery images
        detail_images = detail.get("images", [])
        if detail_images:
            listing.specs["images"] = detail_images

        loc = detail.get("location", {})
        lat = loc.get("latitude")
        lon = loc.get("longitude")
        if lat is not None and lon is not None:
            listing.specs["latitude"] = float(lat)
            listing.specs["longitude"] = float(lon)
            if listing.specs.get("origin_latitude") is not None:
                listing.distance_km = self.haversine_distance(
                    listing.specs["origin_latitude"],
                    listing.specs["origin_longitude"],
                    float(lat),
                    float(lon)
                )

        # Forensic defect auditing on full description
        full_text = f"{listing.title}\n{clean_desc}"
        new_flags = self.audit_defect_flags(full_text)
        listing.specs["forensic_flags"] = sorted(list(set(listing.specs.get("forensic_flags", []) + new_flags)))

        # Anti-bait check on description
        if self.has_bait_phrases(clean_desc):
            listing.specs["is_placeholder_price"] = True
            listing.specs["forensic_flags"].append("BAIT:phrase_in_description")

        return listing

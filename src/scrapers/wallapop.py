"""Wallapop API scraper implementation for ScrapeSuite."""
import logging
import math
import re
from typing import List, Optional, Dict, Any

import requests
from src.models import Listing, SearchFilter, Platform
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

# Known placeholder / bait prices used on Wallapop
PLACEHOLDER_PRICES = {
    1.0, 10.0, 11.0, 12.0, 123.0, 1234.0, 12345.0, 9999.0,
    1111.0, 2222.0, 3333.0, 4444.0, 5555.0, 6666.0, 7777.0, 8888.0, 999.0
}

# Known bait phrases sellers put in descriptions when the price is fake
BAIT_PHRASES = [
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
]


class WallapopScraper(BaseScraper):
    """Production-grade scraper for Wallapop using the native mobile REST API.
    
    Features:
      - Bypasses CloudFront/Akamai web anti-bot using native mobile API headers.
      - Supports native Lucene negative keyword exclusion (query -bad1 -bad2).
      - Category-aware (e.g. category_id='100' for vehicles, electronics, etc.).
      - Precise Haversine distance calculations from a reference coordinate.
      - Shipping eligibility and reservation status detection.
      - Forensic anti-baiting detection (identifies fake 1234€ prices and bait text).
      - Returns normalized Listing dataclass objects.
    """
    platform: Platform = Platform.WALLAPOP
    ENDPOINT: str = "https://api.wallapop.com/api/v3/search/section"

    # Required mobile REST API identity headers
    WALLAPOP_HEADERS: Dict[str, str] = {
        "Host": "api.wallapop.com",
        "Referer": "https://es.wallapop.com/",
        "x-deviceos": "0",  # Android/iOS client token
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
        "Accept-Language": "es,es-ES;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    def __init__(self, session: Optional[requests.Session] = None, delay: float = 0.3):
        super().__init__(session=session, delay=delay)
        self.session.headers.update(self.WALLAPOP_HEADERS)

    @staticmethod
    def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate great-circle distance between two geographic coordinates in kilometers."""
        r = 6371.0  # Earth's radius in kilometers
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (
            math.sin(dlat / 2.0) ** 2
            + math.cos(math.radians(lat1))
            * math.cos(math.radians(lat2))
            * math.sin(dlon / 2.0) ** 2
        )
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        return round(r * c, 2)

    def search(self, query: str, search_filter: Optional[SearchFilter] = None) -> List[Listing]:
        """Perform search on Wallapop and return normalized Listing objects."""
        sf = search_filter or SearchFilter()
        
        # Build search keywords: append any negative keyword exclusions (-word)
        keywords_parts = [query.strip()]
        if sf.exclude_keywords:
            for neg in sf.exclude_keywords:
                neg_clean = neg.strip().lstrip("-")
                if neg_clean:
                    keywords_parts.append(f"-{neg_clean}")
        final_keywords = " ".join(keywords_parts)

        params: Dict[str, Any] = {
            "source": "search_box",
            "keywords": final_keywords,
            "section_type": "organic_search_results",
            "order_by": sf.order_by or "price_low_to_high",
        }

        if sf.category_id:
            params["category_id"] = str(sf.category_id)

        if sf.min_price is not None and sf.min_price > 0:
            params["min_sale_price"] = str(int(sf.min_price))

        if sf.max_price is not None and sf.max_price > 0:
            params["max_sale_price"] = str(int(sf.max_price))

        if sf.latitude is not None and sf.longitude is not None:
            params["latitude"] = str(sf.latitude)
            params["longitude"] = str(sf.longitude)

        resp = self.safe_get(self.ENDPOINT, params=params, headers=self.WALLAPOP_HEADERS)
        if not resp or resp.status_code != 200:
            logger.warning(f"[{self.platform.value}] Wallapop API failed: status {resp.status_code if resp else 'None'}")
            return []

        try:
            payload = resp.json()
        except Exception as e:
            logger.warning(f"[{self.platform.value}] Failed to parse JSON response: {e}")
            return []

        data_obj = payload.get("data", {}) if isinstance(payload, dict) else {}
        section_obj = data_obj.get("section", {}) if isinstance(data_obj, dict) else {}
        items = section_obj.get("items", []) if isinstance(section_obj, dict) else []

        if not isinstance(items, list):
            return []

        ref_lat = sf.latitude if sf.latitude is not None else 40.385
        ref_lon = sf.longitude if sf.longitude is not None else -3.314

        listings: List[Listing] = []

        for it in items:
            if not isinstance(it, dict):
                continue

            item_id = str(it.get("id", ""))
            title = str(it.get("title") or "").strip()
            description = str(it.get("description") or "").strip()
            web_slug = str(it.get("web_slug") or item_id)

            # Price extraction
            price_data = it.get("price")
            price = 0.0
            currency = "EUR"
            if isinstance(price_data, dict):
                try:
                    price = float(price_data.get("amount", 0.0))
                except (TypeError, ValueError):
                    price = 0.0
                currency = str(price_data.get("currency") or "EUR")
            elif isinstance(price_data, (int, float)):
                price = float(price_data)

            # Filter max_price if specified
            if sf.max_price is not None and price > sf.max_price:
                continue
            if sf.min_price is not None and price < sf.min_price:
                continue

            # Reservation status
            flags = it.get("flags", {})
            is_reserved = False
            if isinstance(flags, dict):
                is_reserved = bool(flags.get("reserved", False))

            # Location and distance
            loc = it.get("location")
            seller_location = None
            distance_km = None
            if isinstance(loc, dict):
                city = loc.get("city")
                region = loc.get("region")
                parts = [p for p in [city, region] if p]
                seller_location = ", ".join(parts) if parts else None

                if "latitude" in loc and "longitude" in loc:
                    try:
                        item_lat = float(loc["latitude"])
                        item_lon = float(loc["longitude"])
                        distance_km = self.haversine_distance(ref_lat, ref_lon, item_lat, item_lon)
                    except (TypeError, ValueError):
                        distance_km = None

            # Shipping availability
            shipping_available = True
            shipping_info = it.get("shipping")
            if isinstance(shipping_info, dict):
                if "user_allows_shipping" in shipping_info:
                    shipping_available = bool(shipping_info["user_allows_shipping"])
                elif "shipping_allowed" in shipping_info:
                    shipping_available = bool(shipping_info["shipping_allowed"])
            elif "shipping_allowed" in it:
                shipping_available = bool(it.get("shipping_allowed"))

            # Distance & shipping constraint filtering
            if sf.require_shipping_or_local:
                valid_dist = (distance_km is not None and sf.max_distance_km is not None and distance_km <= sf.max_distance_km)
                if not (valid_dist or shipping_available):
                    continue
            elif sf.max_distance_km is not None:
                if distance_km is not None and distance_km > sf.max_distance_km:
                    continue

            # Forensic Bait Detection
            is_placeholder_price = price in PLACEHOLDER_PRICES
            has_bait_description = any(phrase in description.lower() for phrase in BAIT_PHRASES)

            # Build direct listing URL
            direct_url = f"https://es.wallapop.com/item/{web_slug}"

            listing = Listing(
                id=item_id,
                title=title,
                price=price,
                shipping_cost=0.0,
                total_price=price,
                currency=currency,
                url=direct_url,
                platform=self.platform,
                seller_location=seller_location,
                distance_km=distance_km,
                shipping_available=shipping_available,
                is_reserved=is_reserved,
                description=description,
                specs={
                    "is_placeholder_price": is_placeholder_price,
                    "has_bait_description": has_bait_description,
                    "web_slug": web_slug,
                },
                raw_data=it
            )
            listings.append(listing)

        return listings

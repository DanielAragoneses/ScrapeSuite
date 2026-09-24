"""Abstract base scraper and HTTP client for ScrapeSuite."""
import abc
import logging
import math
import time
from typing import List, Optional, Dict, Any

import requests
from src.models import Listing, SearchFilter, Platform

logger = logging.getLogger(__name__)


class BaseScraper(abc.ABC):
    """Base class for all marketplace scrapers.
    
    Subclasses must define:
      - platform: Platform enum
      - search(query: str, search_filter: Optional[SearchFilter] = None) -> List[Listing]
    """
    platform: Platform = Platform.OTHER
    default_headers: Dict[str, str] = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    }

    def __init__(self, session: Optional[requests.Session] = None, delay: float = 0.3):
        self.session = session or requests.Session()
        self.session.headers.update(self.default_headers)
        self.delay = delay

    @abc.abstractmethod
    def search(self, query: str, search_filter: Optional[SearchFilter] = None) -> List[Listing]:
        """Perform search on platform and return normalized Listing objects."""
        pass

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

    def rate_limit(self):
        """Throttle requests politely to respect target servers."""
        if self.delay > 0:
            time.sleep(self.delay)

    def safe_get(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 12
    ) -> Optional[requests.Response]:
        """Polite GET request with exception handling and custom headers."""
        try:
            self.rate_limit()
            h = dict(self.session.headers)
            if headers:
                h.update(headers)
            resp = self.session.get(url, params=params, headers=h, timeout=timeout)
            return resp
        except Exception as e:
            logger.warning(f"[{self.platform.value}] GET {url} failed: {e}")
            return None

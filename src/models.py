"""Unified data models for ScrapeSuite."""
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, List, Dict, Any
import datetime


class Platform(str, Enum):
    WALLAPOP = "wallapop"
    ALIEXPRESS = "aliexpress"
    EBAY = "ebay"
    EL_CHAPUZAS = "el_chapuzas"
    INFO_COMPUTER = "info_computer"
    COCHES_NET = "coches_net"
    AUTOSCOUT24 = "autoscout24"
    UR_NET = "ur_net"
    OTHER = "other"


@dataclass
class SearchFilter:
    """Universal search filters across platforms."""
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    category_id: Optional[str] = None       # Platform-specific category (e.g. '100' for cars on Wallapop)
    latitude: Optional[float] = 40.385       # Default: Loeches / Madrid
    longitude: Optional[float] = -3.314
    max_distance_km: Optional[float] = None  # None = no distance limit
    require_shipping_or_local: bool = False
    order_by: Optional[str] = "price_low_to_high"
    exclude_keywords: List[str] = field(default_factory=list)
    min_year: Optional[int] = None
    max_year: Optional[int] = None
    max_mileage_km: Optional[int] = None
    countries: List[str] = field(default_factory=list)
    fuel_type: Optional[str] = None
    gearbox: Optional[str] = None
    body_type: Optional[str] = None
    audit_descriptions: bool = False
    min_area_m2: Optional[float] = None
    max_area_m2: Optional[float] = None
    layout: Optional[str] = None
    prefecture: Optional[str] = None
    ward: Optional[str] = None
    only_vacant: bool = True


@dataclass
class Listing:
    """Normalized listing object representing an item from any marketplace."""
    id: str
    title: str
    price: float
    shipping_cost: float = 0.0
    total_price: float = 0.0
    currency: str = "EUR"
    url: str = ""
    platform: Platform = Platform.OTHER
    seller_location: Optional[str] = None
    distance_km: Optional[float] = None
    shipping_available: bool = True
    is_reserved: bool = False
    description: str = ""
    specs: Dict[str, Any] = field(default_factory=dict)
    raw_data: Dict[str, Any] = field(default_factory=dict)
    scraped_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())

    def __post_init__(self):
        if self.total_price <= 0.0:
            self.total_price = round(self.price + self.shipping_cost, 2)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["platform"] = self.platform.value
        return d

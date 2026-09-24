"""UR-Net (UR Housing / 都市再生機構) scraper implementation for ScrapeSuite.

Extracts public and affordable rental housing listings across Japan using UR-Net's
official REST API (chintai.r6.ur-net.go.jp/chintai/api/), bypassing WAFs without
headless browsers. Features prefecture & ward resolution, room vacancy tracking,
and UR's hallmark Zero-Key-Money / Zero-Guarantor contract normalization.
"""
import logging
import html
import re
from typing import List, Optional, Dict, Any, Tuple
from urllib.parse import urljoin

import requests

from src.models import Listing, SearchFilter, Platform
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

# Official UR-Net REST API Endpoints
UR_API_BASE = "https://chintai.r6.ur-net.go.jp/chintai/api/"
UR_ENDPOINT_LIST_BUKKEN = "https://chintai.r6.ur-net.go.jp/chintai/api/bukken/search/list_bukken/"
UR_ENDPOINT_ROOM_LIST = "https://chintai.r6.ur-net.go.jp/chintai/api/room/list/"
UR_WEB_BASE = "https://www.ur-net.go.jp"

# Japanese Prefecture Mapping (ISO 3166-2:JP code -> UR 'tdfk' param & Japanese name)
PREFECTURE_MAP: Dict[str, Tuple[str, str, str]] = {
    # Kanto
    "tokyo": ("13", "kanto", "東京都"),
    "13": ("13", "kanto", "東京都"),
    "kanagawa": ("14", "kanto", "神奈川県"),
    "14": ("14", "kanto", "神奈川県"),
    "yokohama": ("14", "kanto", "神奈川県"),
    "kawasaki": ("14", "kanto", "神奈川県"),
    "saitama": ("11", "kanto", "埼玉県"),
    "11": ("11", "kanto", "埼玉県"),
    "chiba": ("12", "kanto", "千葉県"),
    "12": ("12", "kanto", "千葉県"),
    "ibaraki": ("08", "kanto", "茨城県"),
    "08": ("08", "kanto", "茨城県"),
    "tsukuba": ("08", "kanto", "茨城県"),
    # Kansai
    "osaka": ("27", "kansai", "大阪府"),
    "27": ("27", "kansai", "大阪府"),
    "hyogo": ("28", "kansai", "兵庫県"),
    "28": ("28", "kansai", "兵庫県"),
    "kobe": ("28", "kansai", "兵庫県"),
    "kyoto": ("26", "kansai", "京都府"),
    "26": ("26", "kansai", "京都府"),
    "nara": ("29", "kansai", "奈良県"),
    "29": ("29", "kansai", "奈良県"),
    "shiga": ("25", "kansai", "滋賀県"),
    "25": ("25", "kansai", "滋賀県"),
    # Tokai
    "aichi": ("23", "tokai", "愛知県"),
    "23": ("23", "tokai", "愛知県"),
    "nagoya": ("23", "tokai", "愛知県"),
    "mie": ("24", "tokai", "三重県"),
    "24": ("24", "tokai", "三重県"),
    "gifu": ("21", "tokai", "岐阜県"),
    "21": ("21", "tokai", "岐阜県"),
    "shizuoka": ("22", "tokai", "静岡県"),
    "22": ("22", "tokai", "静岡県"),
    # Kyushu
    "fukuoka": ("40", "kyushu", "福岡県"),
    "40": ("40", "kyushu", "福岡県"),
    "hakata": ("40", "kyushu", "福岡県"),
    "kitakyushu": ("40", "kyushu", "福岡県"),
    # Tohoku & Hokkaido
    "miyagi": ("04", "tohoku", "宮城県"),
    "04": ("04", "tohoku", "宮城県"),
    "sendai": ("04", "tohoku", "宮城県"),
    "hokkaido": ("01", "hokkaido", "北海道"),
    "01": ("01", "hokkaido", "北海道"),
    "sapporo": ("01", "hokkaido", "北海道"),
}

# Sub-Area IDs for Prefectures
# Tokyo Areas: 01=Central 6 Wards, 02=East, 03=South, 04=West, 05=North, 06=Tama/Cities
TOKYO_AREAS = ["01", "02", "03", "04", "05", "06"]
KANAGAWA_AREAS = ["01", "02", "03"]
OSAKA_AREAS = ["01", "02", "03"]

# Tokyo Wards to Area ID mapping
TOKYO_WARD_AREAS: Dict[str, Tuple[str, str]] = {
    # 01 都心
    "chiyoda": ("01", "千代田"), "千代田": ("01", "千代田"), "千代田区": ("01", "千代田"),
    "chuo": ("01", "中央"), "中央": ("01", "中央"), "中央区": ("01", "中央"),
    "minato": ("01", "港"), "港": ("01", "港"), "港区": ("01", "港"),
    "shinjuku": ("01", "新宿"), "新宿": ("01", "新宿"), "新宿区": ("01", "新宿"),
    "shibuya": ("01", "渋谷"), "渋谷": ("01", "渋谷"), "渋谷区": ("01", "渋谷"),
    "bunkyo": ("01", "文京"), "文京": ("01", "文京"), "文京区": ("01", "文京"),
    # 02 23区東
    "taito": ("02", "台東"), "台東": ("02", "台東"), "台東区": ("02", "台東"),
    "sumida": ("02", "墨田"), "墨田": ("02", "墨田"), "墨田区": ("02", "墨田"),
    "koto": ("02", "江東"), "江東": ("02", "江東"), "江東区": ("02", "江東"),
    "arakawa": ("02", "荒川"), "荒川": ("02", "荒川"), "荒川区": ("02", "荒川"),
    "katsushika": ("02", "葛飾"), "葛飾": ("02", "葛飾"), "葛飾区": ("02", "葛飾"),
    "edogawa": ("02", "江戸川"), "江戸川": ("02", "江戸川"), "江戸川区": ("02", "江戸川"),
    # 03 23区南
    "shinagawa": ("03", "品川"), "品川": ("03", "品川"), "品川区": ("03", "品川"),
    "meguro": ("03", "目黒"), "目黒": ("03", "目黒"), "目黒区": ("03", "目黒"),
    "ota": ("03", "大田"), "大田": ("03", "大田"), "大田区": ("03", "大田"),
    "setagaya": ("03", "世田谷"), "世田谷": ("03", "世田谷"), "世田谷区": ("03", "世田谷"),
    # 04 23区西
    "nakano": ("04", "中野"), "中野": ("04", "中野"), "中野区": ("04", "中野"),
    "suginami": ("04", "杉並"), "杉並": ("04", "杉並"), "杉並区": ("04", "杉並"),
    "nerima": ("04", "練馬"), "練馬": ("04", "練馬"), "練馬区": ("04", "練馬"),
    # 05 23区北
    "toshima": ("05", "豊島"), "豊島": ("05", "豊島"), "豊島区": ("05", "豊島"),
    "kita": ("05", "北"), "北": ("05", "北"), "北区": ("05", "北"),
    "itabashi": ("05", "板橋"), "板橋": ("05", "板橋"), "板橋区": ("05", "板橋"),
    "adachi": ("05", "足立"), "足立": ("05", "足立"), "足立区": ("05", "足立"),
    # 06 市部 (Tama / Outlying Cities)
    "musashino": ("06", "武蔵野"), "kichijoji": ("06", "武蔵野"), "武蔵野市": ("06", "武蔵野"),
    "mitaka": ("06", "三鷹"), "三鷹市": ("06", "三鷹"),
    "hachioji": ("06", "八王子"), "八王子市": ("06", "八王子"),
    "tachikawa": ("06", "立川"), "立川市": ("06", "立川"),
    "machida": ("06", "町田"), "町田市": ("06", "町田"),
    "chofu": ("06", "調布"), "調布市": ("06", "調布"),
    "fuchu": ("06", "府中"), "府中市": ("06", "府中"),
    "koganei": ("06", "小金井"), "小金井市": ("06", "小金井"),
    "tama": ("06", "多摩"), "多摩市": ("06", "多摩"),
    "kokubunji": ("06", "国分寺"), "国分寺市": ("06", "国分寺"),
    "kunitachi": ("06", "国立"), "国立市": ("06", "国立"),
    "nishitokyo": ("06", "西東京"), "西東京市": ("06", "西東京"),
}

# Layout mapping (e.g. 1R, 1K, 1DK, 1LDK, 2K, 2DK, 2LDK, 3LDK, 4LDK)
LAYOUT_ALIASES: Dict[str, str] = {
    "1r": "1R", "1k": "1K", "1dk": "1DK", "1ldk": "1LDK",
    "2k": "2K", "2dk": "2DK", "2ldk": "2LDK",
    "3k": "3K", "3dk": "3DK", "3ldk": "3LDK",
    "4k": "4K", "4dk": "4DK", "4ldk": "4LDK",
}


class URNetScraper(BaseScraper):
    """Production-grade scraper for UR-Net (UR Housing / 都市再生機構) in Japan.

    Uses UR-Net's internal REST API endpoints to fetch properties and vacant rooms
    across Japan with zero key money (礼金0), zero agency fees (仲介手数料0),
    zero renewal fees (更新料0), and no guarantor required (保証人不要).
    """
    platform: Platform = Platform.UR_NET

    API_HEADERS: Dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Origin": "https://www.ur-net.go.jp",
        "Referer": "https://www.ur-net.go.jp/chintai/",
        "Sec-Ch-Ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
    }

    def __init__(self, session: Optional[requests.Session] = None, delay: float = 0.3):
        super().__init__(session=session, delay=delay)
        self.session.headers.update(self.API_HEADERS)
        self._session_warmed = False

    def _ensure_session(self, tdfk_code: str = "13"):
        """Warm session to acquire F5 BIG-IP anti-bot session cookies."""
        if self._session_warmed:
            return
        try:
            init_url = f"{UR_WEB_BASE}/chintai/kanto/tokyo/list/"
            self.session.get(init_url, timeout=10)
            self._session_warmed = True
        except Exception as e:
            logger.debug(f"Failed to pre-warm UR-Net session: {e}")
    @classmethod
    def parse_housing_query(
        cls, query: str
    ) -> Tuple[str, List[str], Optional[str], Optional[str], List[str]]:
        """Parse free-form user query into (tdfk_code, area_ids, ward_filter, layout_filter, remaining_tokens).

        Examples:
          "tokyo"           -> ("13", ["01", "02", "03", "04", "05", "06"], None, None, [])
          "shinjuku 1ldk"   -> ("13", ["01"], "新宿区", "1LDK", [])
          "shibuya"         -> ("13", ["01"], "渋谷区", None, [])
          "koto 2ldk"       -> ("13", ["02"], "江東区", "2LDK", [])
          "osaka"           -> ("27", ["01", "02", "03"], None, None, [])
          "yokohama"        -> ("14", ["01"], None, None, [])
        """
        raw = query.strip().lower()
        tokens = re.split(r"[\s,]+", raw) if raw else []

        tdfk_code = "13"  # Default to Tokyo
        area_ids: List[str] = list(TOKYO_AREAS)
        ward_filter: Optional[str] = None
        layout_filter: Optional[str] = None
        rem_tokens: List[str] = []

        for token in tokens:
            t_clean = re.sub(r"(-ku|区)$", "", token.strip().lower())

            # Check if token matches a Tokyo ward/municipality
            if t_clean in TOKYO_WARD_AREAS:
                area_id, kanji = TOKYO_WARD_AREAS[t_clean]
                area_ids = [area_id]
                ward_filter = kanji
                tdfk_code = "13"
                continue
            # Check if token matches a prefecture / major city
            if t_clean in PREFECTURE_MAP:
                code, region, pref_name = PREFECTURE_MAP[t_clean]
                tdfk_code = code
                if code == "13":
                    area_ids = list(TOKYO_AREAS)
                elif code == "14":
                    area_ids = list(KANAGAWA_AREAS)
                elif code == "27":
                    area_ids = list(OSAKA_AREAS)
                else:
                    area_ids = ["01"]
                continue

            # Check if token matches a layout code (1R, 1K, 1LDK, 2LDK, etc.)
            if t_clean in LAYOUT_ALIASES:
                layout_filter = LAYOUT_ALIASES[t_clean]
                continue

            rem_tokens.append(token)

        return tdfk_code, area_ids, ward_filter, layout_filter, rem_tokens

    def fetch_property_rooms(self, property_id: str) -> List[Dict[str, Any]]:
        """Query UR-Net room list API for all available rooms in a specific housing complex."""
        payload = {
            "id": property_id,
            "mode": "init",
        }
        try:
            self.rate_limit()
            resp = self.session.post(
                UR_ENDPOINT_ROOM_LIST,
                data=payload,
                headers=self.API_HEADERS,
                timeout=25
            )
            if resp.status_code != 200:
                logger.warning(f"Failed to fetch rooms for property {property_id}: HTTP {resp.status_code}")
                return []
            data = resp.json()
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.warning(f"Exception fetching rooms for property {property_id}: {e}")
            return []

    def search(
        self,
        query: str,
        search_filter: Optional[SearchFilter] = None,
        fetch_rooms: bool = True,
        max_properties: int = 15,
    ) -> List[Listing]:
        """Perform search across UR-Net Japanese housing and return normalized Listing objects."""
        sf = search_filter or SearchFilter()

        # 1. Parse query parameters
        tdfk_code, area_ids, ward_filter, layout_filter, rem_tokens = self.parse_housing_query(query)

        # Allow explicit overrides from SearchFilter
        if sf.category_id:
            tdfk_code = sf.category_id
        if sf.prefecture and sf.prefecture.lower() in PREFECTURE_MAP:
            tdfk_code = PREFECTURE_MAP[sf.prefecture.lower()][0]
        if sf.ward:
            ward_filter = sf.ward.lower()
        if sf.layout:
            layout_filter = sf.layout.upper()

        logger.info(
            f"[UR-Net] Searching housing: Prefecture {tdfk_code}, Areas {area_ids}, "
            f"Ward: {ward_filter}, Layout: {layout_filter}"
        )

        listings: List[Listing] = []
        properties_processed = 0

        self._ensure_session(tdfk_code)
        for area_id in area_ids:
            payload: Dict[str, Any] = {
                "tdfk": tdfk_code,
                "area": area_id,
            }
            if sf.min_price is not None:
                payload["rent_low"] = str(int(sf.min_price))
            if sf.max_price is not None:
                payload["rent_high"] = str(int(sf.max_price))

            try:
                self.rate_limit()
                resp = self.session.post(
                    UR_ENDPOINT_LIST_BUKKEN,
                    data=payload,
                    headers=self.API_HEADERS,
                    timeout=25
                )
            except Exception as e:
                logger.warning(f"Failed to query list_bukken for area {area_id}: {e}")
                continue

            if not resp or resp.status_code != 200:
                continue

            try:
                raw_properties = resp.json()
            except Exception as e:
                logger.warning(f"Could not parse JSON for area {area_id}: {e}")
                continue

            if not isinstance(raw_properties, list):
                continue

            for prop in raw_properties:
                if properties_processed >= max_properties:
                    break

                # Filter by ward/municipality if specified
                skcs = prop.get("skcs") or ""
                if ward_filter and ward_filter not in skcs and ward_filter not in prop.get("name", ""):
                    continue

                # Filter by negative keywords if any
                if sf.exclude_keywords:
                    full_text = f"{prop.get('name')} {skcs} {prop.get('access')}".lower()
                    if any(exc.strip().lstrip("-").lower() in full_text for exc in sf.exclude_keywords if exc):
                        continue

                room_count = prop.get("roomCount", 0)

                # Filter by vacancy if requested
                if sf.only_vacant and room_count <= 0:
                    continue

                # Fetch individual available rooms
                if fetch_rooms and room_count > 0:
                    rooms = self.fetch_property_rooms(prop.get("id", ""))
                    if rooms:
                        for room in rooms:
                            room_listing = self._normalize_room_item(
                                prop=prop,
                                room=room,
                                tdfk_code=tdfk_code,
                                layout_filter=layout_filter,
                                sf=sf
                            )
                            if room_listing is not None:
                                listings.append(room_listing)
                    else:
                        prop_listing = self._normalize_property_item(
                            prop=prop,
                            tdfk_code=tdfk_code,
                            sf=sf
                        )
                        if prop_listing is not None:
                            listings.append(prop_listing)
                else:
                    prop_listing = self._normalize_property_item(
                        prop=prop,
                        tdfk_code=tdfk_code,
                        sf=sf
                    )
                    if prop_listing is not None:
                        listings.append(prop_listing)

                properties_processed += 1

        # Sort listings by price
        if sf.order_by in ("price_high_to_low", "price_desc"):
            listings.sort(key=lambda x: x.price, reverse=True)
        else:
            listings.sort(key=lambda x: x.price)

        return listings

    def _normalize_room_item(
        self,
        prop: Dict[str, Any],
        room: Dict[str, Any],
        tdfk_code: str,
        layout_filter: Optional[str],
        sf: SearchFilter,
    ) -> Optional[Listing]:
        """Convert a vacant room JSON object into a normalized Listing."""
        room_id = str(room.get("id") or "")
        prop_id = str(prop.get("id") or "")
        listing_id = f"{prop_id}_{room_id}" if room_id else prop_id

        danchi_name = prop.get("name") or "UR Housing Complex"
        room_name = room.get("name") or "Vacant Unit"
        madori_type = room.get("type") or prop.get("type") or ""

        # Filter by layout if specified
        if layout_filter and layout_filter.upper() not in madori_type.upper():
            return None

        # Clean floor space (e.g. '83&#13217;' or '45㎡' -> 45.0)
        raw_space = str(room.get("floorspace") or "")
        match_space = re.search(r"^(\d+(?:\.\d+)?)", raw_space.split("&#")[0].split("㎡")[0].strip())
        space_m2 = float(match_space.group(1)) if match_space else 0.0
        if sf.min_area_m2 is not None and space_m2 < sf.min_area_m2:
            return None
        if sf.max_area_m2 is not None and space_m2 > sf.max_area_m2:
            return None

        # Clean rent price in JPY
        raw_rent = str(room.get("rent") or "")
        clean_rent = re.sub(r"[^\d]", "", raw_rent)
        price_jpy = float(clean_rent) if clean_rent else 0.0

        if sf.min_price is not None and price_jpy < sf.min_price:
            return None
        if sf.max_price is not None and price_jpy > sf.max_price:
            return None

        # Clean common/maintenance fee
        raw_fee = str(room.get("commonfee") or prop.get("commonfee") or "")
        clean_fee = re.sub(r"[^\d]", "", raw_fee)
        commonfee_jpy = float(clean_fee) if clean_fee else 0.0

        floor_str = str(room.get("floor") or "")

        # Assemble clean title
        title_parts = [danchi_name, room_name]
        specs_summary = []
        if madori_type:
            specs_summary.append(madori_type)
        if space_m2 > 0:
            specs_summary.append(f"{space_m2:.0f}㎡")
        if floor_str:
            specs_summary.append(floor_str)
        if specs_summary:
            title_parts.append(f"({', '.join(specs_summary)})")
        title = " ".join(title_parts)

        # URL
        rel_url = room.get("urlDetail") or prop.get("bukkenUrl") or ""
        full_url = urljoin(UR_WEB_BASE, rel_url)

        # Location & Access
        skcs = prop.get("skcs") or ""
        pref_name = "東京都" if tdfk_code == "13" else "Japan"
        seller_location = f"{pref_name} {skcs}".strip()

        raw_access = prop.get("access") or ""
        clean_access = re.sub(r"<[^>]+>", " | ", raw_access).strip(" | ")

        # Images: exterior photo + floorplan diagram
        images = []
        if prop.get("image"):
            images.append(prop["image"])
        if room.get("madori") and room["madori"].startswith("http"):
            images.append(room["madori"])

        specs: Dict[str, Any] = {
            "danchi_name": danchi_name,
            "room_name": room_name,
            "madori": madori_type,
            "floorspace_m2": space_m2,
            "floor": floor_str,
            "rent_jpy": price_jpy,
            "commonfee_jpy": commonfee_jpy,
            "key_money_jpy": 0.0,           # 礼金なし (Zero Reikin)
            "agency_fee_jpy": 0.0,          # 仲介手数料なし (Zero Chukai-Tesuryo)
            "renewal_fee_jpy": 0.0,         # 更新料なし (Zero Koshin-Ryo)
            "guarantor_required": False,    # 保証人不要 (No guarantor required)
            "access": clean_access,
            "ward": skcs,
            "prefecture_code": tdfk_code,
            "images": images,
            "exterior_image": prop.get("image"),
            "floorplan_image": room.get("madori"),
            "vacant_rooms_in_complex": prop.get("roomCount", 1),
        }

        desc = (
            f"UR Housing (都市再生機構): {danchi_name} {room_name}\n"
            f"Layout: {madori_type} ({space_m2:.1f} m²) | Floor: {floor_str}\n"
            f"Rent: ¥{price_jpy:,.0f}/mo | Common Fee: ¥{commonfee_jpy:,.0f}/mo\n"
            f"★ ZERO Key Money (礼金0) | ZERO Agency Fee (仲介手数料0) | ZERO Renewal Fee (更新料0) | NO Guarantor (保証人不要)\n"
            f"Access: {clean_access}"
        )

        return Listing(
            id=listing_id,
            title=title,
            price=price_jpy,
            shipping_cost=commonfee_jpy,
            total_price=round(price_jpy + commonfee_jpy, 2),
            currency="JPY",
            url=full_url,
            platform=self.platform,
            seller_location=seller_location,
            distance_km=None,
            shipping_available=False,
            is_reserved=False,
            description=desc,
            specs=specs,
            raw_data={"property": prop, "room": room},
        )

    def _normalize_property_item(
        self,
        prop: Dict[str, Any],
        tdfk_code: str,
        sf: SearchFilter,
    ) -> Optional[Listing]:
        """Convert a housing complex JSON object into a normalized property-level Listing."""
        prop_id = str(prop.get("id") or "")
        danchi_name = prop.get("name") or "UR Housing Complex"
        skcs = prop.get("skcs") or ""
        room_count = prop.get("roomCount", 0)

        # Parse rent range (e.g. '84,900円～199,100円')
        raw_rent = str(prop.get("rent") or "")
        rent_matches = re.findall(r"([\d,]+)円", raw_rent)
        prices = [float(m.replace(",", "")) for m in rent_matches if m.replace(",", "").isdigit()]
        min_price = prices[0] if prices else 0.0

        if sf.min_price is not None and min_price < sf.min_price:
            return None
        if sf.max_price is not None and min_price > sf.max_price:
            return None

        # Common fee
        raw_fee = str(prop.get("commonfee") or "")
        clean_fee = re.sub(r"[^\d]", "", raw_fee)
        commonfee_jpy = float(clean_fee) if clean_fee else 0.0

        pref_name = "東京都" if tdfk_code == "13" else "Japan"
        seller_location = f"{pref_name} {skcs}".strip()

        rel_url = prop.get("bukkenUrl") or ""
        full_url = urljoin(UR_WEB_BASE, rel_url)

        raw_access = prop.get("access") or ""
        clean_access = re.sub(r"<[^>]+>", " | ", raw_access).strip(" | ")

        images = [prop["image"]] if prop.get("image") else []

        specs: Dict[str, Any] = {
            "danchi_name": danchi_name,
            "room_name": None,
            "madori": None,
            "floorspace_m2": None,
            "floor": None,
            "rent_jpy": min_price,
            "rent_range": raw_rent,
            "commonfee_jpy": commonfee_jpy,
            "key_money_jpy": 0.0,
            "agency_fee_jpy": 0.0,
            "renewal_fee_jpy": 0.0,
            "guarantor_required": False,
            "access": clean_access,
            "ward": skcs,
            "prefecture_code": tdfk_code,
            "images": images,
            "vacant_rooms_in_complex": room_count,
        }

        title = f"{danchi_name} ({skcs}) - {room_count} Vacant Units"

        desc = (
            f"UR Housing Complex: {danchi_name}\n"
            f"Location: {seller_location}\n"
            f"Rent Range: {raw_rent} | Common Fee: ¥{commonfee_jpy:,.0f}/mo\n"
            f"Available Vacant Units: {room_count}\n"
            f"★ ZERO Key Money | ZERO Agency Fee | ZERO Renewal Fee | NO Guarantor Required\n"
            f"Access: {clean_access}"
        )

        return Listing(
            id=prop_id,
            title=title,
            price=min_price,
            shipping_cost=commonfee_jpy,
            total_price=round(min_price + commonfee_jpy, 2),
            currency="JPY",
            url=full_url,
            platform=self.platform,
            seller_location=seller_location,
            distance_km=None,
            shipping_available=False,
            is_reserved=False,
            description=desc,
            specs=specs,
            raw_data=prop,
        )

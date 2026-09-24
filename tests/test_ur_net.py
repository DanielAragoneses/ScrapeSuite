"""Unit and integration tests for UR-Net Japanese housing scraper."""
import json
import unittest
from unittest.mock import MagicMock, patch

from src.models import Listing, SearchFilter, Platform
from src.scrapers.ur_net import (
    URNetScraper,
    PREFECTURE_MAP,
    TOKYO_AREAS,
    TOKYO_WARD_AREAS,
    LAYOUT_ALIASES,
)


class TestURNetScraper(unittest.TestCase):

    def setUp(self):
        self.scraper = URNetScraper(delay=0.0)

    def test_platform_and_init(self):
        self.assertEqual(self.scraper.platform, Platform.UR_NET)
        self.assertIn("User-Agent", self.scraper.session.headers)
        self.assertEqual(self.scraper.session.headers["Origin"], "https://www.ur-net.go.jp")
        self.assertEqual(self.scraper.session.headers["Referer"], "https://www.ur-net.go.jp/chintai/")

    def test_parse_housing_query_tokyo_and_wards(self):
        # Tokyo general
        tdfk, areas, ward, layout, rem = self.scraper.parse_housing_query("tokyo")
        self.assertEqual(tdfk, "13")
        self.assertEqual(areas, TOKYO_AREAS)
        self.assertIsNone(ward)
        self.assertIsNone(layout)

        # Shinjuku
        tdfk, areas, ward, layout, rem = self.scraper.parse_housing_query("shinjuku")
        self.assertEqual(tdfk, "13")
        self.assertEqual(areas, ["01"])
        self.assertEqual(ward, "新宿")

        # Shinjuku-ku
        tdfk, areas, ward, layout, rem = self.scraper.parse_housing_query("shinjuku-ku")
        self.assertEqual(tdfk, "13")
        self.assertEqual(areas, ["01"])
        self.assertEqual(ward, "新宿")

        # Shibuya 1LDK
        tdfk, areas, ward, layout, rem = self.scraper.parse_housing_query("shibuya 1ldk")
        self.assertEqual(tdfk, "13")
        self.assertEqual(areas, ["01"])
        self.assertEqual(ward, "渋谷")
        self.assertEqual(layout, "1LDK")

        # Koto-ku 2LDK
        tdfk, areas, ward, layout, rem = self.scraper.parse_housing_query("koto 2ldk")
        self.assertEqual(tdfk, "13")
        self.assertEqual(areas, ["02"])
        self.assertEqual(ward, "江東")
        self.assertEqual(layout, "2LDK")

        # Hachioji
        tdfk, areas, ward, layout, rem = self.scraper.parse_housing_query("hachioji 3ldk")
        self.assertEqual(tdfk, "13")
        self.assertEqual(areas, ["06"])
        self.assertEqual(ward, "八王子")
        self.assertEqual(layout, "3LDK")

    def test_parse_housing_query_other_prefectures(self):
        # Osaka
        tdfk, areas, ward, layout, rem = self.scraper.parse_housing_query("osaka")
        self.assertEqual(tdfk, "27")
        self.assertEqual(areas, ["01", "02", "03"])

        # Yokohama / Kanagawa
        tdfk, areas, ward, layout, rem = self.scraper.parse_housing_query("yokohama")
        self.assertEqual(tdfk, "14")
        self.assertEqual(areas, ["01", "02", "03"])

        # Kyoto
        tdfk, areas, ward, layout, rem = self.scraper.parse_housing_query("kyoto")
        self.assertEqual(tdfk, "26")

        # Fukuoka
        tdfk, areas, ward, layout, rem = self.scraper.parse_housing_query("fukuoka")
        self.assertEqual(tdfk, "40")

    def test_normalize_room_item(self):
        sample_prop = {
            "id": "20_5900",
            "name": "シティコート大島",
            "skcs": "江東区",
            "roomCount": 2,
            "commonfee": "（5,500円）",
            "access": "<li>都営新宿線｢大島｣駅 徒歩5分</li>",
            "image": "https://chintai.r6.ur-net.go.jp/chintai/img_photo/20/20_590/20_590_photo.jpg",
            "bukkenUrl": "/chintai/kanto/tokyo/20_5900.html",
        }

        sample_room = {
            "id": "000021001",
            "name": "2号棟1001号室",
            "type": "2LDK",
            "floorspace": "83&#13217;",
            "floor": "10階",
            "rent": "244,200円",
            "commonfee": "（5,500円）",
            "madori": "https://sumai.r6.ur-net.go.jp/chintai/madori.gif",
            "urlDetail": "/chintai/kanto/tokyo/20_5900_room.html?JKSS=000021001",
        }

        sf = SearchFilter()
        listing = self.scraper._normalize_room_item(
            prop=sample_prop,
            room=sample_room,
            tdfk_code="13",
            layout_filter=None,
            sf=sf
        )

        self.assertIsNotNone(listing)
        self.assertEqual(listing.id, "20_5900_000021001")
        self.assertEqual(listing.platform, Platform.UR_NET)
        self.assertEqual(listing.currency, "JPY")
        self.assertEqual(listing.price, 244200.0)
        self.assertEqual(listing.shipping_cost, 5500.0)
        self.assertEqual(listing.total_price, 249700.0)
        self.assertIn("シティコート大島 2号棟1001号室", listing.title)
        self.assertIn("2LDK", listing.title)
        self.assertIn("83㎡", listing.title)
        self.assertEqual(listing.seller_location, "東京都 江東区")
        self.assertEqual(listing.url, "https://www.ur-net.go.jp/chintai/kanto/tokyo/20_5900_room.html?JKSS=000021001")

        # Verify UR Perks in specs
        specs = listing.specs
        self.assertEqual(specs["madori"], "2LDK")
        self.assertEqual(specs["floorspace_m2"], 83.0)
        self.assertEqual(specs["floor"], "10階")
        self.assertEqual(specs["key_money_jpy"], 0.0)
        self.assertEqual(specs["agency_fee_jpy"], 0.0)
        self.assertEqual(specs["renewal_fee_jpy"], 0.0)
        self.assertFalse(specs["guarantor_required"])
        self.assertIn("都営新宿線｢大島｣駅 徒歩5分", specs["access"])

        # Dict conversion
        d = listing.to_dict()
        self.assertEqual(d["platform"], "ur_net")
        self.assertEqual(d["price"], 244200.0)

    def test_normalize_property_item_fallback(self):
        sample_prop = {
            "id": "20_3820",
            "name": "神田小川町ハイツ",
            "skcs": "千代田区",
            "roomCount": 0,
            "rent": "84,900円～199,100円",
            "commonfee": "（8,500円）",
            "access": "<li>都営新宿線｢小川町｣駅 徒歩2分</li>",
            "image": "https://chintai.r6.ur-net.go.jp/photo.jpg",
            "bukkenUrl": "/chintai/kanto/tokyo/20_3820.html",
        }
        sf = SearchFilter(only_vacant=False)
        listing = self.scraper._normalize_property_item(sample_prop, "13", sf)

        self.assertIsNotNone(listing)
        self.assertEqual(listing.id, "20_3820")
        self.assertEqual(listing.price, 84900.0)
        self.assertEqual(listing.shipping_cost, 8500.0)
        self.assertIn("神田小川町ハイツ", listing.title)
        self.assertEqual(listing.specs["key_money_jpy"], 0.0)
        self.assertEqual(listing.specs["vacant_rooms_in_complex"], 0)

    def test_room_filters_layout_and_area(self):
        sample_prop = {"id": "p-1", "name": "Test Complex", "skcs": "世田谷区", "roomCount": 1}
        sample_room = {
            "id": "r-1", "name": "101", "type": "1K", "floorspace": "28&#13217;",
            "floor": "1階", "rent": "65,000円", "commonfee": "3,000円"
        }

        # Match 1K
        sf = SearchFilter()
        l_match = self.scraper._normalize_room_item(sample_prop, sample_room, "13", "1K", sf)
        self.assertIsNotNone(l_match)

        # Mismatch layout: requested 2LDK
        l_mismatch = self.scraper._normalize_room_item(sample_prop, sample_room, "13", "2LDK", sf)
        self.assertIsNone(l_mismatch)

        # Mismatch area: minimum 40m2
        sf_area = SearchFilter(min_area_m2=40.0)
        l_small = self.scraper._normalize_room_item(sample_prop, sample_room, "13", None, sf_area)
        self.assertIsNone(l_small)

        # Mismatch price: max 50,000 yen
        sf_price = SearchFilter(max_price=50000.0)
        l_expensive = self.scraper._normalize_room_item(sample_prop, sample_room, "13", None, sf_price)
        self.assertIsNone(l_expensive)

    @patch.object(URNetScraper, "fetch_property_rooms")
    @patch.object(URNetScraper, "safe_get")
    @patch("requests.Session.post")
    def test_mocked_search_workflow(self, mock_post, mock_safe_get, mock_fetch_rooms):
        # Mock list_bukken response
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {
                "id": "20_1111",
                "name": "Mock Danchi Setagaya",
                "skcs": "世田谷区",
                "roomCount": 1,
                "rent": "90,000円",
                "commonfee": "4,000円",
                "access": "徒歩3分",
                "bukkenUrl": "/mock.html",
            }
        ]
        mock_post.return_value = mock_resp

        # Mock room/list response
        mock_fetch_rooms.return_value = [
            {
                "id": "room-101",
                "name": "101号室",
                "type": "1LDK",
                "floorspace": "45&#13217;",
                "floor": "1階",
                "rent": "90,000円",
                "commonfee": "4,000円",
                "urlDetail": "/mock_room.html",
            }
        ]

        scraper = URNetScraper(delay=0.0)
        scraper._session_warmed = True

        results = scraper.search("setagaya", SearchFilter(), fetch_rooms=True)
        self.assertEqual(len(results), 1)
        res = results[0]
        self.assertEqual(res.id, "20_1111_room-101")
        self.assertEqual(res.price, 90000.0)
        self.assertEqual(res.shipping_cost, 4000.0)
        self.assertEqual(res.specs["madori"], "1LDK")
        self.assertEqual(res.specs["floorspace_m2"], 45.0)


if __name__ == "__main__":
    unittest.main()

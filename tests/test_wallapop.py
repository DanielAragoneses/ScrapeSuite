"""Unit tests for ScrapeSuite models and Wallapop scraper."""
import unittest
from src.models import Listing, SearchFilter, Platform
from src.scrapers.base import BaseScraper
from src.scrapers.wallapop import WallapopScraper, PLACEHOLDER_PRICES, BAIT_PHRASES


class TestScrapeSuite(unittest.TestCase):

    def test_listing_model(self):
        listing = Listing(
            id="test1234",
            title="Mazda MX-5 NA Pop-Up",
            price=3500.0,
            shipping_cost=0.0,
            platform=Platform.WALLAPOP,
            seller_location="Madrid, Comunidad de Madrid",
            distance_km=18.5,
            shipping_available=True,
            description="Coche clásico con faros escamoteables",
        )
        self.assertEqual(listing.total_price, 3500.0)
        self.assertEqual(listing.platform, Platform.WALLAPOP)
        d = listing.to_dict()
        self.assertEqual(d["platform"], "wallapop")
        self.assertEqual(d["title"], "Mazda MX-5 NA Pop-Up")

    def test_search_filter(self):
        sf = SearchFilter(
            min_price=50.0,
            max_price=200.0,
            category_id="100",
            exclude_keywords=["ventilador", "caja"],
        )
        self.assertEqual(sf.min_price, 50.0)
        self.assertEqual(sf.max_price, 200.0)
        self.assertEqual(sf.category_id, "100")
        self.assertEqual(len(sf.exclude_keywords), 2)

    def test_haversine_distance(self):
        # Madrid center to Loeches (~32 km)
        madrid_lat, madrid_lon = 40.4168, -3.7038
        loeches_lat, loeches_lon = 40.385, -3.314
        dist = WallapopScraper.haversine_distance(madrid_lat, madrid_lon, loeches_lat, loeches_lon)
        self.assertGreater(dist, 25.0)
        self.assertLess(dist, 40.0)

    def test_wallapop_scraper_init(self):
        scraper = WallapopScraper()
        self.assertEqual(scraper.platform, Platform.WALLAPOP)
        self.assertIn("Host", scraper.session.headers)
        self.assertEqual(scraper.session.headers["x-deviceos"], "0")

    def test_anti_bait_constants(self):
        self.assertIn(1234.0, PLACEHOLDER_PRICES)
        self.assertIn(1.0, PLACEHOLDER_PRICES)
        self.assertTrue(any("precio no es el del anuncio" in p for p in BAIT_PHRASES))

    def test_reserved_flag_parsing(self):
        """API returns {"reserved": {"flag": bool}}; both states must map through."""
        payload = {
            "data": {"section": {"items": [
                {
                    "id": "reserved1", "title": "Reserved board", "description": "",
                    "price": {"amount": 30.0, "currency": "EUR"},
                    "reserved": {"flag": True}, "web_slug": "reserved-board-1",
                    "location": {"city": "Madrid", "region": "Madrid",
                                 "latitude": 40.4, "longitude": -3.7},
                    "shipping": {"item_is_shippable": True, "user_allows_shipping": True},
                },
                {
                    "id": "free1", "title": "Available board", "description": "",
                    "price": {"amount": 30.0, "currency": "EUR"},
                    "reserved": {"flag": False}, "web_slug": "available-board-1",
                    "location": {"city": "Madrid", "region": "Madrid",
                                 "latitude": 40.4, "longitude": -3.7},
                    "shipping": {"item_is_shippable": True, "user_allows_shipping": True},
                },
            ]}},
        }

        class _Resp:
            status_code = 200
            def json(self):
                return payload

        scraper = WallapopScraper()
        scraper.safe_get = lambda *a, **kw: _Resp()
        results = scraper.search("teclado mecanico")
        by_id = {item.id: item for item in results}
        self.assertIs(by_id["reserved1"].is_reserved, True)
        self.assertIs(by_id["free1"].is_reserved, False)


if __name__ == "__main__":
    unittest.main()

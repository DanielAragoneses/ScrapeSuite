"""Unit and integration tests for AutoScout24 European scraper."""
import json
import unittest
from unittest.mock import MagicMock, patch

from src.models import Listing, SearchFilter, Platform
from src.scrapers.base import BaseScraper
from src.scrapers.autoscout24 import (
    AutoScout24Scraper,
    PLACEHOLDER_PRICES,
    BAIT_PHRASES,
    FORENSIC_DEFECT_PATTERNS,
    AUTOSCOUT_COUNTRY_MAP,
    FUEL_MAP,
    GEARBOX_MAP,
)


class TestAutoScout24Scraper(unittest.TestCase):

    def setUp(self):
        self.scraper = AutoScout24Scraper(delay=0.0)

    def test_platform_and_init(self):
        self.assertEqual(self.scraper.platform, Platform.AUTOSCOUT24)
        self.assertEqual(self.scraper.base_url, "https://www.autoscout24.com")
        self.assertIn("User-Agent", self.scraper.session.headers)
        self.assertIn("Sec-Ch-Ua", self.scraper.session.headers)

    def test_parse_query_slug(self):
        # Make + Model
        make, model, rem = self.scraper.parse_query_slug("toyota celica")
        self.assertEqual(make, "toyota")
        self.assertEqual(model, "celica")
        self.assertEqual(rem, [])

        # Make + Model with remaining tokens
        make, model, rem = self.scraper.parse_query_slug("mazda mx-5 nb")
        self.assertEqual(make, "mazda")
        self.assertEqual(model, "mx-5")
        self.assertEqual(rem, ["nb"])

        # Make alias (vw -> volkswagen)
        make, model, rem = self.scraper.parse_query_slug("vw golf gti")
        self.assertEqual(make, "volkswagen")
        self.assertEqual(model, "golf")
        self.assertEqual(rem, ["gti"])

        # Multi-word make (alfa romeo)
        make, model, rem = self.scraper.parse_query_slug("alfa romeo 147")
        self.assertEqual(make, "alfa-romeo")
        self.assertEqual(model, "147")
        self.assertEqual(rem, [])

        # Multi-word make (mercedes c 220)
        make, model, rem = self.scraper.parse_query_slug("mercedes c 220")
        self.assertEqual(make, "mercedes-benz")
        self.assertEqual(model, "c-220")

        # Iconic model standalone (miata -> mazda mx-5)
        make, model, rem = self.scraper.parse_query_slug("miata")
        self.assertEqual(make, "mazda")
        self.assertEqual(model, "mx-5")

        # Iconic model standalone (celica -> toyota celica)
        make, model, rem = self.scraper.parse_query_slug("celica")
        self.assertEqual(make, "toyota")
        self.assertEqual(model, "celica")

        # Model with generation (celica t23)
        make, model, rem = self.scraper.parse_query_slug("celica t23")
        self.assertEqual(make, "toyota")
        self.assertEqual(model, "celica")
        self.assertEqual(rem, ["t23"])

        # Make only
        make, model, rem = self.scraper.parse_query_slug("porsche")
        self.assertEqual(make, "porsche")
        self.assertIsNone(model)

        # Unrecognized generic word
        make, model, rem = self.scraper.parse_query_slug("camper")
        self.assertEqual(make, "camper")
        self.assertIsNone(model)

    def test_build_search_url_and_params(self):
        sf = SearchFilter(
            min_price=2000,
            max_price=8000,
            min_year=2000,
            max_year=2005,
            max_mileage_km=180000,
            fuel_type="gasoline",
            gearbox="manual",
            countries=["ES", "DE", "FR"],
            order_by="price_low_to_high",
        )
        url, params, rem = self.scraper.build_search_url_and_params("toyota celica", sf, page=2)

        self.assertEqual(url, "https://www.autoscout24.com/lst/toyota/celica")
        self.assertEqual(params["atype"], "C")
        self.assertEqual(params["sort"], "price")
        self.assertEqual(params["desc"], "0")
        self.assertEqual(params["pricefrom"], "2000")
        self.assertEqual(params["priceto"], "8000")
        self.assertEqual(params["fregfrom"], "2000")
        self.assertEqual(params["fregto"], "2005")
        self.assertEqual(params["kmto"], "180000")
        self.assertEqual(params["fuel"], "B")
        self.assertEqual(params["gear"], "M")
        self.assertEqual(params["page"], "2")
        # Check country mapping
        cy_parts = set(params["cy"].split(","))
        self.assertEqual(cy_parts, {"E", "D", "F"})

    def test_placeholder_prices(self):
        self.assertTrue(self.scraper.is_placeholder_price(1.0))
        self.assertTrue(self.scraper.is_placeholder_price(0.0))
        self.assertTrue(self.scraper.is_placeholder_price(1234.0))
        self.assertTrue(self.scraper.is_placeholder_price(9999.0))
        self.assertTrue(self.scraper.is_placeholder_price(99999.0))
        self.assertFalse(self.scraper.is_placeholder_price(4500.0))
        self.assertFalse(self.scraper.is_placeholder_price(12500.0))

    def test_bait_phrases_multilingual(self):
        # Spanish
        self.assertTrue(self.scraper.has_bait_phrases("Hola, el precio no es el del anuncio"))
        self.assertTrue(self.scraper.has_bait_phrases("Consultar precio por whatsapp"))
        # German
        self.assertTrue(self.scraper.has_bait_phrases("Preis auf Anfrage, bitte Angebot machen"))
        # English
        self.assertTrue(self.scraper.has_bait_phrases("Price on request. POA."))
        # French
        self.assertTrue(self.scraper.has_bait_phrases("Prix sur demande, faire offre"))
        # Italian
        self.assertTrue(self.scraper.has_bait_phrases("Prezzo su richiesta, trattativa riservata"))
        # Dutch
        self.assertTrue(self.scraper.has_bait_phrases("Prijs op aanvraag, bieden"))
        # Normal
        self.assertFalse(self.scraper.has_bait_phrases("Coche en perfecto estado con ITV recién pasada."))

    def test_multilingual_defect_flags(self):
        # German: Motorschaden & Ölverbrauch
        de_text = "Sehr hoher Ölverbrauch. Motorschaden! Fahrzeug ist nicht fahrbereit, nur für Export."
        de_flags = self.scraper.audit_defect_flags(de_text)
        self.assertTrue(any("ENGINE_DEFECT" in f for f in de_flags))
        self.assertTrue(any("NON_RUNNER" in f for f in de_flags))
        self.assertTrue(any("PARTS_ONLY" in f for f in de_flags))

        # Spanish: junta de culata & sin documentacion
        es_text = "Tiene la junta de culata tocada y está sin documentación. Para piezas."
        es_flags = self.scraper.audit_defect_flags(es_text)
        self.assertTrue(any("ENGINE_DEFECT" in f for f in es_flags))
        self.assertTrue(any("DOCUMENTATION_ISSUE" in f for f in es_flags))
        self.assertTrue(any("PARTS_ONLY" in f for f in es_flags))

        # French: boîte HS & accidenté
        fr_text = "Véhicule accidenté, boîte HS, vendu dans l'état pour pièces."
        fr_flags = self.scraper.audit_defect_flags(fr_text)
        self.assertTrue(any("ACCIDENT_DAMAGE" in f for f in fr_flags))
        self.assertTrue(any("GEARBOX_DEFECT" in f for f in fr_flags))
        self.assertTrue(any("PARTS_ONLY" in f for f in fr_flags))

        # Italian: motore fuso
        it_text = "Auto con motore fuso, non marciante, da riparare."
        it_flags = self.scraper.audit_defect_flags(it_text)
        self.assertTrue(any("ENGINE_DEFECT" in f for f in it_flags))
        self.assertTrue(any("NON_RUNNER" in f for f in it_flags))

        # Dutch: schadeauto
        nl_text = "Schadeauto met versnellingsbak defect, voor onderdelen."
        nl_flags = self.scraper.audit_defect_flags(nl_text)
        self.assertTrue(any("ACCIDENT_DAMAGE" in f for f in nl_flags))
        self.assertTrue(any("GEARBOX_DEFECT" in f for f in nl_flags))

        # English: blown engine
        en_text = "Blown engine and head gasket leak. Non runner, salvage spares or repair."
        en_flags = self.scraper.audit_defect_flags(en_text)
        self.assertTrue(any("ENGINE_DEFECT" in f for f in en_flags))
        self.assertTrue(any("NON_RUNNER" in f for f in en_flags))
        self.assertTrue(any("PARTS_ONLY" in f for f in en_flags))

    def test_extract_next_data(self):
        sample_json = {"props": {"pageProps": {"listings": [{"id": "abc-123"}]}}}
        html = f"""
        <!DOCTYPE html>
        <html>
        <head><title>AutoScout24</title></head>
        <body>
            <script id="__NEXT_DATA__" type="application/json">
            {json.dumps(sample_json)}
            </script>
        </body>
        </html>
        """
        extracted = self.scraper.extract_next_data(html)
        self.assertIsNotNone(extracted)
        self.assertEqual(extracted["props"]["pageProps"]["listings"][0]["id"], "abc-123")

        # Invalid html
        self.assertIsNone(self.scraper.extract_next_data("<html>No data</html>"))

    def test_listing_normalization(self):
        sample_item = {
            "id": "item-998877",
            "url": "/offers/mazda-mx-5-1-8-roadster-item-998877",
            "price": {
                "priceRaw": 4900,
                "priceFormatted": "€ 4.900",
            },
            "vehicle": {
                "make": "Mazda",
                "model": "MX-5",
                "modelVersionInput": "1.8i 16V Nardi Edition",
                "fuel": "Gasolina",
                "transmission": "manual",
                "mileageInKm": "165.000 km",
            },
            "location": {
                "countryCode": "ES",
                "city": "Madrid",
                "zip": "28001",
                "street": "Gran Vía",
                "latitude": 40.4200,
                "longitude": -3.7050,
            },
            "seller": {
                "type": "PrivateSeller",
                "id": "seller-123",
            },
            "vehicleDetails": [
                {"data": "165,000 km", "iconName": "mileage_odometer"},
                {"data": "Manual", "iconName": "gearbox"},
                {"data": "05/2001", "iconName": "calendar"},
                {"data": "Gasolina", "iconName": "gas_pump"},
                {"data": "103 kW (140 hp)", "iconName": "speedometer"},
            ],
            "images": [
                "https://prod.pictures.autoscout24.net/listing-images/img1.webp"
            ],
            "superDeal": {"isEligible": True},
        }

        sf = SearchFilter(latitude=40.385, longitude=-3.314)  # Loeches / Madrid
        listing = self.scraper._parse_listing_item(sample_item, sf, [])

        self.assertIsNotNone(listing)
        self.assertEqual(listing.id, "item-998877")
        self.assertEqual(listing.title, "Mazda MX-5 1.8i 16V Nardi Edition")
        self.assertEqual(listing.price, 4900.0)
        self.assertEqual(listing.total_price, 4900.0)
        self.assertEqual(listing.platform, Platform.AUTOSCOUT24)
        self.assertEqual(listing.url, "https://www.autoscout24.com/offers/mazda-mx-5-1-8-roadster-item-998877")
        self.assertIn("Madrid", listing.seller_location)
        self.assertIn("ES", listing.seller_location)
        self.assertIsNotNone(listing.distance_km)
        # Distance from Madrid center to Loeches is approx 33 km
        self.assertGreater(listing.distance_km, 25.0)
        self.assertLess(listing.distance_km, 45.0)

        # Specs inspection
        specs = listing.specs
        self.assertEqual(specs["make"], "Mazda")
        self.assertEqual(specs["model"], "MX-5")
        self.assertEqual(specs["year"], 2001)
        self.assertEqual(specs["mileage_km"], 165000)
        self.assertEqual(specs["power_kw"], 103)
        self.assertEqual(specs["power_hp"], 140)
        self.assertEqual(specs["fuel"], "Gasolina")
        self.assertEqual(specs["transmission"], "Manual")
        self.assertEqual(specs["seller_type"], "PrivateSeller")
        self.assertFalse(specs["is_placeholder_price"])
        self.assertTrue(specs["super_deal"])

        # Dict conversion
        d = listing.to_dict()
        self.assertEqual(d["platform"], "autoscout24")
        self.assertEqual(d["specs"]["mileage_km"], 165000)

    def test_client_negative_keywords_filtering(self):
        sample_item = {
            "id": "neg-test-1",
            "url": "/offers/test-1",
            "price": {"priceRaw": 3500},
            "vehicle": {
                "make": "Volkswagen",
                "model": "Golf",
                "modelVersionInput": "1.9 TDI Diesel Siniestrado",
                "fuel": "Diesel",
            },
            "location": {"countryCode": "ES", "city": "Valencia"},
            "vehicleDetails": [],
        }
        sf = SearchFilter(exclude_keywords=["diesel", "siniestrado"])
        result = self.scraper._parse_listing_item(sample_item, sf, [])
        self.assertIsNone(result)

    def test_geofencing_distance_filter(self):
        # Listing in Berlin (~1870 km from Madrid)
        berlin_item = {
            "id": "berlin-test",
            "url": "/offers/berlin-test",
            "price": {"priceRaw": 5000},
            "vehicle": {"make": "BMW", "model": "320"},
            "location": {
                "countryCode": "DE",
                "city": "Berlin",
                "latitude": 52.5200,
                "longitude": 13.4050,
            },
            "vehicleDetails": [],
        }

        # Filter max 100 km from Madrid
        sf_strict = SearchFilter(latitude=40.385, longitude=-3.314, max_distance_km=100.0)
        res_dropped = self.scraper._parse_listing_item(berlin_item, sf_strict, [])
        self.assertIsNone(res_dropped)

        # Filter max 2500 km from Madrid
        sf_wide = SearchFilter(latitude=40.385, longitude=-3.314, max_distance_km=2500.0)
        res_kept = self.scraper._parse_listing_item(berlin_item, sf_wide, [])
        self.assertIsNotNone(res_kept)
        self.assertGreater(res_kept.distance_km, 1800.0)

    @patch.object(AutoScout24Scraper, "get_listing_detail")
    def test_audit_listing_detail(self, mock_get_detail):
        mock_get_detail.return_value = {
            "description": "Coche con junta de culata rota.<br />No arranca, para reparar, solo para piezas.",
            "location": {
                "countryCode": "ES",
                "city": "Alcalá de Henares",
                "latitude": 40.4819,
                "longitude": -3.3635,
            },
        }

        listing = Listing(
            id="audit-123",
            title="Peugeot 206 1.4",
            price=600.0,
            platform=Platform.AUTOSCOUT24,
            url="https://www.autoscout24.com/offers/audit-123",
            specs={"forensic_flags": []},
        )

        audited = self.scraper.audit_listing_detail(listing)
        self.assertIn("junta de culata rota", audited.description)
        self.assertIn("ENGINE_DEFECT:junta de culata", audited.specs["forensic_flags"])
        self.assertIn("NON_RUNNER:no arranca", audited.specs["forensic_flags"])
        self.assertIn("NON_RUNNER:para reparar", audited.specs["forensic_flags"])
        self.assertIn("PARTS_ONLY:para piezas", audited.specs["forensic_flags"])
        self.assertEqual(audited.specs["latitude"], 40.4819)


if __name__ == "__main__":
    unittest.main()

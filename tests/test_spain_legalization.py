"""Unit tests for Spanish vehicle legalization and import cost calculator."""
import unittest

from src.models import Listing, Platform
from src.utils.spain_legalization import (
    SpainLegalizationCalculator,
    SpainLegalizationBreakdown,
    FEE_DGT_MATRICULACION_TASA_1_1,
    FEE_DGT_CAMBIO_TITULAR_TASA_4_1,
    FEE_FICHA_TECNICA_REDUCIDA,
    FEE_ITV_IMPORTACION_EXTRAORDINARIA,
    FEE_PLACAS_ACRILICAS_HOMOLOGADAS,
    FEE_IVTM_ROAD_TAX_ESTIMATE,
    FEE_RHD_LIGHTING_ADAPTATION,
)


class TestSpainLegalization(unittest.TestCase):

    def test_domestic_spain_car(self):
        listing = Listing(
            id="es-test-1",
            title="Mazda MX-5 NB",
            price=6500.0,
            seller_location="Madrid, ES, 28001",
            specs={"country_code": "ES"},
        )
        b = SpainLegalizationCalculator.calculate(listing)

        self.assertTrue(b.is_domestic)
        self.assertEqual(b.origin_country, "ES")
        self.assertEqual(b.transport_or_transit_cost, 0.0)
        self.assertEqual(b.ficha_reducida_cost, 0.0)
        self.assertEqual(b.itv_importacion_cost, 0.0)
        self.assertEqual(b.dgt_fee, FEE_DGT_CAMBIO_TITULAR_TASA_4_1)
        self.assertGreater(b.itp_or_transfer_tax, 0.0)
        self.assertEqual(b.rhd_adaptation_cost, 0.0)
        self.assertEqual(b.total_landed_spain_cost, round(listing.price + b.total_legalization_cost, 2))

        table = b.summary_table()
        self.assertIn("Domestic Spanish Vehicle", table)
        self.assertIn("DGT Ownership Transfer", table)

    def test_imported_german_car(self):
        listing = Listing(
            id="de-test-1",
            title="Subaru Impreza 1.5R",
            price=700.0,
            seller_location="Munich, DE, 80331",
            specs={"country_code": "DE"},
        )
        b = SpainLegalizationCalculator.calculate(listing)

        self.assertFalse(b.is_domestic)
        self.assertEqual(b.origin_country, "DE")
        self.assertEqual(b.transport_or_transit_cost, 850.0)
        self.assertEqual(b.ficha_reducida_cost, FEE_FICHA_TECNICA_REDUCIDA)
        self.assertEqual(b.itv_importacion_cost, FEE_ITV_IMPORTACION_EXTRAORDINARIA)
        self.assertEqual(b.dgt_fee, FEE_DGT_MATRICULACION_TASA_1_1)
        self.assertGreaterEqual(b.iedmt_modelo_576_cost, 150.0)
        self.assertEqual(b.ivtm_road_tax, FEE_IVTM_ROAD_TAX_ESTIMATE)
        self.assertEqual(b.physical_plates_cost, FEE_PLACAS_ACRILICAS_HOMOLOGADAS)
        self.assertEqual(b.rhd_adaptation_cost, 0.0)

        # Expected total is sum of all components
        expected_total = round(
            850.0 + FEE_FICHA_TECNICA_REDUCIDA + FEE_ITV_IMPORTACION_EXTRAORDINARIA +
            FEE_DGT_MATRICULACION_TASA_1_1 + b.iedmt_modelo_576_cost +
            FEE_IVTM_ROAD_TAX_ESTIMATE + FEE_PLACAS_ACRILICAS_HOMOLOGADAS,
            2
        )
        self.assertAlmostEqual(b.total_legalization_cost, expected_total, places=2)
        self.assertAlmostEqual(b.total_landed_spain_cost, round(listing.price + expected_total, 2), places=2)

        table = b.summary_table()
        self.assertIn("Spain Legalization Breakdown", table)
        self.assertIn("International Transport", table)
        self.assertIn("Ficha Técnica Reducida", table)
        self.assertIn("ITV Previa a Matriculación", table)
        self.assertIn("DGT Registration Fee", table)

    def test_imported_rhd_car_adaptation(self):
        listing = Listing(
            id="rhd-test-1",
            title="Honda S2000 RHD Facelift",
            price=19995.0,
            seller_location="Lokeren, BE, 9160",
            specs={"country_code": "BE"},
            description="Rechtslenker uit Engeland stuur aan de rechterkant",
        )
        b = SpainLegalizationCalculator.calculate(listing)

        self.assertFalse(b.is_domestic)
        self.assertEqual(b.origin_country, "BE")
        self.assertEqual(b.rhd_adaptation_cost, FEE_RHD_LIGHTING_ADAPTATION)

        table = b.summary_table()
        self.assertIn("RHD Headlight & Lighting Adaptation", table)

    def test_french_and_austrian_transports(self):
        l_fr = Listing(id="fr-1", title="Peugeot", price=1000.0, seller_location="Paris, FR", specs={"country_code": "FR"})
        b_fr = SpainLegalizationCalculator.calculate(l_fr)
        self.assertEqual(b_fr.transport_or_transit_cost, 650.0)

        l_at = Listing(id="at-1", title="Audi", price=1000.0, seller_location="Wien, AT", specs={"country_code": "AT"})
        b_at = SpainLegalizationCalculator.calculate(l_at)
        self.assertEqual(b_at.transport_or_transit_cost, 900.0)


if __name__ == "__main__":
    unittest.main()

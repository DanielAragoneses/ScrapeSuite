"""Unit tests for the Arbitrage Valuation Engine and Secondary Market Fee Calculator."""
import unittest

from src.utils.arbitrage_calc import (
    ArbitrageEvaluator,
    ArbitrageBreakdown,
    PLATFORM_FEE_SCHEDULES,
    PACKAGING_LOGISTICS_TIERS,
)


class TestArbitrageEvaluator(unittest.TestCase):

    def test_legacy_scope_unprofitable_trap(self):
        """Verify that obsolete digital scopes priced above real market values are flagged as traps."""
        # Siglent SDS 1202CNL+: Buy 225€, actual secondary market clearing price is ~190€
        breakdown = ArbitrageEvaluator.evaluate(
            item_name="Siglent SDS 1202CNL+ 200MHz",
            buy_price=225.0,
            conservative_resale_gross=190.0,
            resale_platform="ebay",
            weight_tier="medium_synth_testgear",
            inbound_shipping=6.50,
            description="Osciloscopio digital antiguo sin decodificación",
        )

        # Net profit should be negative (guaranteed loss)
        self.assertLess(breakdown.true_net_profit_eur, 0.0)
        self.assertEqual(breakdown.verdict, "UNPROFITABLE_TRAP")
        self.assertTrue(any("OBSOLETE_DIGITAL_SCOPE" in r for r in breakdown.risk_factors))

    def test_monochrome_tektronix_trap(self):
        """Verify Tektronix TDS 210 monochrome scope is flagged as an obsolete trap."""
        # TDS 210: Buy 180€, actual clearance ~130€
        breakdown = ArbitrageEvaluator.evaluate(
            item_name="Tektronix TDS 210 Oscilloscope",
            buy_price=180.0,
            conservative_resale_gross=130.0,
            resale_platform="ebay",
            weight_tier="medium_synth_testgear",
            inbound_shipping=6.00,
        )
        self.assertLess(breakdown.true_net_profit_eur, 0.0)
        self.assertEqual(breakdown.verdict, "UNPROFITABLE_TRAP")
        self.assertTrue(any("MONOCHROME_LEGACY_SCOPE_OBSOLETE" in r for r in breakdown.risk_factors))

    def test_heavy_vintage_audio_shipping_deduction(self):
        """Verify heavy vintage audio correctly applies 35€ packaging/shipping and 13.5% fees."""
        # Pioneer SX-450: Buy 150€, realistic unrestored resale ~210€
        breakdown = ArbitrageEvaluator.evaluate(
            item_name="Pioneer SX-450 Receptor Vintage",
            buy_price=150.0,
            conservative_resale_gross=210.0,
            resale_platform="ebay",
            weight_tier="heavy_vintage_audio",
            inbound_shipping=8.50,
            description="Guardado en armario 15W por canal",
        )

        # Fees: 210 * 13.5% = 28.35€
        self.assertAlmostEqual(breakdown.platform_fee_eur, 28.35, places=2)
        # Heavy shipping tier: 35.00€
        self.assertEqual(breakdown.packaging_and_shipping_eur, 35.00)
        # Total cost: 158.50 (acq) + 28.35 (fee) + 35 (ship) = 221.85€ -> Net loss of ~11.85€!
        self.assertLess(breakdown.true_net_profit_eur, 10.0)
        self.assertIn(breakdown.verdict, ("UNPROFITABLE_TRAP", "MODEST_GAIN_HIGH_EFFORT"))

    def test_viable_asymmetric_flip_promax(self):
        """Verify genuine asymmetric opportunities are recognized as viable."""
        # Promax CRT rejuvenator: Buy 60€, conservative resale 220€
        breakdown = ArbitrageEvaluator.evaluate(
            item_name="Promax RT-501B CRT Rejuvenator",
            buy_price=60.0,
            conservative_resale_gross=220.0,
            resale_platform="ebay",
            weight_tier="medium_synth_testgear",
            inbound_shipping=5.50,
            description="Comprobador y regenerador de tubos TRC arcade con adaptadores",
        )

        self.assertGreater(breakdown.true_net_profit_eur, 90.0)
        self.assertGreater(breakdown.true_roi_percent, 100.0)
        self.assertEqual(breakdown.verdict, "VIABLE_ASYMMETRIC_FLIP")

    def test_counterfeit_and_defect_risk_detection(self):
        """Verify automatic detection of high-risk items (Neumann replica, foam rot, bad meter)."""
        # Neumann TLM 103 replica risk
        b_mic = ArbitrageEvaluator.evaluate(
            item_name="Neumann TLM 103 Micrófono",
            buy_price=600.0,
            conservative_resale_gross=780.0,
            resale_platform="reverb",
            weight_tier="light_optics_mic",
        )
        self.assertTrue(any("COUNTERFEIT" in r for r in b_mic.risk_factors))

        # Leica CL with defective meter
        b_leica = ArbitrageEvaluator.evaluate(
            item_name="Leica CL",
            buy_price=390.0,
            conservative_resale_gross=420.0,
            resale_platform="ebay",
            weight_tier="light_optics_mic",
            description="El fotometro funciona de manera inestable",
        )
        self.assertTrue(any("METER_DEFECTIVE" in r for r in b_leica.risk_factors))
        self.assertEqual(b_leica.verdict, "UNPROFITABLE_TRAP")

        # RE20 foam rot risk
        b_re20 = ArbitrageEvaluator.evaluate(
            item_name="Electro-Voice RE20 Vintage",
            buy_price=425.0,
            conservative_resale_gross=520.0,
            resale_platform="reverb",
            weight_tier="light_optics_mic",
        )
        self.assertTrue(any("FOAM_ROT" in r for r in b_re20.risk_factors))

    def test_summary_table_formatting(self):
        breakdown = ArbitrageEvaluator.evaluate(
            item_name="Test Synth",
            buy_price=100.0,
            conservative_resale_gross=250.0,
            resale_platform="reverb",
            weight_tier="medium_synth_testgear",
        )
        table = breakdown.summary_table()
        self.assertIn("Arbitrage Financial Ledger", table)
        self.assertIn("TRUE NET PROFIT", table)
        self.assertIn("TRUE ROI", table)
        self.assertIn("Platform Fees", table)
        self.assertIn("Outbound Insured Courier", table)


if __name__ == "__main__":
    unittest.main()

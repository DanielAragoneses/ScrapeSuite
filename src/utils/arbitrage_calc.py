"""Arbitrage valuation engine and secondary market fee calculator for ScrapeSuite.

Implements rigorous accounting for real-world flipping economics:
- Inbound acquisition costs (shipping/pickup)
- Platform & payment processing fees (eBay ~13.5%, Reverb ~8.5%)
- Weight-tiered insured packaging and outbound logistics (12€ to 55€)
- Parts and refurbishment consumables
- Condition-adjusted conservative market clearing prices
- Risk factor auditing (foam rot, counterfeit vulnerability, obsolete legacy tech)
"""
import logging
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# Outbound packaging and insured courier shipping cost tiers
PACKAGING_LOGISTICS_TIERS: Dict[str, Tuple[float, str]] = {
    # (Cost in EUR, Description)
    "light_optics_mic": (12.00, "Small/Light (<2 kg): Bubble wrap, reinforced box, insured national/EU courier"),
    "medium_synth_testgear": (22.00, "Medium (2–6 kg): Double box, high-density foam corners, insured tracking"),
    "heavy_vintage_audio": (35.00, "Heavy/Fragile (7–15 kg): Heavy-duty double-wall box, 15 kg insured courier"),
    "bulky_crate": (55.00, "Bulky/Crate (>15 kg): Wood-reinforced crate, pallet freight / specialty fragile transport"),
}

# Platform fee schedules (Final Value Fee + regulatory/payment processing fee)
PLATFORM_FEE_SCHEDULES: Dict[str, float] = {
    "ebay": 13.5,     # Standard eBay electronics category fee + managed payments
    "reverb": 8.5,    # Reverb 5% selling fee + 3.19% + 0.49€ payment processing (~8.5%)
    "wallapop": 0.0,  # Peer-to-peer cash on delivery / local handover
    "forum": 0.0,     # Specialized collector forum / direct wire transfer
}

# Known legacy tech traps and counterfeit-prone equipment heuristics
KNOWN_TRAP_HEURISTICS: Dict[str, List[str]] = {
    "tds 210": ["MONOCHROME_LEGACY_SCOPE_OBSOLETE", "Priced above market; modern 12-bit Rigol/Siglent scopes retail for 300-360€ with warranty"],
    "tds 220": ["MONOCHROME_LEGACY_SCOPE_OBSOLETE", "Late 90s monochrome LCD with tiny 2.5k sample memory; real clearance is 100-140€"],
    "sds 1202cnl": ["OBSOLETE_DIGITAL_SCOPE", "Older generation without web interface or serial decoding; market clearance is 160-200€"],
    "tlm 103": ["COUNTERFEIT_REPLICA_RISK", "Heavily counterfeited on Spanish classifieds; requires internal capsule PCB inspection"],
    "re20": ["ACOUSTIC_FOAM_ROT_RISK", "Vintage 1990s units suffer from disintegrated internal acoustic foam coating the capsule"],
    "altix": ["PROPRIETARY_MOUNT_ILLIQUID", "Altix bayonet mount is not M42; requires rare adapter, reducing digital mirrorless buyer demand"],
    "pioneer sx-450": ["ENTRY_LEVEL_MINIMAL_SPREAD", "15W entry model with vinyl wrap; 400€+ tier is reserved for SX-750+ or recapped units"],
    "leica cl": ["METER_FAILURE_PENALTY", "Unstable or inoperative CdS meter drops body value to 350-420€, eliminating profit margin"],
}


@dataclass
class ArbitrageBreakdown:
    """Rigorous financial ledger for a secondary market arbitrage flip."""
    item_name: str
    buy_price: float
    inbound_shipping: float
    total_acquisition_cost: float
    conservative_resale_gross: float
    resale_platform: str
    platform_fee_percent: float
    platform_fee_eur: float
    packaging_and_shipping_eur: float
    packaging_tier_desc: str
    refurbishment_and_parts_cost: float
    true_net_profit_eur: float
    true_roi_percent: float
    margin_of_safety_eur: float
    risk_factors: List[str] = field(default_factory=list)
    verdict: str = "VIABLE_ASYMMETRIC_FLIP"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def summary_table(self) -> str:
        """Render a clean, audit-compliant financial ledger."""
        return (
            f"Arbitrage Financial Ledger: {self.item_name}\n"
            f"  [Acquisition]\n"
            f"  - Item Buy Price:                     {self.buy_price:7.2f} €\n"
            f"  - Inbound Shipping & Insurance:        {self.inbound_shipping:7.2f} €\n"
            f"    -> Total Capital Deployed:          {self.total_acquisition_cost:7.2f} €\n"
            f"  [Resale & Deductions ({self.resale_platform.upper()})]\n"
            f"  + Conservative Resale Realized:       {self.conservative_resale_gross:7.2f} €\n"
            f"  - Platform Fees ({self.platform_fee_percent:.1f}%):              {self.platform_fee_eur:7.2f} €\n"
            f"  - Outbound Insured Courier & Pack:    {self.packaging_and_shipping_eur:7.2f} €\n"
            f"  - Consumables / Refurbishment Parts:   {self.refurbishment_and_parts_cost:7.2f} €\n"
            f"  ---------------------------------------------------\n"
            f"  = TRUE NET PROFIT:                    {self.true_net_profit_eur:7.2f} €\n"
            f"  = TRUE ROI:                           {self.true_roi_percent:7.1f} %\n"
            f"  = Verdict:                            [{self.verdict}]\n"
            f"  = Identified Risks:                   {', '.join(self.risk_factors) if self.risk_factors else 'None'}"
        )


class ArbitrageEvaluator:
    """Evaluates potential flips using real-world marketplace accounting."""

    @classmethod
    def audit_risk_factors(cls, item_name: str, description: str = "") -> List[str]:
        """Scan title and description for known obsolescence, counterfeit, and mechanical traps."""
        corpus = f"{item_name} {description}".lower()
        flags: List[str] = []

        for trigger, (flag, explanation) in KNOWN_TRAP_HEURISTICS.items():
            if trigger in corpus:
                flags.append(f"{flag}: {explanation}")

        # Check for unserviced / untested disclosures
        if "para piezas" in corpus or "no probado" in corpus or "no puedo comprobar" in corpus:
            flags.append("UNTESTED_OR_PARTS_DISCLOSURE: Requires bench testing and possible repair")
        if "fuelle" in corpus and ("daño" in corpus or "roto" in corpus or "grieta" in corpus):
            flags.append("BELLOWS_PINHOLE_RISK: Medium-format light leaks destroy film value")
        if "fotometro" in corpus and ("inestable" in corpus or "no funciona" in corpus):
            flags.append("METER_DEFECTIVE: Inoperative light meter eliminates collector premium")

        return flags

    @classmethod
    def evaluate(
        cls,
        item_name: str,
        buy_price: float,
        conservative_resale_gross: float,
        resale_platform: str = "ebay",
        weight_tier: str = "medium_synth_testgear",
        inbound_shipping: float = 5.0,
        refurbishment_and_parts_cost: float = 0.0,
        description: str = "",
        custom_risk_flags: Optional[List[str]] = None,
    ) -> ArbitrageBreakdown:
        """Calculate complete line-by-line financial reality of an arbitrage flip."""
        plat_key = resale_platform.strip().lower()
        fee_pct = PLATFORM_FEE_SCHEDULES.get(plat_key, 13.5)
        fee_eur = round(conservative_resale_gross * (fee_pct / 100.0), 2)

        tier_info = PACKAGING_LOGISTICS_TIERS.get(
            weight_tier,
            PACKAGING_LOGISTICS_TIERS["medium_synth_testgear"]
        )
        shipping_out_eur, tier_desc = tier_info

        total_acquisition = round(buy_price + inbound_shipping, 2)
        total_costs = round(
            total_acquisition + fee_eur + shipping_out_eur + refurbishment_and_parts_cost,
            2
        )

        true_net_profit = round(conservative_resale_gross - total_costs, 2)
        invested_capital = max(total_acquisition + refurbishment_and_parts_cost, 1.0)
        true_roi = round((true_net_profit / invested_capital) * 100.0, 1)

        # Margin of safety (difference between gross resale and total costs)
        margin_of_safety = max(0.0, true_net_profit)

        # Audit risk flags
        risk_flags = custom_risk_flags or []
        detected_flags = cls.audit_risk_factors(item_name, description)
        for df in detected_flags:
            if df not in risk_flags:
                risk_flags.append(df)

        # Verdict classification
        has_fatal_trap = any(
            "OBSOLETE" in f or "COUNTERFEIT" in f or "METER_DEFECTIVE" in f
            for f in risk_flags
        )

        if true_net_profit <= 0.0 or has_fatal_trap and true_net_profit < 50.0:
            verdict = "UNPROFITABLE_TRAP"
        elif has_fatal_trap or any("FOAM_ROT" in f or "BELLOWS" in f for f in risk_flags):
            verdict = "HIGH_RISK_GAMBLE"
        elif true_net_profit >= 90.0 and true_roi >= 40.0:
            verdict = "VIABLE_ASYMMETRIC_FLIP"
        else:
            verdict = "MODEST_GAIN_HIGH_EFFORT"

        return ArbitrageBreakdown(
            item_name=item_name,
            buy_price=buy_price,
            inbound_shipping=inbound_shipping,
            total_acquisition_cost=total_acquisition,
            conservative_resale_gross=conservative_resale_gross,
            resale_platform=resale_platform,
            platform_fee_percent=fee_pct,
            platform_fee_eur=fee_eur,
            packaging_and_shipping_eur=shipping_out_eur,
            packaging_tier_desc=tier_desc,
            refurbishment_and_parts_cost=refurbishment_and_parts_cost,
            true_net_profit_eur=true_net_profit,
            true_roi_percent=true_roi,
            margin_of_safety_eur=margin_of_safety,
            risk_factors=risk_flags,
            verdict=verdict,
        )

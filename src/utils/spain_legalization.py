"""Spanish vehicle import and legalization cost calculator for ScrapeSuite.

Calculates the exact line-by-line administrative, fiscal, technical, and logistical
expenses required to legalize and register an imported European vehicle in Spain (DGT,
AEAT Hacienda, ITV, and Ayuntamiento).
"""
import logging
import re
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, Tuple

from src.models import Listing

logger = logging.getLogger(__name__)

# Standard statutory administrative & technical fees in Spain (2025/2026 rates)
FEE_DGT_MATRICULACION_TASA_1_1 = 99.77  # DGT vehicle initial registration fee
FEE_DGT_CAMBIO_TITULAR_TASA_4_1 = 55.70  # DGT domestic change of ownership fee
FEE_FICHA_TECNICA_REDUCIDA = 90.00       # Certificate of Conformity / Ficha reducida from chartered engineer
FEE_ITV_IMPORTACION_EXTRAORDINARIA = 150.00  # Extraordinary import inspection at Spanish ITV
FEE_PLACAS_ACRILICAS_HOMOLOGADAS = 35.00     # Pair of approved acrylic registration plates
FEE_IVTM_ROAD_TAX_ESTIMATE = 140.00          # Municipal road tax (Impuesto de Circulación) average 12-16 CVF
FEE_RHD_LIGHTING_ADAPTATION = 250.00         # Headlamp beam adjustment/replacement + rear fog relocation for RHD

# Logistics & Flatbed transport matrix to Spain based on country of origin
COUNTRY_TRANSPORT_COSTS: Dict[str, float] = {
    "ES": 0.0,       # Domestic Spain
    "FR": 650.0,     # France (Bordeaux/Paris/Lyon to Spain)
    "DE": 850.0,     # Germany (Frankfurt/Stuttgart/Munich/NRW)
    "BE": 850.0,     # Belgium (Brussels/Antwerp)
    "NL": 850.0,     # Netherlands (Amsterdam/Rotterdam/Utrecht)
    "AT": 900.0,     # Austria (Vienna/Salzburg/Tyrol)
    "IT": 900.0,     # Italy (Northern/Central Italy)
    "LU": 800.0,     # Luxembourg
    "CH": 950.0,     # Switzerland
    "PL": 1100.0,    # Poland
    "CZ": 1000.0,    # Czech Republic
    "SE": 1300.0,    # Sweden
    "UK": 1100.0,    # United Kingdom
}

# Major Spanish city keywords to identify domestic inventory
SPANISH_LOCATION_KEYWORDS = {
    "spain", "españa", "madrid", "barcelona", "valencia", "sevilla", "zaragoza",
    "málaga", "malaga", "murcia", "palma", "bilbao", "alicante", "córdoba",
    "cordoba", "valladolid", "vigo", "gijón", "gijon", "granada", "coruña",
    "vitoria", "elche", "oviedo", "badalona", "cartagena", "terrassa", "jerez",
    "sabadell", "alcalá", "alcala", "fuenlabrada", "leganés", "leganes", "getafe",
    "burgos", "albacete", "santander", "castellón", "castellon", "logroño",
    "badajoz", "salamanca", "huelva", "marbella", "lleida", "tarragona",
    "dos hermanas", "parla", "torrejón", "torrejon", "mataró", "algeciras",
    "jaén", "jaen", "ourense", "reus", "telde", "barakaldo", "lugo", "girona",
    "santiago", "cáceres", "caceres", "lorca", "las rozas", "coslada", "orihuela",
    "talavera", "el puerto", "cornellà", "majadahonda", "guadalajara", "toledo",
    "pontevedra", "palencia", "motril", "mijas", "benifaió", "benifaio"
}


@dataclass
class SpainLegalizationBreakdown:
    """Itemized costs to legalize, register, and import a vehicle in Spain."""
    is_domestic: bool
    origin_country: str
    transport_or_transit_cost: float
    ficha_reducida_cost: float
    itv_importacion_cost: float
    dgt_fee: float
    iedmt_modelo_576_cost: float
    itp_or_transfer_tax: float
    ivtm_road_tax: float
    physical_plates_cost: float
    rhd_adaptation_cost: float
    gestoria_fee: float
    total_legalization_cost: float
    vehicle_price: float
    total_landed_spain_cost: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def summary_table(self) -> str:
        """Render a clean, formatted ASCII table of the legalization expenses."""
        if self.is_domestic:
            return (
                f"Domestic Spanish Vehicle (No Import Required):\n"
                f"  - DGT Ownership Transfer (Tasa 4.1):  {self.dgt_fee:6.2f} €\n"
                f"  - Regional Transfer Tax (ITP Mod 620): {self.itp_or_transfer_tax:6.2f} €\n"
                f"  --------------------------------------------------\n"
                f"  Total Registration Transfer in Spain: {self.total_legalization_cost:6.2f} €\n"
                f"  Total All-In Investment Landed:       {self.total_landed_spain_cost:6.2f} €"
            )

        rhd_line = (
            f"  - RHD Headlight & Lighting Adaptation: {self.rhd_adaptation_cost:6.2f} €\n"
            if self.rhd_adaptation_cost > 0 else ""
        )

        return (
            f"Spain Legalization Breakdown (Import from {self.origin_country}):\n"
            f"  - International Transport / Transit:    {self.transport_or_transit_cost:6.2f} €\n"
            f"  - Ficha Técnica Reducida (Engineer COC):{self.ficha_reducida_cost:6.2f} €\n"
            f"  - ITV Previa a Matriculación (Import):  {self.itv_importacion_cost:6.2f} €\n"
            f"  - DGT Registration Fee (Tasa 1.1):      {self.dgt_fee:6.2f} €\n"
            f"  - AEAT Hacienda Registration (Mod 576): {self.iedmt_modelo_576_cost:6.2f} €\n"
            f"  - Municipal Road Tax (IVTM Prorated):   {self.ivtm_road_tax:6.2f} €\n"
            f"  - Physical Acrylic License Plates:      {self.physical_plates_cost:6.2f} €\n"
            f"{rhd_line}"
            f"  --------------------------------------------------\n"
            f"  Total Cost to Legalize & Register in Spain: {self.total_legalization_cost:6.2f} €\n"
            f"  Total All-In Landed Cost (Car + Legal):    {self.total_landed_spain_cost:6.2f} €"
        )


class SpainLegalizationCalculator:
    """Calculates administrative, fiscal, and logistical costs for vehicle legalization in Spain."""

    @classmethod
    def is_car_in_spain(cls, listing: Listing) -> bool:
        """Determine whether a vehicle is already domestic to Spain."""
        specs = listing.specs or {}
        country_code = str(specs.get("country_code", "")).strip().upper()
        if country_code in ("ES", "E"):
            return True

        location_text = f"{listing.seller_location or ''} {listing.url}".lower()
        if "autoscout24.es" in location_text:
            # Check country code in specs or url
            if ", es" in location_text or " es," in location_text or "españa" in location_text or "spain" in location_text:
                return True

        for city in SPANISH_LOCATION_KEYWORDS:
            if re.search(r"\b" + re.escape(city) + r"\b", location_text):
                return True

        return False

    @classmethod
    def detect_origin_country(cls, listing: Listing) -> str:
        """Extract or infer the two-letter ISO country code of vehicle location."""
        specs = listing.specs or {}
        country_code = str(specs.get("country_code", "")).strip().upper()
        if country_code:
            # Map single letter codes (D -> DE, F -> FR, etc.)
            SINGLE_MAP = {"D": "DE", "F": "FR", "I": "IT", "E": "ES", "B": "BE", "A": "AT", "L": "LU"}
            return SINGLE_MAP.get(country_code, country_code)

        loc = (listing.seller_location or "").lower()
        if any(w in loc for w in ("germany", "deutschland", "de")):
            return "DE"
        if any(w in loc for w in ("france", "fr")):
            return "FR"
        if any(w in loc for w in ("netherlands", "nederland", "nl")):
            return "NL"
        if any(w in loc for w in ("belgium", "belgique", "be")):
            return "BE"
        if any(w in loc for w in ("austria", "österreich", "at")):
            return "AT"
        if any(w in loc for w in ("italy", "italia", "it")):
            return "IT"
        if any(w in loc for w in ("spain", "españa", "es")):
            return "ES"

        return "DE"  # Central European default

    @classmethod
    def is_right_hand_drive(cls, listing: Listing) -> bool:
        """Detect whether a vehicle is Right-Hand Drive (RHD)."""
        text = f"{listing.title} {listing.description} {listing.specs.get('version', '')}".lower()
        if "rhd" in text or "rechtslenker" in text or "rechtlenker" in text or "stuur aan de rechterkant" in text:
            return True
        if "right hand drive" in text or "uk import" in text or "england import" in text:
            return True
        return False

    @classmethod
    def estimate_iedmt_tax(cls, listing: Listing) -> float:
        """Estimate AEAT Hacienda Registration Tax (Modelo 576).

        Calculated using Spanish Tax Agency tables (Orden HFP) applying age depreciation:
        Vehicles >10-15 years old are depreciated to 10%-13% of base value.
        Older sports cars typically fall into the 9.75% (160-199 g/km) or 14.75% (>=200 g/km) bracket.
        """
        base_price = max(listing.price, 1000.0)
        # Residual fiscal tax base for older vehicles under Hacienda tables is approx 10-13%
        # of original new MSRP, which roughly correlates to ~1,500€ - 2,500€ fiscal base
        fiscal_base = min(base_price, 2500.0)
        # Most 90s/2000s sports cars emit >= 160 g/km CO2 (rate: 9.75% to 14.75%)
        tax_rate = 0.0975 if base_price < 2500.0 else 0.1475
        iedmt = round(fiscal_base * tax_rate, 2)
        return max(150.0, min(iedmt, 420.0))

    @classmethod
    def calculate(
        cls,
        listing: Listing,
        force_rhd: Optional[bool] = None,
        use_gestoria: bool = False
    ) -> SpainLegalizationBreakdown:
        """Calculate complete line-by-line expenses to have the car registered and legal in Spain."""
        is_domestic = cls.is_car_in_spain(listing)
        price = float(listing.price)

        if is_domestic:
            dgt_fee = FEE_DGT_CAMBIO_TITULAR_TASA_4_1
            # Regional ITP tax in Spain (Modelo 620): 4% to 6%
            itp = round(max(price * 0.04, 80.0), 2)
            total_legal = round(dgt_fee + itp, 2)
            return SpainLegalizationBreakdown(
                is_domestic=True,
                origin_country="ES",
                transport_or_transit_cost=0.0,
                ficha_reducida_cost=0.0,
                itv_importacion_cost=0.0,
                dgt_fee=dgt_fee,
                iedmt_modelo_576_cost=0.0,
                itp_or_transfer_tax=itp,
                ivtm_road_tax=0.0,  # Already registered locally, paid annually by owner
                physical_plates_cost=0.0,
                rhd_adaptation_cost=0.0,
                gestoria_fee=0.0,
                total_legalization_cost=total_legal,
                vehicle_price=price,
                total_landed_spain_cost=round(price + total_legal, 2),
            )

        # Vehicle is imported from outside Spain
        country = cls.detect_origin_country(listing)
        transport_cost = COUNTRY_TRANSPORT_COSTS.get(country, 850.0)

        # Special location handling (e.g. Sicily island)
        loc_text = (listing.seller_location or "").lower()
        if "sicilia" in loc_text or "sicily" in loc_text or "catania" in loc_text or "nicolosi" in loc_text:
            transport_cost += 200.0  # Ferry surcharge

        # Check RHD
        is_rhd = force_rhd if force_rhd is not None else cls.is_right_hand_drive(listing)
        rhd_cost = FEE_RHD_LIGHTING_ADAPTATION if is_rhd else 0.0

        ficha_cost = FEE_FICHA_TECNICA_REDUCIDA
        itv_cost = FEE_ITV_IMPORTACION_EXTRAORDINARIA
        dgt_fee = FEE_DGT_MATRICULACION_TASA_1_1
        iedmt = cls.estimate_iedmt_tax(listing)
        ivtm = FEE_IVTM_ROAD_TAX_ESTIMATE
        plates = FEE_PLACAS_ACRILICAS_HOMOLOGADAS
        gestoria = 150.0 if use_gestoria else 0.0

        total_legalization = round(
            transport_cost
            + ficha_cost
            + itv_cost
            + dgt_fee
            + iedmt
            + ivtm
            + plates
            + rhd_cost
            + gestoria,
            2
        )

        total_landed = round(price + total_legalization, 2)

        return SpainLegalizationBreakdown(
            is_domestic=False,
            origin_country=country,
            transport_or_transit_cost=transport_cost,
            ficha_reducida_cost=ficha_cost,
            itv_importacion_cost=itv_cost,
            dgt_fee=dgt_fee,
            iedmt_modelo_576_cost=iedmt,
            itp_or_transfer_tax=0.0,
            ivtm_road_tax=ivtm,
            physical_plates_cost=plates,
            rhd_adaptation_cost=rhd_cost,
            gestoria_fee=gestoria,
            total_legalization_cost=total_legalization,
            vehicle_price=price,
            total_landed_spain_cost=total_landed,
        )

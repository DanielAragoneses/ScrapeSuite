"""Forensic visual pipeline for inspecting top vehicle listings via Gemini 2.5 Flash."""
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Callable, Tuple

from src.models import Listing
from src.vision.client import OpenRouterVisionClient
from src.utils.spain_legalization import SpainLegalizationCalculator

logger = logging.getLogger(__name__)

# Patterns in visual report indicating structural/mechanical red flags
VISUAL_RED_FLAG_PATTERNS: Dict[str, List[str]] = {
    "RUST_CORROSION": [
        "rust bubbling", "rust perforation", "heavy rust", "corrosion", "rust staining",
        "surface rust on panel", "chassis rust", "sills rusted", "wheel arch rust",
    ],
    "PANEL_ALIGNMENT_COLLISION": [
        "uneven shut-line", "uneven gap", "misaligned panel", "panel mismatch",
        "color mismatch", "overspray", "prior body repair", "frame damage", "wrinkled apron",
    ],
    "WARNING_LIGHTS": [
        "check engine", "cel illuminated", "warning light", "abs light", "airbag light",
        "battery light", "oil pressure light",
    ],
    "FLUID_LEAK": [
        "fluid drip", "damp spot underneath", "oil leak", "coolant stain", "fluid puddle",
    ],
    "COSMETIC_DAMAGE": [
        "clearcoat failure", "clearcoat peeling", "large dent", "deep scratch",
        "cracked windshield", "hazy headlight", "moisture inside lens",
    ],
    "INTERIOR_WEAR": [
        "upholstery tear", "dashboard crack", "missing trim", "sagging headliner",
        "pedal rubber worn through", "bolster tear",
    ],
}


@dataclass
class VisualInspectionResult:
    """Outcome of the forensic visual pipeline for candidate vehicle listings."""
    inspected_listings: List[Listing] = field(default_factory=list)
    curated_top_listings: List[Listing] = field(default_factory=list)
    discarded_listings: List[Tuple[Listing, str]] = field(default_factory=list)
    raw_reports: Dict[str, str] = field(default_factory=dict)


class ForensicVisualPipeline:
    """Orchestrates top-10 visual inspection and top-5 ranking."""

    def __init__(
        self,
        vision_client: Optional[OpenRouterVisionClient] = None,
        max_images_per_listing: int = 10,
        use_base64: bool = True,
    ):
        self.vision_client = vision_client or OpenRouterVisionClient()
        self.max_images_per_listing = min(max_images_per_listing, 10)
        self.use_base64 = use_base64

    @staticmethod
    def audit_visual_text_for_flags(report_text: str) -> List[str]:
        """Scan Gemini 2.5 Flash visual inspection text for red flags and anomalies."""
        if not report_text:
            return []

        lower = report_text.lower()
        flags: List[str] = []

        for category, patterns in VISUAL_RED_FLAG_PATTERNS.items():
            for p in patterns:
                if p in lower:
                    flags.append(f"{category}:{p}")
                    break  # One tag per category is sufficient

        return flags

    @staticmethod
    def compute_visual_score(listing: Listing) -> float:
        """Calculate a visual health score (0.0 to 10.0) based on detected visual flags."""
        flags = listing.specs.get("visual_flags", [])
        score = 10.0

        for f in flags:
            if "RUST_CORROSION" in f:
                score -= 3.0
            elif "PANEL_ALIGNMENT_COLLISION" in f:
                score -= 2.5
            elif "WARNING_LIGHTS" in f:
                score -= 2.0
            elif "FLUID_LEAK" in f:
                score -= 2.0
            elif "COSMETIC_DAMAGE" in f:
                score -= 1.0
            elif "INTERIOR_WEAR" in f:
                score -= 0.5

        return max(0.0, min(10.0, score))

    def run(
        self,
        listings: List[Listing],
        top_n_candidates: int = 10,
        top_n_final: int = 5,
        scraper_detail_fetcher: Optional[Callable[[Listing], Listing]] = None,
        progress_callback: Optional[Callable[[int, int, Listing, str], None]] = None,
    ) -> VisualInspectionResult:
        """Execute the forensic vision pipeline over the top N candidate listings.

        1. Selects the top `top_n_candidates` listings (default 10).
        2. Retrieves full gallery images (via scraper_detail_fetcher if needed).
        3. Sends each vehicle's photo set to Gemini 2.5 Flash via OpenRouter.
        4. Ingests and parses visual reports, flagging defects.
        5. Re-evaluates, discards severely compromised listings, and ranks the Top 5.
        """
        result = VisualInspectionResult()

        if not listings:
            return result

        # 1. Filter obvious placeholder prices if any leaked through
        candidates = [
            it for it in listings
            if not it.specs.get("is_placeholder_price", False) and it.price > 10.0
        ]
        if not candidates:
            candidates = listings

        # Select top N candidates (up to 10)
        selected_candidates = candidates[:top_n_candidates]
        total_to_inspect = len(selected_candidates)

        logger.info(f"Starting forensic visual inspection for top {total_to_inspect} candidate listings...")

        for idx, listing in enumerate(selected_candidates, 1):
            if progress_callback:
                progress_callback(idx, total_to_inspect, listing, "fetching_images")

            # Ensure high-res gallery images are populated from listing detail page
            if scraper_detail_fetcher:
                try:
                    listing = scraper_detail_fetcher(listing)
                except Exception as e:
                    logger.warning(f"Failed to fetch detail gallery images for {listing.id}: {e}")

            images = listing.specs.get("images", [])
            if not images and listing.raw_data.get("images"):
                images = listing.raw_data.get("images", [])
                listing.specs["images"] = images
            # Fallback if no images found
            if not images:
                logger.info(f"Listing {listing.id} ({listing.title}) has no images available. Skipping visual check.")
                listing.specs["visual_inspection"] = "No images available for visual inspection."
                listing.specs["visual_flags"] = []
                listing.specs["visual_score"] = 5.0
                result.inspected_listings.append(listing)
                continue

            # 2. Call Gemini 2.5 Flash via OpenRouter
            if progress_callback:
                progress_callback(idx, total_to_inspect, listing, "calling_gemini_vision")

            try:
                report = self.vision_client.inspect_listing_images(
                    image_urls=images,
                    max_images=self.max_images_per_listing,
                    use_base64=self.use_base64,
                )
            except Exception as e:
                logger.error(f"Visual inspection failed for {listing.id}: {e}")
                report = f"Visual inspection error: {e}"

            listing.specs["images_inspected_count"] = min(len(images), self.max_images_per_listing)
            listing.specs["total_images_available"] = len(images)
            # Attach visual data to listing
            listing.specs["visual_inspection"] = report
            visual_flags = self.audit_visual_text_for_flags(report)
            listing.specs["visual_flags"] = visual_flags
            visual_score = self.compute_visual_score(listing)
            listing.specs["visual_score"] = visual_score
            # Attach Spain legalization and import fiscal breakdown
            legal_breakdown = SpainLegalizationCalculator.calculate(listing)
            listing.specs["spain_legalization"] = legal_breakdown.to_dict()
            listing.specs["total_spain_legal_cost"] = legal_breakdown.total_landed_spain_cost
            listing.specs["spain_legalization_table"] = legal_breakdown.summary_table()

            result.inspected_listings.append(listing)
            result.raw_reports[listing.id] = report

        # 3. Discard & Re-rank
        # Identify non-viable cars (e.g. catastrophic crash or heavy chassis rust)
        accepted: List[Listing] = []
        for it in result.inspected_listings:
            v_score = it.specs.get("visual_score", 10.0)
            flags = it.specs.get("visual_flags", [])

            # Example critical discard condition: collision panel mismatch + heavy rust
            has_heavy_rust = any("RUST_CORROSION" in f for f in flags)
            has_frame_mismatch = any("PANEL_ALIGNMENT_COLLISION" in f for f in flags)

            if has_heavy_rust and has_frame_mismatch and v_score < 4.0:
                result.discarded_listings.append((
                    it,
                    f"Discarded: Critical structural rust combined with severe panel/frame misalignment (Score: {v_score}/10)"
                ))
            else:
                accepted.append(it)

        # Ensure we maintain at least top_n_final (default 5)
        # If discards drop us below top_n_final, restore least-damaged candidates
        if len(accepted) < top_n_final and result.discarded_listings:
            needed = top_n_final - len(accepted)
            restored = result.discarded_listings[:needed]
            for it, _ in restored:
                accepted.append(it)
            result.discarded_listings = result.discarded_listings[needed:]

        # If original candidate pool was smaller than top_n_final, add remaining listings from search
        if len(accepted) < top_n_final:
            for extra in candidates[top_n_candidates:]:
                if len(accepted) >= top_n_final:
                    break
                if extra not in accepted:
                    accepted.append(extra)

        # 4. Final Ranking: Balance price attractiveness, visual health score, and mechanical completeness
        # Lower price is better, higher visual score is better
        # Composite rank score: lower is better
        def ranking_key(item: Listing) -> Tuple[float, float]:
            # Normalize price and invert visual score
            p = item.price if item.price > 0 else 999999.0
            v_score = item.specs.get("visual_score", 7.0)
            # Give high weight to price, but penalize bad visual scores
            penalty = (10.0 - v_score) * (p * 0.05)
            effective_score = p + penalty
            return effective_score, p

        sorted_curated = sorted(accepted, key=ranking_key)
        result.curated_top_listings = sorted_curated[:max(top_n_final, 5)]

        return result

"""Unit tests for OpenRouter Gemini 2.5 Flash automotive vision tool and pipeline."""
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from src.models import Listing, Platform
from src.vision.client import (
    OpenRouterVisionClient,
    FORENSIC_INSPECTOR_PROMPT,
    load_env_file,
)
from src.vision.pipeline import (
    ForensicVisualPipeline,
    VisualInspectionResult,
)


class TestVisionClientAndPipeline(unittest.TestCase):

    def test_forensic_prompt_mandate(self):
        """Verify the exact prompt breakdown required by the appraisal protocol is present."""
        self.assertIn("You are an expert automotive forensic inspector documenting vehicle condition", FORENSIC_INSPECTOR_PROMPT)
        self.assertIn("### IMAGE [Index]: [Camera Angle & Viewpoint]", FORENSIC_INSPECTOR_PROMPT)
        self.assertIn("- **Frame & Environment:**", FORENSIC_INSPECTOR_PROMPT)
        self.assertIn("- **Visible Panels & Alignment:**", FORENSIC_INSPECTOR_PROMPT)
        self.assertIn("- **Paint & Body Condition:**", FORENSIC_INSPECTOR_PROMPT)
        self.assertIn("- **Glass, Trim & Lighting:**", FORENSIC_INSPECTOR_PROMPT)
        self.assertIn("- **Wheels, Brakes & Tires:**", FORENSIC_INSPECTOR_PROMPT)
        self.assertIn("- **Interior & Cabin (if visible):**", FORENSIC_INSPECTOR_PROMPT)
        self.assertIn("- **Instrument Cluster & Electronics (if visible):**", FORENSIC_INSPECTOR_PROMPT)
        self.assertIn("- **Text, Badging & Markings:**", FORENSIC_INSPECTOR_PROMPT)
        self.assertIn("- **Micro-Anomalies & Red Flags:**", FORENSIC_INSPECTOR_PROMPT)
        self.assertIn("Be clinically descriptive, objective, and precise", FORENSIC_INSPECTOR_PROMPT)

    def test_client_init_and_key_resolution(self):
        # Explicit key
        client = OpenRouterVisionClient(api_key="test_sk_12345")
        self.assertTrue(client.is_configured)
        self.assertEqual(client.api_key, "test_sk_12345")
        self.assertEqual(client.model, "google/gemini-2.5-flash")

        # Env variable key
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "env_key_67890"}):
            client_env = OpenRouterVisionClient()
            self.assertTrue(client_env.is_configured)
            self.assertEqual(client_env.api_key, "env_key_67890")

    def test_build_multimodal_message(self):
        client = OpenRouterVisionClient(api_key="test_key")
        urls = [
            "https://images.example.com/front.jpg",
            "https://images.example.com/side.jpg",
        ]
        msg = client.build_multimodal_message(urls, use_base64=False, max_images=5)
        self.assertEqual(msg["role"], "user")
        content = msg["content"]
        self.assertEqual(len(content), 3)  # 1 text prompt + 2 image_url objects
        self.assertEqual(content[0]["type"], "text")
        self.assertEqual(content[0]["text"], FORENSIC_INSPECTOR_PROMPT)
        self.assertEqual(content[1]["type"], "image_url")
        self.assertEqual(content[1]["image_url"]["url"], "https://images.example.com/front.jpg")
        self.assertEqual(content[2]["type"], "image_url")
        self.assertEqual(content[2]["image_url"]["url"], "https://images.example.com/side.jpg")

    def test_max_ten_images_strict_cap(self):
        client = OpenRouterVisionClient(api_key="test_key")
        urls_25 = [f"https://images.example.com/pic_{i}.jpg" for i in range(25)]
        msg = client.build_multimodal_message(urls_25, use_base64=False, max_images=25)
        # 1 text prompt + exactly 10 images max
        image_items = [c for c in msg["content"] if c.get("type") == "image_url"]
        self.assertEqual(len(image_items), 10)

        # Test pipeline cap
        pipeline = ForensicVisualPipeline(max_images_per_listing=30)
        self.assertEqual(pipeline.max_images_per_listing, 10)

    @patch("requests.Session.post")
    def test_inspect_listing_images_mocked_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": (
                            "### IMAGE 1: [Front Three-Quarter View]\n"
                            "- **Frame & Environment:** Dry asphalt outdoor parking lot.\n"
                            "- **Visible Panels & Alignment:** Uneven shut-line between hood and driver fender.\n"
                            "- **Paint & Body Condition:** Swirl marks on hood, rust bubbling along rocker panel.\n"
                            "- **Glass, Trim & Lighting:** Clear headlamp lenses.\n"
                            "- **Wheels, Brakes & Tires:** Curb rash on front left rim.\n"
                            "- **Micro-Anomalies & Red Flags:** Slight overspray on inner fender liner."
                        )
                    }
                }
            ]
        }
        mock_post.return_value = mock_response

        client = OpenRouterVisionClient(api_key="test_key")
        report = client.inspect_listing_images(["https://images.example.com/car.jpg"], use_base64=False)

        self.assertIn("### IMAGE 1", report)
        self.assertIn("rust bubbling along rocker panel", report)
        self.assertIn("Uneven shut-line between hood and driver fender", report)

    def test_audit_visual_text_for_flags(self):
        pipeline = ForensicVisualPipeline()

        sample_clean_report = (
            "### IMAGE 1: [Front View]\n"
            "- **Visible Panels & Alignment:** Even shut lines.\n"
            "- **Paint & Body Condition:** High gloss, clean finish.\n"
        )
        flags_clean = pipeline.audit_visual_text_for_flags(sample_clean_report)
        self.assertEqual(flags_clean, [])

        sample_flawed_report = (
            "### IMAGE 1: [Side Profile]\n"
            "- **Visible Panels & Alignment:** Uneven gap on driver door, panel mismatch.\n"
            "- **Paint & Body Condition:** Rust bubbling along lower sills, clearcoat failure on roof.\n"
            "- **Instrument Cluster & Electronics:** Check engine light and warning light on dashboard.\n"
            "- **Micro-Anomalies & Red Flags:** Fluid drip under transmission area."
        )
        flags_flawed = pipeline.audit_visual_text_for_flags(sample_flawed_report)
        self.assertTrue(any("RUST_CORROSION" in f for f in flags_flawed))
        self.assertTrue(any("PANEL_ALIGNMENT_COLLISION" in f for f in flags_flawed))
        self.assertTrue(any("WARNING_LIGHTS" in f for f in flags_flawed))
        self.assertTrue(any("FLUID_LEAK" in f for f in flags_flawed))
        self.assertTrue(any("COSMETIC_DAMAGE" in f for f in flags_flawed))

    def test_compute_visual_score(self):
        listing_clean = Listing(
            id="clean1",
            title="Clean S13",
            price=15000.0,
            specs={"visual_flags": []},
        )
        score_clean = ForensicVisualPipeline.compute_visual_score(listing_clean)
        self.assertEqual(score_clean, 10.0)

        listing_flawed = Listing(
            id="flawed1",
            title="Rust Bucket S13",
            price=8000.0,
            specs={"visual_flags": [
                "RUST_CORROSION:rust bubbling",
                "PANEL_ALIGNMENT_COLLISION:uneven gap",
                "WARNING_LIGHTS:check engine",
            ]},
        )
        score_flawed = ForensicVisualPipeline.compute_visual_score(listing_flawed)
        # 10 - 3.0 (rust) - 2.5 (alignment) - 2.0 (cel) = 2.5
        self.assertAlmostEqual(score_flawed, 2.5)

    def test_pipeline_run_top10_to_top5_mocked(self):
        """Verify pipeline takes top 10 candidates, inspects them, and curates at least top 5."""
        mock_client = MagicMock()

        def mock_inspect(image_urls, **kwargs):
            if "rust" in image_urls[0]:
                return "Visible rust bubbling and uneven gap with frame damage."
            return "Even shut lines, clean original paint, no warning lights."

        mock_client.is_configured = True
        mock_client.inspect_listing_images.side_effect = mock_inspect

        pipeline = ForensicVisualPipeline(vision_client=mock_client, use_base64=False)

        # Generate 12 mock candidate listings
        mock_listings = []
        for i in range(1, 13):
            is_rusty = (i == 2 or i == 3)  # Two listings with rust
            img_prefix = "rust" if is_rusty else "clean"
            mock_listings.append(
                Listing(
                    id=f"car-{i:02d}",
                    title=f"Nissan S13 #{i:02d}",
                    price=5000.0 + (i * 1000.0),
                    platform=Platform.AUTOSCOUT24,
                    specs={"images": [f"https://example.com/{img_prefix}_{i}.jpg"]},
                )
            )

        result = pipeline.run(mock_listings, top_n_candidates=10, top_n_final=5)

        # Inspected top 10
        self.assertEqual(len(result.inspected_listings), 10)
        self.assertEqual(mock_client.inspect_listing_images.call_count, 10)

        # Curated top listings has at least 5
        self.assertGreaterEqual(len(result.curated_top_listings), 5)

        # Verify inspection details were stored on each listing
        first = result.inspected_listings[0]
        self.assertIn("visual_inspection", first.specs)
        self.assertIn("visual_score", first.specs)
        self.assertIn("visual_flags", first.specs)


if __name__ == "__main__":
    unittest.main()

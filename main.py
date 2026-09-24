#!/usr/bin/env python3
"""CLI Entrypoint for ScrapeSuite."""
import argparse
import json
import sys

from src.models import SearchFilter, Platform
from src.scrapers.wallapop import WallapopScraper
from src.scrapers.autoscout24 import AutoScout24Scraper
from src.vision import OpenRouterVisionClient, ForensicVisualPipeline
from src.utils.spain_legalization import SpainLegalizationCalculator
from src.scrapers.ur_net import URNetScraper

def main():
    parser = argparse.ArgumentParser(description="ScrapeSuite: High-Performance Marketplace Scraper")
    subparsers = parser.add_subparsers(dest="command")

    # search command
    p_search = subparsers.add_parser("search", help="Execute a marketplace search")
    p_search.add_argument("query", type=str, help="Search query keywords")
    p_search.add_argument("--platform", type=str, default="wallapop", help="Target platform (default: wallapop)")
    p_search.add_argument("--category", type=str, default=None, help="Platform category ID (e.g. 100 for cars)")
    p_search.add_argument("--min-price", type=float, default=None, help="Minimum price in EUR")
    p_search.add_argument("--max-price", type=float, default=None, help="Maximum price in EUR")
    p_search.add_argument("--exclude", nargs="*", default=[], help="Keywords to exclude from search")
    p_search.add_argument("--limit", type=int, default=15, help="Max results to display")
    p_search.add_argument("--json", dest="json_out", type=str, default=None, help="Export results to JSON file")
    p_search.add_argument("--countries", nargs="*", default=[], help="Target European countries (e.g. ES DE FR IT NL BE AT)")
    p_search.add_argument("--min-year", type=int, default=None, help="Minimum registration year")
    p_search.add_argument("--max-year", type=int, default=None, help="Maximum registration year")
    p_search.add_argument("--max-km", type=int, default=None, help="Maximum mileage in km")
    p_search.add_argument("--fuel", type=str, default=None, help="Fuel type (gasoline, diesel, electric, hybrid, lpg)")
    p_search.add_argument("--gear", type=str, default=None, help="Gearbox (manual, automatic)")
    p_search.add_argument("--audit", action="store_true", help="Deep forensic audit of seller descriptions")
    p_search.add_argument("--vision", action="store_true", help="Enable Gemini 2.5 Flash vision inspection via OpenRouter")
    p_search.add_argument("--openrouter-key", type=str, default=None, help="OpenRouter API Key for Gemini 2.5 Flash vision")
    p_search.add_argument("--top-inspect", type=int, default=10, help="Number of candidate listings to visually inspect (default: 10)")
    p_search.add_argument("--top-report", type=int, default=5, help="Minimum number of top listings in final report (default: 5)")
    p_search.add_argument("--max-images", type=int, default=10, help="Max images to inspect per listing (max: 10, default: 10)")
    p_search.add_argument("--no-spain-legal", dest="spain_legal", action="store_false", default=True, help="Disable Spain legalization breakdown")

    p_search.add_argument("--layout", type=str, default=None, help="Housing layout (e.g. 1K, 1LDK, 2LDK, 3LDK)")
    p_search.add_argument("--min-area", type=float, default=None, help="Minimum floor space in m²")
    p_search.add_argument("--max-area", type=float, default=None, help="Maximum floor space in m²")
    p_search.add_argument("--all-properties", action="store_true", help="List all complexes including 0 vacant units")
    args = parser.parse_args()

    if args.command == "search":
        platform_name = args.platform.strip().lower()
        sf = SearchFilter(
            min_price=args.min_price,
            max_price=args.max_price,
            category_id=args.category,
            exclude_keywords=args.exclude,
            min_year=args.min_year,
            max_year=args.max_year,
            max_mileage_km=args.max_km,
            countries=args.countries,
            fuel_type=args.fuel,
            gearbox=args.gear,
            audit_descriptions=args.audit,
            layout=args.layout,
            min_area_m2=args.min_area,
            max_area_m2=args.max_area,
            only_vacant=not args.all_properties,
        )

        if platform_name in ("autoscout24", "autoscout", "as24"):
            scraper = AutoScout24Scraper()
        elif platform_name in ("ur_net", "ur_housing", "ur"):
            scraper = URNetScraper()
        elif platform_name in ("wallapop",):
            scraper = WallapopScraper()
        else:
            print(f"[-] Unknown platform '{args.platform}'. Available: wallapop, autoscout24, ur_net")
            sys.exit(1)
        print(f"[*] Querying {scraper.platform.value.upper()} for '{args.query}'...")
        if args.exclude:
            print(f"    Excluding keywords: {args.exclude}")
        if args.category:
            print(f"    Category filter: {args.category}")

        if args.countries:
            print(f"    Countries:        {args.countries}")
        if args.min_year or args.max_year:
            print(f"    Year range:       {args.min_year or 'Any'} - {args.max_year or 'Any'}")
        if args.max_km:
            print(f"    Max mileage:      {args.max_km} km")
        if args.fuel:
            print(f"    Fuel:             {args.fuel}")
        if args.gear:
            print(f"    Gearbox:          {args.gear}")
        if args.layout:
            print(f"    Layout:           {args.layout}")
        if args.min_area or args.max_area:
            print(f"    Floor space:      {args.min_area or 0}㎡ - {args.max_area or 'Any'}㎡")
        if args.all_properties:
            print(f"    Include 0-vacancy:True")
        results = scraper.search(args.query, search_filter=sf)
        print(f"\n[+] Total items retrieved: {len(results)}\n")

        final_listings = results
        discarded_summary = []

        if args.vision:
            vision_client = OpenRouterVisionClient(api_key=args.openrouter_key)
            if not vision_client.is_configured:
                print("[!] Notice: --vision requested but OPENROUTER_API_KEY is not set.")
                print("    Please set the OPENROUTER_API_KEY environment variable, add it to .env, or use --openrouter-key.")
                print("    Proceeding with text/specs evaluation only.\n")
            else:
                print(f"[*] Launching Gemini 2.5 Flash vision inspection on top {min(args.top_inspect, len(results))} listings...")
                pipeline = ForensicVisualPipeline(vision_client=vision_client, max_images_per_listing=args.max_images)

                detail_fetcher = None
                if hasattr(scraper, "audit_listing_detail"):
                    detail_fetcher = scraper.audit_listing_detail

                def on_progress(idx, total, listing, status):
                    if status == "calling_gemini_vision":
                        print(f"    [{idx}/{total}] Inspecting photos for #{idx:02d} {listing.title[:45]}...")

                v_res = pipeline.run(
                    results,
                    top_n_candidates=args.top_inspect,
                    top_n_final=args.top_report,
                    scraper_detail_fetcher=detail_fetcher,
                    progress_callback=on_progress,
                )

                final_listings = v_res.curated_top_listings
                discarded_summary = v_res.discarded_listings
                print(f"\n[+] Vision appraisal complete. Curated top {len(final_listings)} listings.\n")

                if discarded_summary:
                    print(f"[-] Discarded listings based on visual red flags:")
                    for disc_item, reason in discarded_summary:
                        print(f"    - [{disc_item.price:.2f}€] {disc_item.title[:45]}: {reason}")
                    print()

        display_items = final_listings[:args.limit] if not args.vision else final_listings[:max(args.top_report, 5)]

        for idx, it in enumerate(display_items, 1):
            dist_str = f" | {it.distance_km:.1f} km" if it.distance_km is not None else ""
            ship_str = " | Ships" if it.shipping_available else " | Pickup only"
            bait_flag = " [!] BAIT PRICE" if it.specs.get("is_placeholder_price") else ""
            img_count_str = f" ({it.specs.get('images_inspected_count', 0)} photos)" if "images_inspected_count" in it.specs else ""
            v_score_str = f" [Vision: {it.specs['visual_score']:.1f}/10{img_count_str}]" if "visual_score" in it.specs else ""
            if it.platform == Platform.UR_NET:
                price_str = f"¥{it.price:,.0f}/mo"
                fee_str = f" (Fee: ¥{it.shipping_cost:,.0f}/mo)" if it.shipping_cost > 0 else ""
                print(f"#{idx:02d} [{price_str}{fee_str}] {it.title[:65]}")
                print(f"     Location: {it.seller_location or 'N/A'}")
                print(f"     URL:      {it.url}")
                h_parts = []
                if it.specs.get("madori"): h_parts.append(it.specs["madori"])
                if it.specs.get("floorspace_m2"): h_parts.append(f"{it.specs['floorspace_m2']:.0f}㎡")
                if it.specs.get("floor"): h_parts.append(it.specs["floor"])
                if it.specs.get("vacant_rooms_in_complex") is not None:
                    h_parts.append(f"Vacancies: {it.specs['vacant_rooms_in_complex']}")
                if h_parts:
                    print(f"     Specs:    {' | '.join(h_parts)}")
                print("     UR Perks: 0 Reikin (No Key Money) | 0 Agency Fee | 0 Renewal Fee | NO Guarantor")
                if it.specs.get("access"):
                    print(f"     Access:   {it.specs['access'][:80]}...")
            else:
                dist_str = f" | {it.distance_km:.1f} km" if it.distance_km is not None else ""
                ship_str = " | Ships" if it.shipping_available else " | Pickup only"
                bait_flag = " [!] BAIT PRICE" if it.specs.get("is_placeholder_price") else ""
                img_count_str = f" ({it.specs.get('images_inspected_count', 0)} photos)" if "images_inspected_count" in it.specs else ""
                v_score_str = f" [Vision: {it.specs['visual_score']:.1f}/10{img_count_str}]" if "visual_score" in it.specs else ""
                
                print(f"#{idx:02d} [{it.price:.2f}€{bait_flag}]{v_score_str} {it.title[:60]}")
                print(f"     Location: {it.seller_location or 'N/A'}{dist_str}{ship_str}")
                print(f"     URL:      {it.url}")
                specs_parts = []
                if it.specs.get("year"):
                    specs_parts.append(f"Year: {it.specs['year']}")
                if it.specs.get("mileage_km"):
                    specs_parts.append(f"{it.specs['mileage_km']:,} km")
                if it.specs.get("power_hp"):
                    specs_parts.append(f"{it.specs['power_hp']} hp")
                if it.specs.get("fuel"):
                    specs_parts.append(f"{it.specs['fuel']}")
                if it.specs.get("transmission"):
                    specs_parts.append(f"{it.specs['transmission']}")
                if specs_parts:
                    print(f"     Specs:    {' | '.join(specs_parts)}")

                if it.specs.get("forensic_flags"):
                    print(f"     [!] Mechanical Flags: {', '.join(it.specs['forensic_flags'])}")

                if it.specs.get("visual_flags"):
                    print(f"     [!] Visual Flags:     {', '.join(it.specs['visual_flags'])}")
                if getattr(args, "spain_legal", True):
                    legal = SpainLegalizationCalculator.calculate(it)
                    if not legal.is_domestic:
                        rhd_note = " | RHD lighting adapt" if legal.rhd_adaptation_cost > 0 else ""
                        print(f"     [+] Legalize in Spain: +{legal.total_legalization_cost:,.2f} € (Transport: {legal.transport_or_transit_cost:.0f}€ | ITV/Ficha: {legal.itv_importacion_cost + legal.ficha_reducida_cost:.0f}€ | DGT/Taxes: {legal.dgt_fee + legal.iedmt_modelo_576_cost:.0f}€{rhd_note})")
                        print(f"         Total Landed & Legal in Spain: {legal.total_landed_spain_cost:,.2f} €")
                    else:
                        print(f"     [+] Domestic Spain: DGT Transfer & ITP: +{legal.total_legalization_cost:,.2f} € | Total in Spain: {legal.total_landed_spain_cost:,.2f} €")

                if it.description:
                    print(f"     Desc:     {it.description[:100]}...")

                if it.specs.get("visual_inspection"):
                    v_preview = it.specs["visual_inspection"].strip()
                    first_lines = "\n               ".join(v_preview.splitlines()[:4])
                    print(f"     Visual:   {first_lines}...")
            print()
        if args.json_out:
            with open(args.json_out, "w", encoding="utf-8") as f:
                json.dump([it.to_dict() for it in final_listings], f, indent=2, ensure_ascii=False)
            print(f"[+] Results saved to {args.json_out}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()

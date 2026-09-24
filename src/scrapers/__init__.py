"""Scrapers package for ScrapeSuite."""
from src.scrapers.base import BaseScraper
from src.scrapers.wallapop import WallapopScraper
from src.scrapers.autoscout24 import AutoScout24Scraper
from src.scrapers.ur_net import URNetScraper

__all__ = ["BaseScraper", "WallapopScraper", "AutoScout24Scraper", "URNetScraper"]

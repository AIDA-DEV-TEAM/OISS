"""Filesystem paths and layer names for the OISS data layer."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
EXTRACTED = DATA / "extracted"
SYNTHETIC = DATA / "synthetic"
DB_PATH = DATA / "oiss.duckdb"

LAYERS = ("raw", "quarantine", "staging", "analytics")

# Odisha agricultural year runs July -> June; month 1 of an agri year is July.
AGRI_YEAR_START_MONTH = 7

STATE_DISTRICT_ID = "OD00"

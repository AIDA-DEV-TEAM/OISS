"""Filesystem paths and layer names for the OISS data layer."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
EXTRACTED = DATA / "extracted"
SYNTHETIC = DATA / "synthetic"
DB_PATH = DATA / "oiss.duckdb"
# Generated export files. Written at run time, never committed.
EXPORTS = DATA / "exports"

LAYERS = ("raw", "quarantine", "staging", "analytics")

# Odisha agricultural year runs July -> June; month 1 of an agri year is July.
AGRI_YEAR_START_MONTH = 7

STATE_DISTRICT_ID = "OD00"

import os
MODEL_API_BASE_URL = os.environ.get("MODEL_API_BASE_URL", "http://127.0.0.1:8000")

# Language model used by the assistant (RFP area 5). Read from the environment,
# never from a file in the repo; see .env.example for what each one means.
# An empty value (as .env.example leaves them) means the default.
LLM_PROVIDER = (os.environ.get("LLM_PROVIDER") or "gemini").strip().lower()
LLM_MODEL = os.environ.get("LLM_MODEL") or "gemini-2.5-flash"
LLM_API_KEY = os.environ.get("LLM_API_KEY") or ""
LLM_TIMEOUT_SECONDS = float(os.environ.get("LLM_TIMEOUT_SECONDS") or "20")
# Responses cached by a hash of their input. Committed, so the starter questions
# answer identically with no API key and no network.
LLM_CACHE_DIR = Path(os.environ.get("LLM_CACHE_DIR") or DATA / "llm_cache")

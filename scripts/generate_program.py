#!/usr/bin/env python3
import json
import re
from datetime import datetime, date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
TZ = ZoneInfo(CFG.get("timezone", "Europe/Amsterdam"))
OUT = ROOT / "site"
OUT.mkdir(exist_ok=True)

MONTHS = {
    "jan": 1, "feb": 2, "mrt": 3, "mar": 3,
    "apr": 4, "mei": 5, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "okt": 10, "nov": 11, "dec": 12,
}

# Instellingen voor de schermweergave
MAX_MATCHES_PER_PAGE = 4
PAGE_INTERVAL_SECONDS = 12


def parse_date(value, today):
    value = value.lower().strip()

    m = re.search(r"(\d{1,2})[-/](\d{1,2})[-/](20\d{2})", value)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None

    m = re.search(r"(\d{1,2})\s+([a-z]+)", value)
    if m:
        month = MONTHS.get(m.group(2)[:3])
        if month:
            year = today.year
            try:
                d = date(year, month, int(m.group(1)))
                if d < today - timedelta(days=180):
                    d = date(year + 1, month, int(m.group(1)))
                return d
            except ValueError:
                return None
    return None


def get_rows():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(CFG["source_url"], wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)

        rows = page.evaluate("""() => {
            const all = [];
            const elements = [...document.querySelectorAll('tr, [role="row"]')];
            for (const row of elements) {
                const cells = [...row.querySelectorAll(
                    ':scope > td, :scope > th, :scope > [role="cell"], :scope > [role="gridcell"], :scope > [role="columnheader"]'
                )];
                if (cells.length >= 2) all.push(cells.map(c => c.innerText.trim()));
            }
            return all;
        }""")
        html = page.content()
        browser.close()
    return rows, html


def find_matches(rows, today):
    matches = []
    diagnostics = []
    end_date = today + timedelta(days=int(CFG.get("lookahead_days", 7)))

    header = None
    for cells in rows:
        normalized = [c.strip().lower() for c in cells]
        if any("thuis" in c for c in normalized) and any(
            "uit" == c or c.endswith(" uit") for c in normalized
        ):
            header = normalized
            break

    if not header:
        return [], [{"error": "Header met THUIS en UIT niet gevonden", "rows": rows}]

    date_idx = next((i for i, c in enumerate(header) if "datum" in c), None)
    time_idx = next((i for i, c in enumerate(header) if "tijd" in c), None)
    home_idx = next((i for i, c in enumerate(header) if "thuis" in c), None)
    away_idx = next((i for i, c in enumerate(header) if c == "uit" or c.endswith(" uit")), None)

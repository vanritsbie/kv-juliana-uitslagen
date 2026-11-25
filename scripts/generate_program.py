
#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
TZ = ZoneInfo(CFG.get("timezone", "Europe/Amsterdam"))
OUT = ROOT / "site"
OUT.mkdir(exist_ok=True)

MONTHS = {
    "januari": 1, "februari": 2, "maart": 3,
    "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "augustus": 8, "september": 9,
    "oktober": 10, "november": 11, "december": 12,
}

def normalize(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()

def extract_date(text):
    text = text.lower()

    m = re.search(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", text)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)),
                            int(m.group(3))).date()
        except ValueError:
            pass

    for month, number in MONTHS.items():
        m = re.search(rf"\b(\d{{1,2}})\s+{month}\s+(20\d{{2}})\b", text)
        if m:
            try:
                return datetime(int(m.group(2)), number,
                                int(m.group(1))).date()
            except ValueError:
                pass

    m = re.search(r"\b(\d{1,2})[-/](\d{1,2})[-/](20\d{2})\b", text)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)),
                            int(m.group(1))).date()
        except ValueError:
            pass

    return None

def fetch_page():
    url = CFG["source_url"]

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)
        html = page.content()
        browser.close()

    return html

def extract_rows(html):
    soup = BeautifulSoup(html, "html.parser")
    rows = []

    for tr in soup.find_all("tr"):
        text = normalize(tr.get_text(" ", strip=True))
        if text:
            rows.append(text)

    selectors = [
        "[class*='wedstrijd']",
        "[class*='match']",
        "[class*='game']",
        "[class*='event']",
    ]

    for selector in selectors:
        for element in soup.select(selector):
            text = normalize(element.get_text(" ", strip=True))
            if text and len(text) < 500:
                rows.append(text)

    return list(dict.fromkeys(rows))

def is_home_match(row):
    # Controleer of Juliana aan de linkerzijde van
    # een wedstrijdscheiding staat.
    separators = r"\s+(?:-|–|—|vs\.?|tegen)\s+"

    parts = re.split(separators, row, maxsplit=1,
                     flags=re.IGNORECASE)

    if len(parts) < 2:
        return False

    home_team = parts[0].strip().lower()

    return "juliana" in home_team

def main():
    matches = []
    errors = []
    diagnostic_rows = []

    try:
        html = fetch_page()
        rows = extract_rows(html)

        today = datetime.now(TZ).date()
        end_date = today + timedelta(
            days=int(CFG.get("lookahead_days", 7))
        )

        for row in rows:
            date_value = extract_date(row)

            diagnostic_rows.append({
                "raw": row,
                "date": str(date_value) if date_value else None,
                "home_match": is_home_match(row)
            })

            if not is_home_match(row):
                continue

            if not date_value:
                continue

            if not (today <= date_value <= end_date):
                continue

            matches.append({
                "date": str(date_value),
                "raw": row
            })

    except Exception as e:
        errors.append(str(e))
        print(f"FOUT bij ophalen programma: {e}", file=sys.stderr)

    matches.sort(key=lambda x: x.get("date", ""))

    render(matches, errors)

    (OUT / "diagnostics.json").write_text(
        json.dumps(diagnostic_rows, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

def render(matches, errors):
    if matches:
        rows = "".join(
            f'<article class="match">'
            f'<div class="date">{m["date"]}</div>'
            f'<div class="details">{m["raw"]}</div>'
            f'</article>'
            for m in matches
        )
        status = ""
    elif errors:
        rows = (
            '<div class="empty">'
            'Programma tijdelijk niet beschikbaar.'
            '<br><small>De gegevensbron kon niet worden geladen.</small>'
            '</div>'
        )
        status = '<div class="status">Bronfout</div>'
    else:
        rows = (
            '<div class="empty">'
            'Geen thuiswedstrijden gevonden in de komende 7 dagen.'
            '</div>'
        )
        status = '<div class="status">Programma automatisch bijgewerkt</div>'

    html = f"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="900">
<title>KV Juliana | Thuis in 't Veerhuis</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;background:#f8f9fc;color:#122f57;
font-family:Arial,Helvetica,sans-serif}}
main{{width:100vw;height:100vh;padding:4vw 5vw;
display:flex;flex-direction:column;gap:2vh;overflow:hidden}}
header{{display:flex;align-items:center;gap:2vw;
border-bottom:5px solid #f58200;padding-bottom:1.5vh}}
.brand{{font-size:clamp(20px,3vw,52px);font-weight:900;
letter-spacing:.04em;color:#122f57}}
h1{{font-size:clamp(26px,4vw,64px);margin:0;color:#122f57}}
.subtitle{{font-size:clamp(14px,2vw,32px);
font-weight:700;color:#f58200}}
.list{{display:flex;flex-direction:column;gap:1.2vh;overflow:hidden}}
.match{{display:flex;align-items:center;gap:2vw;background:white;
border-left:1vw solid #f58200;padding:2vh 2vw;border-radius:10px;
box-shadow:0 2px 10px #0001;font-size:clamp(16px,2.3vw,36px)}}
.date{{font-weight:900;min-width:16vw;color:#f58200}}
.details{{font-weight:700}}
.empty{{font-size:clamp(22px,3vw,44px);padding:5vh;
background:white;border-radius:12px;text-align:center}}
small{{font-size:.6em}}
footer{{margin-top:auto;background:#122f57;color:white;
padding:2vh 2vw;border-radius:8px;display:flex;
justify-content:space-between;font-size:clamp(13px,1.8vw,28px);
font-weight:700}}
.status{{font-size:14px;color:#6b7280}}
</style>
</head>
<body>
<main>
<header>
<div class="brand">KV JULIANA</div>
<div>
<h1>THUIS IN 'T VEERHUIS</h1>
<div class="subtitle">WEDSTRIJDPROGRAMMA</div>
</div>
</header>
<section class="list">{rows}</section>
{status}
<footer>
<span>Kom onze teams aanmoedigen!</span>
<span>kvjuliana.nl</span>
</footer>
</main>
</body>
</html>"""

    (OUT / "index.html").write_text(html, encoding="utf-8")
    (OUT / "matches.json").write_text(
        json.dumps(matches, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"Generated page for {len(matches)} matches")

if __name__ == "__main__":
    main()

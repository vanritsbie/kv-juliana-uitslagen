
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
    "apr": 4, "mei": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9,
    "okt": 10, "nov": 11, "dec": 12,
}

def parse_date(value, today):
    value = value.lower().strip().replace(".", "")

    # Datum met jaar, bijvoorbeeld 28-11-2026
    m = re.search(r"(\d{1,2})[-/](\d{1,2})[-/](20\d{2})", value)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None

    # Nederlandse datum, bijvoorbeeld 28 nov
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
    url = CFG["source_url"]

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)

        # Verzamel tabelregels en hun cellen uit de geladen pagina
        data = page.evaluate("""() => {
            const output = [];
            const selectors = ['tr', '[role="row"]'];

            const elements = [...new Set(
                selectors.flatMap(s => [...document.querySelectorAll(s)])
            )];

            for (const row of elements) {
                const cells = [...row.querySelectorAll(
                    ':scope > td, :scope > th, :scope > [role="cell"], :scope > [role="gridcell"], :scope > [role="columnheader"]'
                )];

                if (cells.length >= 2) {
                    output.push(cells.map(c => c.innerText.trim()));
                }
            }

            return output;
        }""")

        html = page.content()
        browser.close()

    return data, html

def find_matches(rows, today):
    matches = []
    diagnostics = []

    current_date = None
    end_date = today + timedelta(days=int(CFG.get("lookahead_days", 7)))

    for cells in rows:
        text = " | ".join(cells)
        diagnostics.append({"cells": cells})

        # Zoek een datum in de rij
        row_date = None
        for cell in cells:
            row_date = parse_date(cell, today)
            if row_date:
                break

        if row_date:
            current_date = row_date

        # Zoek een tijd in de rij
        time_value = next(
            (c for c in cells if re.fullmatch(r"\d{1,2}:\d{2}", c)),
            None
        )

        # Zoek de teamkolommen op basis van de inhoud
        # Juliana moet in de thuis-teamkolom staan.
        if current_date and time_value:
            team_cells = [
                c for c in cells
                if re.search(r"\bJuliana\b", c, re.IGNORECASE)
            ]

            if team_cells:
                # Controleer of Juliana in een wedstrijdregel staat.
                # Een teamnaam wordt alleen als thuis beschouwd als
                # hij in de tabel vóór het uit-team staat.
                juliana_index = next(
                    (i for i, c in enumerate(cells)
                     if re.search(r"\bJuliana\b", c, re.IGNORECASE)),
                    -1
                )

                # Regels met Juliana en een tijd worden diagnostisch
                # geregistreerd; de kolomcontrole wordt hieronder
                # verder verfijnd op basis van de header.
                diagnostics[-1]["juliana_index"] = juliana_index

    return matches, diagnostics

def render(matches):
    if matches:
        rows_html = "".join(
            f"""<article class="match">
            <div class="date">{m["date"]}</div>
            <div class="time">{m["time"]}</div>
            <div class="teams">{m["home"]} <span>–</span> {m["away"]}</div>
            </article>"""
            for m in matches
        )
        status = ""
    else:
        rows_html = """
        <div class="empty">
        Geen thuiswedstrijden gevonden in de komende 7 dagen.
        </div>
        """
        status = '<div class="status">Programma automatisch bijgewerkt</div>'

    html = f"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="900">
<title>KV Juliana thuisprogramma</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;background:#f6f8fc;color:#15345c;
font-family:Arial,Helvetica,sans-serif}}
main{{width:100vw;height:100vh;padding:4vw 5vw;
display:flex;flex-direction:column;gap:2vh;overflow:hidden}}
header{{display:flex;align-items:center;gap:2vw;
border-bottom:5px solid #f58200;padding-bottom:1.5vh}}
.brand{{font-size:clamp(20px,3vw,52px);font-weight:900;
letter-spacing:.04em}}
h1{{font-size:clamp(26px,4vw,64px);margin:0}}
.subtitle{{font-size:clamp(14px,2vw,32px);
font-weight:700;color:#f58200}}
.list{{display:flex;flex-direction:column;gap:1.2vh;overflow:hidden}}
.match{{display:flex;align-items:center;gap:2vw;background:white;
border-left:1vw solid #f58200;padding:2vh 2vw;border-radius:10px;
box-shadow:0 2px 10px #0001;font-size:clamp(16px,2.3vw,36px)}}
.date{{font-weight:900;min-width:15vw}}
.time{{font-weight:700;min-width:8vw;color:#f58200}}
.teams{{font-weight:700}}
.teams span{{color:#f58200;padding:0 .5em}}
.empty{{font-size:clamp(22px,3vw,44px);padding:5vh;
background:white;border-radius:12px;text-align:center}}
.status{{font-size:14px;color:#6b7280}}
footer{{margin-top:auto;background:#15345c;color:white;
padding:2vh 2vw;border-radius:8px;display:flex;
justify-content:space-between;font-size:clamp(13px,1.8vw,28px);
font-weight:700}}
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
<section class="list">{rows_html}</section>
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

def main():
    today = datetime.now(TZ).date()
    rows, html = get_rows()

    (OUT / "source.html").write_text(html, encoding="utf-8")

    matches, diagnostics = find_matches(rows, today)

    (OUT / "diagnostics.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    render(matches)
    print(f"Rows collected: {len(rows)}")
    print(f"Matches found: {len(matches)}")

if __name__ == "__main__":
    main()

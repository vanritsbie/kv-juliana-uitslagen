#!/usr/bin/env python3
"""Initial weekly KV Juliana home-match display generator."""
from __future__ import annotations
import json, re, sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
TZ = ZoneInfo(CFG.get("timezone", "Europe/Amsterdam"))
OUT = ROOT / "site"
OUT.mkdir(exist_ok=True)

def normalize(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()

def extract_rows(soup):
    rows = []
    for table in soup.find_all("table"):
        headers = [normalize(th.get_text(" ", strip=True)).lower() for th in table.find_all("th")]
        for tr in table.find_all("tr"):
            cells = [normalize(td.get_text(" ", strip=True)) for td in tr.find_all(["td", "th"])]
            if not cells: continue
            if headers and len(headers) == len(cells):
                rows.append(dict(zip(headers, cells)))
            else:
                rows.append({"text": " | ".join(cells)})
    for node in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(node.string or node.get_text())
            if isinstance(data, list): rows.extend(data)
            elif isinstance(data, dict):
                rows.extend(data.get("events", []) if isinstance(data.get("events"), list) else [data])
        except Exception: pass
    return rows

def row_text(row):
    return normalize(" ".join(map(str, row.values()))) if isinstance(row, dict) else normalize(row)

def parse_date(text):
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try: return datetime.strptime(text, fmt).date()
        except ValueError: pass
    return None

def main():
    matches = []
    try:
        response = requests.get(CFG["source_url"], timeout=30,
            headers={"User-Agent": "KVJulianaYodeck/1.0"})
        response.raise_for_status()
        try:
            data = response.json()
            rows = data if isinstance(data, list) else data.get("matches", data.get("events", []))
        except Exception:
            rows = extract_rows(BeautifulSoup(response.text, "html.parser"))
        now = datetime.now(TZ).date()
        until = now + timedelta(days=int(CFG.get("lookahead_days", 7)))
        club_keys = [x.lower() for x in CFG.get("filter_keywords", ["Juliana"])]
        venue_keys = [x.lower() for x in CFG.get("venue_keywords", ["Veerhuis", "Oud Gastel"])]
        for row in rows:
            raw = row_text(row)
            low = raw.lower()
            if not any(k in low for k in club_keys) or not any(k in low for k in venue_keys):
                continue
            date_val = None
            if isinstance(row, dict):
                for k, v in row.items():
                    if "date" in str(k).lower() or "datum" in str(k).lower():
                        date_val = parse_date(str(v)) or date_val
            if not date_val:
                for token in re.findall(r"\d{4}-\d{2}-\d{2}|\d{2}-\d{2}-\d{4}|\d{2}/\d{2}/\d{4}", raw):
                    date_val = parse_date(token)
                    if date_val: break
            if date_val and not (now <= date_val <= until): continue
            matches.append({"date": str(date_val) if date_val else "", "raw": raw})
    except Exception as e:
        print(f"Source retrieval/parsing failed: {e}", file=sys.stderr)
    matches.sort(key=lambda x: x.get("date", ""))
    render(matches)

def render(matches):
    if matches:
        rows = "".join(
            f'<article class="match"><div class="date">{m["date"] or "Datum onbekend"}</div><div class="details">{m["raw"]}</div></article>'
            for m in matches)
        status = ""
    else:
        rows = '<div class="empty">Op dit moment zijn er geen wedstrijden gevonden.<br><small>Het programma wordt automatisch vernieuwd. Controleer de bronkoppeling als dit bericht blijft staan.</small></div>'
        status = '<div class="status">Programma wordt automatisch bijgewerkt</div>'
    html = f"""<!DOCTYPE html>
<html lang="nl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="900"><title>KV Juliana | Thuis in 't Veerhuis</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#f8f9fc;color:#122f57;font-family:Arial,Helvetica,sans-serif}}
main{{width:100vw;height:100vh;padding:4vw 5vw;display:flex;flex-direction:column;gap:2vh;overflow:hidden}}
header{{display:flex;align-items:center;gap:2vw;border-bottom:5px solid #f58200;padding-bottom:1.5vh}}
.brand{{font-size:clamp(20px,3vw,52px);font-weight:900;letter-spacing:.04em;color:#122f57}}
h1{{font-size:clamp(26px,4vw,64px);margin:0;color:#122f57}}.subtitle{{font-size:clamp(14px,2vw,32px);font-weight:700;color:#f58200}}
.list{{display:flex;flex-direction:column;gap:1.2vh;overflow:hidden}}.match{{display:flex;align-items:center;gap:2vw;background:white;border-left:1vw solid #f58200;padding:2vh 2vw;border-radius:10px;box-shadow:0 2px 10px #0001;font-size:clamp(16px,2.3vw,36px)}}
.date{{font-weight:900;min-width:16vw;color:#f58200}}.details{{font-weight:700}}.empty{{font-size:clamp(22px,3vw,44px);padding:5vh;background:white;border-radius:12px;text-align:center}}small{{font-size:.6em}}
footer{{margin-top:auto;background:#122f57;color:white;padding:2vh 2vw;border-radius:8px;display:flex;justify-content:space-between;font-size:clamp(13px,1.8vw,28px);font-weight:700}}
.status{{font-size:14px;color:#6b7280}}
</style></head><body><main><header><div class="brand">KV JULIANA</div><div><h1>THUIS IN 'T VEERHUIS</h1><div class="subtitle">WEDSTRIJDPROGRAMMA</div></div></header>
<section class="list">{rows}</section>{status}<footer><span>Kom onze teams aanmoedigen!</span><span>kvjuliana.nl</span></footer></main></body></html>"""
    (OUT/"index.html").write_text(html, encoding="utf-8")
    (OUT/"matches.json").write_text(json.dumps(matches, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Generated page for {len(matches)} filtered matches")

if __name__ == "__main__":
    main()

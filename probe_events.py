#!/usr/bin/env python3
"""Vergleicht offizielle Wilsdruffer Termin- und Veranstaltungsrubriken.

Ändert die bestehende ICS-Datei ausdrücklich NICHT.
"""
import re
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

PAGES = {
    "Verwaltung / Termine": 645,
    "Leben / Veranstaltungen": 20,
    "Tourismus / Veranstaltungen": 179,
}
s = requests.Session()
s.headers["User-Agent"] = "Mozilla/5.0 (compatible; WilsdruffKalender/0.4)"
for name, page in PAGES.items():
    print(f"\n===== {name} (pgId={page}) =====", flush=True)
    try:
        resp = s.get("https://www.wilsdruff.de/wilma.aspx", params={"pgId": page}, timeout=35)
        print("HTTP", resp.status_code, "URL", resp.url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")
        print("Titel:", soup.title.get_text(" ", strip=True) if soup.title else "-")
        tables = soup.select("table.idu-cm3-wilma-puzzle-documentlist-table")
        print("Terminlisten:", len(tables))
        for table in tables:
            rows = table.select("tr")
            print("Zeilen:", len(rows))
            for row in rows[:6]:
                print("  ", row.get_text(" | ", strip=True)[:450])
        for tag in soup.find_all(attrs={"class": re.compile("puzzle-documentlist", re.I)})[:5]:
            print("Listenelement:", tag.name, tag.get("class"), "id=", tag.get("id"))
        print("Navigation:")
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if "doclist_page" in href or "dlc_offset" in href:
                print("  ", a.get_text(" ", strip=True)[:30], urljoin(resp.url, href)[:180])
        if not tables:
            main = soup.select_one("main") or soup.select_one(".wilma-content") or soup.body
            print("Textauszug:", main.get_text(" ", strip=True)[-2000:] if main else "-")
    except Exception as exc:
        print("FEHLER:", type(exc).__name__, str(exc))

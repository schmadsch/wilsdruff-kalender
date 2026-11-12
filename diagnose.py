#!/usr/bin/env python3
"""Diagnose der öffentlichen Wilsdruffer Veranstaltungsseite.

Erzeugt noch KEINEN ICS-Kalender: Erst die HTML-Struktur prüfen.
"""
import re
import sys
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

URL = "https://www.wilsdruff.de/wilma.aspx?pgId=645"
DATE = re.compile(r"\\b(?:[0-3]?\\d[.]\\s*[01]?\\d[.]\\s*20\\d\\d|20\\d\\d-[01]\\d-[0-3]\\d)\\b")
HEADERS = {"User-Agent": "WilsdruffKalender/0.1 (+https://github.com/schmadsch/wilsdruff-kalender)"}

def main():
    try:
        response = requests.get(URL, headers=HEADERS, timeout=30)
        print("URL:", response.url)
        print("HTTP:", response.status_code)
        print("Content-Type:", response.headers.get("Content-Type", "unbekannt"))
        response.raise_for_status()
    except requests.RequestException as exc:
        print("Abruf fehlgeschlagen:", exc, file=sys.stderr)
        return 1

    soup = BeautifulSoup(response.content, "html.parser")
    print("Titel:", soup.title.get_text(" ", strip=True) if soup.title else "(kein Titel)")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    dates = DATE.findall(text)
    print("Gefundene Datumsangaben:", len(dates))
    print("Datumsbeispiele:", dates[:15])
    print("\\nRelevante Links (max. 35):")
    seen = set()
    count = 0
    for a in soup.find_all("a", href=True):
        label = a.get_text(" ", strip=True)
        href = urljoin(response.url, a["href"])
        if urlparse(href).netloc not in ("www.wilsdruff.de", "wilsdruff.de"):
            continue
        if not (re.search(r"veranstalt|termin|kalender|wilma|seite|weiter", label + " " + href, re.I)):
            continue
        if href in seen:
            continue
        seen.add(href)
        print(f"- {label[:90]}: {href}")
        count += 1
        if count >= 35:
            break
    print("\\nTextauszug (max. 2500 Zeichen):")
    print(text[:2500])
    if not dates:
        print("\\nWARNUNG: Keine Datumsangaben erkannt; HTML oder Abruf prüfen.")
        return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

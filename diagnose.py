#!/usr/bin/env python3
"""Diagnose der Wilsdruffer Kalender-HTML-Struktur (keine ICS-Erzeugung)."""
import re
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

URL = "https://www.wilsdruff.de/wilma.aspx?pgId=645"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; WilsdruffKalender/0.2)"}

def main():
    response = requests.get(URL, headers=HEADERS, timeout=30)
    print("HTTP:", response.status_code, "URL:", response.url)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")
    print("Seitentitel:", soup.title.get_text(" ", strip=True) if soup.title else "?")
    print("Tabellen:", len(soup.select("table")))
    for i, table in enumerate(soup.select("table")[:12], 1):
        print(f"\\nTABELLE {i}: id={table.get('id')} class={table.get('class')}")
        print(table.get_text(" | ", strip=True)[:1200])
    print("\\nKALENDER-ELEMENTE:")
    candidates = soup.find_all(attrs={"id": re.compile("1407|1408|kalend|termin|event|pzl", re.I)})
    for tag in candidates[:25]:
        print(tag.name, "id=", tag.get("id"), "class=", tag.get("class"))
        print(tag.get_text(" | ", strip=True)[:700])
    print("\\nLINKS MIT DATUM/KALENDERBEZUG:")
    for a in soup.select("a[href]"):
        label = a.get_text(" ", strip=True)
        href = a.get("href", "")
        if re.search(r"1407|1408|doclist|offset|monat|next|prev|veranstalt|kalend", label + " " + href, re.I):
            print(label[:90], "=>", urljoin(response.url, href)[:250])
    print("\\nKALENDER-UMGEBUNG:")
    html = str(soup)
    for match in list(re.finditer(r"November|1407|1408|Veranstaltungen", html, re.I))[-12:]:
        print(re.sub(r"\\s+", " ", html[max(0, match.start()-200):match.end()+350])[:550])
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Wilsdruff-Termine aus der öffentlichen HTML-Terminliste als iCalendar exportieren.

Quelle: https://www.wilsdruff.de/wilma.aspx?pgId=645
Achtung: Die separate Rubrik 'Veranstaltungen' (pgId=20/179) ist noch nicht geprüft.
"""
from __future__ import annotations

import hashlib
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

BASE = "https://www.wilsdruff.de/wilma.aspx?pgId=645"
TZ = ZoneInfo("Europe/Berlin")
OUTPUT = Path("docs/wilsdruff.ics")
MAX_PAGES = 30
DATE_RE = re.compile(r"\b([0-3]?\d\.[01]?\d\.20\d{2})\b")
TIME_RE = re.compile(r"\b([0-2]?\d:[0-5]\d)\b")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; WilsdruffKalender/0.3; +https://github.com/schmadsch/wilsdruff-kalender)"}


def field(text: str, label: str, next_labels: str) -> str:
    pattern = rf"(?:^|\s){re.escape(label)}\s*:\s*(.*?)(?=\s+(?:{next_labels})\s*:|$)"
    match = re.search(pattern, text, re.I | re.S)
    return match.group(1).strip(" |;-") if match else ""


def parse_page(html: bytes, url: str) -> tuple[list[dict], set[int]]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.idu-cm3-wilma-puzzle-documentlist-table")
    if table is None:
        raise ValueError("Terminliste 1408 nicht gefunden – HTML-Struktur möglicherweise geändert")

    events = []
    for tr in table.select("tr"):
        if tr.find_parent("thead"):
            continue
        text = tr.get_text(" ", strip=True)
        date_match = re.search(r"\bDatum\s*:\s*" + DATE_RE.pattern, text, re.I)
        if not date_match:
            continue
        raw_date = date_match.group(1)
        raw_time = field(text, "Uhrzeit", "Ort|Veranstalter|Datum")
        time_match = TIME_RE.search(raw_time)
        place = field(text, "Ort", "Veranstalter|Datum|Uhrzeit")
        organizer = field(text, "Veranstalter", "Datum|Uhrzeit|Ort")
        title = text[:date_match.start()].strip(" |;-")
        title = re.sub(r"^\s*Termine\s*", "", title, flags=re.I).strip()
        if not title:
            raise ValueError(f"Termin ohne Titel: {text[:200]}")
        day = datetime.strptime(raw_date, "%d.%m.%Y").date()
        start = datetime.combine(day, datetime.strptime(time_match.group(0), "%H:%M").time(), TZ) if time_match else None
        # Ohne explizite Uhrzeit als ganztägig behandeln; 00:00 bleibt 00:00.
        detail_link = next((urljoin(url, a["href"]) for a in tr.select("a[href]")), url)
        events.append(dict(title=title, day=day, start=start, location=place,
                           organizer=organizer, url=detail_link))

    page_indices = set()
    for a in soup.select('a[href*="wilma_pzl_doclist_page1408"]'):
        href = urljoin(url, a["href"])
        for value in parse_qs(urlparse(href).query).get("wilma_pzl_doclist_page1408", []):
            if value.isdigit():
                page_indices.add(int(value))
    return events, page_indices


def retrieve() -> list[dict]:
    session = requests.Session()
    session.headers.update(HEADERS)
    found = {}
    visited_signatures = set()
    for page in range(MAX_PAGES):
        params = {"pgId": "645"}
        if page:
            params["wilma_pzl_doclist_page1408"] = str(page)
        response = session.get("https://www.wilsdruff.de/wilma.aspx", params=params, timeout=35)
        response.raise_for_status()
        events, page_indices = parse_page(response.content, response.url)
        print(f"Seite {page + 1}: {len(events)} Termine, Seitennavigation {sorted(page_indices)}")
        if not events:
            if page == 0:
                raise ValueError("Keine Termine auf der Startseite – Export wird abgebrochen")
            break
        signature = tuple((e["title"], str(e["day"]), str(e["start"])) for e in events)
        if signature in visited_signatures:
            break
        visited_signatures.add(signature)
        for event in events:
            key = (event["title"], event["day"], event["location"])
            found[key] = event
        if page + 1 not in page_indices:
            break
    else:
        raise ValueError("Seitengrenze erreicht; möglicherweise nicht alle Termine gelesen")
    if not found:
        raise ValueError("Keine Termine erkannt")
    return sorted(found.values(), key=lambda e: (e["day"], e["title"]))


def escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")


def fold(line: str) -> list[str]:
    # RFC 5545: maximal 75 Oktette pro physischer Zeile
    chunks, current = [], ""
    for char in line:
        candidate = current + char
        if len(candidate.encode("utf-8")) > 75:
            chunks.append(current)
            current = " " + char
        else:
            current = candidate
    chunks.append(current)
    return chunks


def calendar(events: list[dict]) -> str:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Wilsdruff Kalender//DE",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             "X-WR-CALNAME:Wilsdruff – Termine",
             "X-WR-TIMEZONE:Europe/Berlin"]
    stamp = datetime.now(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")
    for e in events:
        identifier = hashlib.sha256(f'{e["title"]}|{e["day"]}|{e["location"]}'.encode()).hexdigest()[:24]
        lines.extend(["BEGIN:VEVENT", f"UID:{identifier}@wilsdruff-kalender",
                      f"DTSTAMP:{stamp}", f"SUMMARY:{escape(e['title'])}"])
        if e["start"] is None:
            lines.extend([f"DTSTART;VALUE=DATE:{e['day']:%Y%m%d}",
                          f"DTEND;VALUE=DATE:{e['day'] + timedelta(days=1):%Y%m%d}"])
        else:
            # Endzeit nicht veröffentlicht: 60 Minuten als technische Annahme
            start = e["start"].astimezone(ZoneInfo("UTC"))
            end = (e["start"] + timedelta(hours=1)).astimezone(ZoneInfo("UTC"))
            lines.extend([f"DTSTART:{start:%Y%m%dT%H%M%SZ}",
                          f"DTEND:{end:%Y%m%dT%H%M%SZ}"])
        if e["location"]:
            lines.append(f"LOCATION:{escape(e['location'])}")
        if e["organizer"]:
            lines.append(f"DESCRIPTION:{escape('Veranstalter: ' + e['organizer'])}")
        lines.append(f"URL:{e['url']}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(part for line in lines for part in fold(line)) + "\r\n"


def main() -> int:
    try:
        events = retrieve()
        print(f"Insgesamt: {len(events)} unterschiedliche Termine")
        for event in events[:10]:
            print(event["day"], event["start"].strftime("%H:%M") if event["start"] else "ganztägig", event["title"])
        output = calendar(events)
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_bytes(output.encode("utf-8"))
        print(f"Erzeugt: {OUTPUT} ({len(output.encode('utf-8'))} Bytes)")
        return 0
    except (requests.RequestException, ValueError) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

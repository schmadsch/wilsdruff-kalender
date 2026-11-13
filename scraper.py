#!/usr/bin/env python3
"""Städtische Termine und Veranstaltungen als iCalendar exportieren.

Quellen: Verwaltung (pgId=645), Leben/Veranstaltungen (pgId=20).
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

SOURCES = [("Verwaltung", 645), ("Veranstaltungen", 20)]
TZ = ZoneInfo("Europe/Berlin")
OUTPUT = Path("docs/wilsdruff.ics")
MAX_PAGES = 30
DATE_RE = re.compile(r"\b([0-3]?\d\.[01]?\d\.20\d{2})\b")
TIME_RE = re.compile(r"\b([0-2]?\d:[0-5]\d)\b")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; WilsdruffKalender/0.3; +https://github.com/schmadsch/wilsdruff-kalender)"}


def fields_from_row(row) -> dict[str, str]:
    """Werte auch dann lesen, wenn die Felder anders angeordnet sind."""
    text = row.get_text(" ", strip=True)
    labels = ("Datum", "Uhrzeit", "Ort", "Ortszusatz", "Veranstalter")
    label_expr = "|".join(labels)
    matches = list(re.finditer(rf"(?<!\\w)({label_expr})\\s*:", text, re.I))
    result = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        result[match.group(1).lower()] = text[match.end():end].strip(" |;-")
    return result


def parse_page(html: bytes, url: str) -> tuple[list[dict], set[int], str | None]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.idu-cm3-wilma-puzzle-documentlist-table")
    if table is None:
        raise ValueError("Terminliste nicht gefunden – HTML-Struktur möglicherweise geändert")

    events = []
    for tr in table.select("tr"):
        if tr.find_parent("thead"):
            continue
        text = tr.get_text(" ", strip=True)
        values = fields_from_row(tr)
        date_match = DATE_RE.search(values.get("datum", ""))
        if not date_match:
            continue
        raw_date = date_match.group(1)
        time_match = TIME_RE.search(values.get("uhrzeit", ""))
        place = values.get("ort", "")
        extra = values.get("ortszusatz", "")
        if extra:
            place = (place + ", " + extra).strip(", ")
        organizer = values.get("veranstalter", "")
        title_match = re.search(r"\\bDatum\\s*:", text, re.I)
        title = text[:title_match.start()].strip(" |;-") if title_match else ""
        title = re.sub(r"^\\s*Termine\\s*", "", title, flags=re.I).strip()
        if not title:
            raise ValueError(f"Termin ohne Titel: {text[:200]}")
        day = datetime.strptime(raw_date, "%d.%m.%Y").date()
        start = datetime.combine(day, datetime.strptime(time_match.group(0), "%H:%M").time(), TZ) if time_match else None
        detail_link = next((urljoin(url, a["href"]) for a in tr.select("a[href]")), url)
        events.append(dict(title=title, day=day, start=start, location=place,
                           organizer=organizer, url=detail_link))

    page_indices = set()
    page_param = None
    for a in soup.select('a[href*="wilma_pzl_doclist_page"]'):
        href = urljoin(url, a["href"])
        query = parse_qs(urlparse(href).query)
        for name, values in query.items():
            if name.startswith("wilma_pzl_doclist_page"):
                page_param = name
                page_indices.update(int(value) for value in values if value.isdigit())
    return events, page_indices, page_param


def retrieve() -> list[dict]:
    session = requests.Session()
    session.headers.update(HEADERS)
    found = {}
    for source_name, source_id in SOURCES:
        visited_signatures = set()
        page_param = None
        source_count = 0
        for page in range(MAX_PAGES):
            params = {"pgId": str(source_id)}
            if page:
                if page_param is None:
                    break
                params[page_param] = str(page)
            response = session.get("https://www.wilsdruff.de/wilma.aspx", params=params, timeout=35)
            response.raise_for_status()
            events, page_indices, discovered_param = parse_page(response.content, response.url)
            page_param = discovered_param or page_param
            print(f"{source_name}, Seite {page + 1}: {len(events)} Termine, Seitennavigation {sorted(page_indices)}")
            if not events:
                if page == 0:
                    raise ValueError(f"{source_name}: Keine Termine erkannt – Export abgebrochen")
                break
            signature = tuple((e["title"], str(e["day"]), str(e["start"])) for e in events)
            if signature in visited_signatures:
                break
            visited_signatures.add(signature)
            source_count += len(events)
            for event in events:
                # Erste Quelle gewinnt: UID und Ort bestehender Termine bleiben stabil.
                key = (re.sub(r"\\s+", " ", event["title"]).casefold(), event["day"])
                if key not in found:
                    found[key] = event
            if page + 1 not in page_indices:
                break
        else:
            raise ValueError(f"{source_name}: Seitengrenze erreicht")
        print(f"{source_name}: {source_count} Einträge vor Dublettenprüfung")
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
             "X-WR-CALNAME:Wilsdruff – Termine und Veranstaltungen",
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

"""Scrape SUUMO rental listings for Setagaya into data/YYYY-MM-DD.csv."""
import csv
import datetime
import os
import sys
import time

import requests
from bs4 import BeautifulSoup

BASE = "https://suumo.jp"
URL = BASE + "/chintai/tokyo/sc_setagaya/"
PAGES = 3  # shortcut: first few pages only (~300 units), raise once GitHub runners prove they aren't blocked
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"}
FIELDS = ["id", "name", "address", "access", "age_floors", "floor", "rent", "admin_fee",
          "deposit", "key_money", "layout", "area", "url"]


def text(el):
    return el.get_text(" ", strip=True) if el else ""


def parse(html):
    rows = []
    for b in BeautifulSoup(html, "html.parser").select(".cassetteitem"):
        building = {
            "name": text(b.select_one(".cassetteitem_content-title")),
            "address": text(b.select_one(".cassetteitem_detail-col1")),
            "access": text(b.select_one(".cassetteitem_detail-col2")),
            "age_floors": text(b.select_one(".cassetteitem_detail-col3")),
        }
        for tr in b.select("table.cassetteitem_other tbody tr"):
            link = tr.select_one('a[href^="/chintai/"]')
            tds = tr.find_all("td")
            rows.append({
                **building,
                "id": tr.select_one("input.js-ikkatsuCB")["value"],
                "floor": text(tds[2]),
                "rent": text(tr.select_one(".cassetteitem_price--rent")),
                "admin_fee": text(tr.select_one(".cassetteitem_price--administration")),
                "deposit": text(tr.select_one(".cassetteitem_price--deposit")),
                "key_money": text(tr.select_one(".cassetteitem_price--gratuity")),
                "layout": text(tr.select_one(".cassetteitem_madori")),
                "area": text(tr.select_one(".cassetteitem_menseki")).replace("m 2", "m2"),
                "url": BASE + link["href"] if link else "",
            })
    return rows


def main():
    rows = []
    for page in range(1, PAGES + 1):
        r = requests.get(URL, params={"page": page}, headers=HEADERS, timeout=30)
        print(f"page {page}: HTTP {r.status_code}, {len(r.content)} bytes")
        r.raise_for_status()
        rows += parse(r.text)
        time.sleep(2)  # be polite

    if not rows:
        sys.exit("No listings parsed: blocked or page layout changed")

    os.makedirs("data", exist_ok=True)
    path = f"data/{datetime.date.today().isoformat()}.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} listings to {path}")


if __name__ == "__main__":
    main()

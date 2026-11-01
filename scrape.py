"""Scrape SUUMO listings into data/<type>/<ward>/YYYY-MM-DD.csv."""
import csv
import datetime
import os
import sys
import time

import requests
from bs4 import BeautifulSoup

BASE = "https://suumo.jp"
PAGES = 3  # shortcut: first few pages per search only, raise if we need full coverage
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"}

RENT_FIELDS = ["id", "name", "address", "access", "age_floors", "floor", "rent", "admin_fee",
               "deposit", "key_money", "layout", "area", "url"]
HOUSE_FIELDS = ["id", "name", "price", "address", "access", "land_area",
                "building_area", "layout", "built", "title", "url"]
HOUSE_LABELS = {"物件名": "name", "販売価格": "price", "所在地": "address", "沿線・駅": "access",
                "土地面積": "land_area", "建物面積": "building_area", "間取り": "layout", "築年月": "built"}


def text(el):
    return el.get_text(" ", strip=True) if el else ""


def parse_rent(html):
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


def parse_house(html):
    rows = []
    for u in BeautifulSoup(html, "html.parser").select(".property_unit"):
        link = u.select_one(".property_unit-title a")
        href = link["href"]  # e.g. /chukoikkodate/tokyo/sc_setagaya/nc_20933882/
        row = {
            "id": href.rstrip("/").rsplit("nc_", 1)[-1],
            "title": text(link),
            "url": BASE + href,
        }
        for dl in u.select("dl"):
            key = HOUSE_LABELS.get(text(dl.dt))
            if key:
                row[key] = text(dl.dd).replace("m 2", "m2")
        rows.append(row)
    return rows


# (SUUMO type, ward): searched at /<type>/tokyo/sc_<ward>/, saved to data/<type>/<ward>/
TARGETS = [
    ("chintai", "setagaya"),
    ("ikkodate", "setagaya"),       # new houses for sale
    ("chukoikkodate", "setagaya"),  # used houses for sale
]
# shortcut: assumes every for-sale type uses the house page layout, add a parser when adding mansion types
PARSERS = {"chintai": (parse_rent, RENT_FIELDS)}


def scrape(path, parser):
    rows = []
    for page in range(1, PAGES + 1):
        r = requests.get(BASE + path, params={"page": page}, headers=HEADERS, timeout=30)
        print(f"{path} page {page}: HTTP {r.status_code}, {len(r.content)} bytes")
        r.raise_for_status()
        rows += parser(r.text)
        time.sleep(2)  # be polite
    return rows


def main():
    failed = []
    today = datetime.date.today().isoformat()
    for kind, ward in TARGETS:
        parser, fields = PARSERS.get(kind, (parse_house, HOUSE_FIELDS))
        rows = scrape(f"/{kind}/tokyo/sc_{ward}/", parser)
        if not rows:
            failed.append(f"{kind}/{ward}")
            continue
        folder = os.path.join("data", kind, ward)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{today}.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields, restval="")
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {len(rows)} listings to {path}")

    if failed:
        sys.exit(f"No listings parsed for {', '.join(failed)}: blocked or page layout changed")


if __name__ == "__main__":
    main()

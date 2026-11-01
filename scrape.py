"""Scrape the SUUMO searches in config.yaml into data/<type>/<ward>/YYYY-MM-DD.csv."""
import csv
import datetime
import os
import re
import sys
import time

import requests
import yaml
from bs4 import BeautifulSoup

BASE = "https://suumo.jp"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"}

RENT_FIELDS = ["id", "name", "address", "access", "age_floors", "floor", "rent", "admin_fee",
               "deposit", "key_money", "layout", "area", "url"]
HOUSE_FIELDS = ["id", "name", "price", "address", "access", "land_area",
                "building_area", "layout", "built", "title", "url"]
HOUSE_LABELS = {"物件名": "name", "販売価格": "price", "所在地": "address", "沿線・駅": "access",
                "土地面積": "land_area", "建物面積": "building_area", "間取り": "layout", "築年月": "built"}

# Calculated columns are prefixed with _ to tell them apart from scraped text.
RENT_CALC = ["_rent_yen", "_admin_fee_yen", "_monthly_yen", "_deposit_yen", "_key_money_yen",
             "_move_in_yen", "_area_m2", "_yen_per_m2", "_age_years", "_building_floors", "_floor",
             "_rooms", "_walk_minutes", "_station", "_line"]
HOUSE_CALC = ["_price_yen_min", "_price_yen_max", "_land_m2_min", "_land_m2_max",
              "_building_m2_min", "_building_m2_max", "_rooms_min", "_rooms_max", "_price_per_tsubo",
              "_built_year", "_age_years", "_walk_minutes", "_station", "_line", "_is_land"]
HISTORY = ["_first_seen", "_days_listed", "_price_change"]
M2_PER_TSUBO = 3.30579


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
            **dict.fromkeys(HOUSE_LABELS.values(), ""),  # new houses have no 築年月
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


def yen(s):
    """'3億980万円' -> 309800000, '15000円' -> 15000, '-' or '未定' -> None."""
    if "円" not in s:
        return None
    oku, man = re.search(r"([\d.]+)億", s), re.search(r"([\d.]+)万", s)
    if not (oku or man):
        m = re.search(r"([\d,]+)円", s)
        return int(m[1].replace(",", "")) if m else None
    return round((float(oku[1]) * 1e8 if oku else 0) + (float(man[1]) * 1e4 if man else 0))


def span(values):
    return (min(values), max(values)) if values else (None, None)


def first_int(s):
    m = re.search(r"\d+", s)
    return int(m[0]) if m else None


def price_span(s):
    """'5980万円～7480万円' or '1億円・1億2000万円（予定）' -> (min, max); notes after （ or ※ dropped."""
    pieces = re.split("[～・]", re.split("[（※]", s)[0])
    return span([v for v in map(yen, pieces) if v])


def area_span(s):
    """'100.09m2 ～120.5m2 （30.27坪～36.45坪）' -> (100.09, 120.5); ignores 'うち車庫…' after 、."""
    return span([float(x) for x in re.findall(r"([\d.]+)\s*(?:m2|㎡)", s.split("、")[0])])


def rooms_span(s):
    """'3LDK+S（納戸）～4LDK' -> (3, 4); 'ワンルーム' -> 1."""
    return span([1 if p.startswith("ワンルーム") else first_int(p)
                 for p in re.split("[～・]", s) if p.startswith("ワンルーム") or re.match(r"\d", p)])


def nearest_station(access):
    """(line, station, walk minutes) of the closest station on foot; bus routes are ignored."""
    walks = (re.findall(r"(\S+?)/(\S+?)駅 歩(\d+)分", access)  # chintai: 小田急線/経堂駅 歩5分
             or re.findall(r"(\S+?)「(.+?)」徒歩(\d+)分", access))  # for sale: 小田急線「経堂」徒歩5分～7分
    if not walks:
        return None, None, None
    line, station, minutes = min(walks, key=lambda w: int(w[2]))
    return line, station, int(minutes)


def calc_rent(row, today):
    rent = yen(row["rent"])
    admin, deposit, key = (yen(row[k]) or 0 for k in ("admin_fee", "deposit", "key_money"))
    monthly = rent + admin if rent else None
    area = area_span(row["area"])[0]
    line, station, walk = nearest_station(row["access"])
    floor = row["floor"]  # '6階', '1-2階' (maisonette), 'B1階', '-'
    floors = re.search(r"(\d+)階建", row["age_floors"])  # '地下1地上5階建' -> 5 above ground
    return {
        "_rent_yen": rent,
        "_admin_fee_yen": admin,
        "_monthly_yen": monthly,
        "_deposit_yen": deposit,
        "_key_money_yen": key,
        # shortcut: excludes agency fee, insurance and lock change, which the list page doesn't show
        "_move_in_yen": deposit + key + monthly if monthly else None,
        "_area_m2": area,
        "_yen_per_m2": round(monthly / area) if monthly and area else None,
        "_age_years": 0 if "新築" in row["age_floors"] else first_int(row["age_floors"]),
        "_building_floors": int(floors[1]) if floors else None,
        "_floor": -first_int(floor) if floor.startswith("B") else first_int(floor),
        "_rooms": rooms_span(row["layout"])[0],
        "_walk_minutes": walk,
        "_station": station,
        "_line": line,
    }


def calc_house(row, today):
    price, land, building = price_span(row["price"]), area_span(row["land_area"]), area_span(row["building_area"])
    built = first_int(row["built"])
    line, station, walk = nearest_station(row["access"])
    single = price[0] == price[1] and land[0] == land[1]
    return {
        "_price_yen_min": price[0], "_price_yen_max": price[1],
        "_land_m2_min": land[0], "_land_m2_max": land[1],
        "_building_m2_min": building[0], "_building_m2_max": building[1],
        **dict(zip(("_rooms_min", "_rooms_max"), rooms_span(row["layout"]))),
        # only for a single price on a single plot: pairing range ends would be meaningless
        "_price_per_tsubo": round(price[0] / (land[0] / M2_PER_TSUBO)) if single and price[0] and land[0] else None,
        "_built_year": built,
        "_age_years": today.year - built if built else None,
        "_walk_minutes": walk,
        "_station": station,
        "_line": line,
        "_is_land": "/tochi/" in row["url"],  # land sold with a build condition, mixed into ikkodate
    }


def add_history(rows, folder, today, price_key):
    """Fill _first_seen from the previous CSV in folder. On the first snapshot every row stays null,
    so a date only appears on listings that showed up after scraping began. CSVs from before the
    history columns existed don't count: they used a different sort order, so aren't comparable."""
    earlier = sorted(f for f in os.listdir(folder) if f.endswith(".csv") and f < f"{today.isoformat()}.csv") \
        if os.path.isdir(folder) else []
    if not earlier:
        return
    with open(os.path.join(folder, earlier[-1]), encoding="utf-8") as f:
        reader = csv.DictReader(f)
        prev = {r["id"]: r for r in reader}
    if "_first_seen" not in (reader.fieldnames or []):  # checks the header, so an empty CSV still counts
        return
    for row in rows:
        p = prev.get(row["id"])
        # shortcut: only compares with the latest earlier file, so a listing missing for a night
        # (or pushed past the scraped pages) comes back as new; compare against all files if that gets noisy
        first = (p.get("_first_seen") or None) if p else today.isoformat()
        old_price = int(p[price_key]) if p and p[price_key] else None
        row["_first_seen"] = first
        row["_days_listed"] = (today - datetime.date.fromisoformat(first)).days if first else None
        row["_price_change"] = row[price_key] - old_price if old_price and row[price_key] else None


TYPES = ("chintai", "ikkodate", "chukoikkodate")  # add a parser before adding e.g. mansion
NO_MATCH = "条件にあう物件がありません"  # SUUMO's "no listings match" message
# type -> (parser, scraped columns, calculated columns, calculator, column used for _price_change)
PARSERS = {"chintai": (parse_rent, RENT_FIELDS, RENT_CALC, calc_rent, "_monthly_yen")}
HOUSE = (parse_house, HOUSE_FIELDS, HOUSE_CALC, calc_house, "_price_yen_min")
# Newest first, so the scraped pages hold the latest listings and _first_seen isn't fooled by
# SUUMO's default "recommended" order shuffling listings in and out of those pages.
SORT = {"chintai": {"po1": "09", "po2": "99"}}  # 新着順
HOUSE_SORT = {"po": "1", "pj": "2"}  # 新着・更新順: updated old listings also rise, so a few false "new"

# config.yaml filter name -> (SUUMO query param, values SUUMO's dropdowns accept)
RENT_MAN = [f"{x / 2:.1f}" for x in range(6, 40)] + [f"{x:.1f}" for x in [*range(20, 31), 35, 40, 50, 100]]
RENT_AREA = [str(x) for x in [*range(20, 71, 5), 80, 90, 100]]
HOUSE_PRICE = [str(x) for x in [*range(500, 8001, 500), 9000, 10000]]
HOUSE_AREA = [str(x) for x in range(60, 151, 10)]
FILTERS = {"chintai": {
    "min_rent": ("cb", RENT_MAN), "max_rent": ("ct", RENT_MAN),
    "min_area": ("mb", RENT_AREA), "max_area": ("mt", RENT_AREA),
    "max_walk": ("et", ["1", "5", "7", "10", "15", "20"]),
    "max_age": ("cn", ["0", "1", "3", "5", "7", "10", "15", "20", "25", "30"]),
    "south_facing": ("tc", "0400104"),  # 南向き: includes south-east and south-west
    "reinforced_concrete": ("kz", "1"),  # 鉄筋系: RC and SRC
}}
HOUSE_FILTERS = {
    "min_price": ("kb", HOUSE_PRICE), "max_price": ("kt", HOUSE_PRICE + ["12000"]),
    "min_building_area": ("hb", HOUSE_AREA), "max_building_area": ("ht", HOUSE_AREA),
    "min_land_area": ("tb", HOUSE_AREA), "max_land_area": ("tt", HOUSE_AREA),
    "max_walk": ("et", ["1", "3", "5", "7", "10", "15", "20"]),
    "max_age": ("cn", ["3", "5", "7", "10", "15", "20", "25", "30"]),  # chukoikkodate only
    "south_facing": ("mh", "151"),  # 南向き feature tag set by the agency, not a direction field
}


def suumo_params(kind, filters):
    """{'max_rent': 25} -> {'ct': '25.0'}, rejecting values SUUMO would silently ignore."""
    spec = FILTERS.get(kind, HOUSE_FILTERS)
    params = {}
    for name, value in filters.items():
        if name not in spec:
            raise ValueError(f"{kind}: unknown filter {name!r}, use one of {', '.join(spec)}")
        param, allowed = spec[name]
        if isinstance(allowed, str):  # on/off option, e.g. south_facing: true
            if not isinstance(value, bool):
                raise ValueError(f"{kind}: {name} must be true or false, got {value!r}")
            if value:
                params[param] = allowed
            continue
        value = f"{float(value):.1f}" if allowed is RENT_MAN else str(value)  # SUUMO wants rent as 25.0
        if value not in allowed:
            raise ValueError(f"{kind}: {name}={value} isn't a SUUMO option, use one of {', '.join(allowed)}")
        params[param] = value
    return params


def load_config(path):
    """-> (pages, [(type, ward, SUUMO filter params)])"""
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    targets = []
    for kind, search in cfg["searches"].items():
        if kind not in TYPES:
            raise ValueError(f"unknown type {kind!r}, use one of {', '.join(TYPES)}")
        params = suumo_params(kind, search.get("filters") or {})
        targets += [(kind, ward, params) for ward in search["wards"]]
    return cfg.get("pages", 3), targets


def scrape(path, parser, params, pages):
    rows = []
    for page in range(1, pages + 1):
        time.sleep(2)  # be polite
        r = requests.get(BASE + path, params={**params, "page": page}, headers=HEADERS, timeout=30)
        print(f"{path} page {page}: HTTP {r.status_code}, {len(r.content)} bytes")
        r.raise_for_status()
        found = parser(r.text)
        if not found:
            if NO_MATCH in r.text:  # past the last page, or the filters match nothing
                break
            raise RuntimeError(f"{path} page {page}: no listings parsed, blocked or page layout changed")
        rows += found
    return rows


def main():
    pages, targets = load_config(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml"))
    failed = []
    today = datetime.date.today()
    for kind, ward, filters in targets:
        parser, fields, calc_fields, calc, price_key = PARSERS.get(kind, HOUSE)
        try:
            rows = scrape(f"/{kind}/tokyo/sc_{ward}/", parser, {**SORT.get(kind, HOUSE_SORT), **filters}, pages)
        except (RuntimeError, requests.RequestException) as e:  # e.g. a mistyped ward, keep the other searches going
            failed.append(f"{kind}/{ward}: {e}")
            continue
        for row in rows:
            row.update(calc(row, today))
        folder = os.path.join("data", kind, ward)
        add_history(rows, folder, today, price_key)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{today.isoformat()}.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields + calc_fields + HISTORY, restval="")
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {len(rows)} listings to {path}")

    if failed:
        sys.exit("Failed searches:\n" + "\n".join(failed))


if __name__ == "__main__":
    main()

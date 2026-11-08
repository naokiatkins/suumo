# suumo

A nightly GitHub Actions job that scrapes Tokyo rental and house-for-sale listings from [SUUMO](https://suumo.jp) and commits them to this repo as CSV files.

## How it works

`.github/workflows/scrape.yml` runs every night, and can also be started from the Actions tab. It runs the self-checks, then scrapes, then commits whatever is in `data/`. If one search fails, the others still run and their data is still committed, but the job is then marked as failed.

Results go to `data/<type>/<ward>/<UTC timestamp>.csv`, for example `data/chintai/setagaya/2026-11-02T171509Z.csv`. Each search writes its own file, so two searches covering the same ward never overwrite each other.

| Folder | What it holds |
|---|---|
| `chintai` | Rentals |
| `ikkodate` | New houses for sale |
| `chukoikkodate` | Used houses for sale |

## Configuring searches

Everything is set in [config.yaml](config.yaml). There are two ways to add a search.

**Ward searches** take a list of wards and a set of filters for each type. Wards use the name after `sc_` in SUUMO's URLs, e.g. `setagaya`. SUUMO only accepts the values in its own dropdowns and silently returns nothing for anything else, so the scraper rejects invalid values up front. The allowed values are listed in config.yaml's comments.

```yaml
searches:
  chintai:
    wards: [setagaya, shibuya]
    filters: {max_rent: 16, min_area: 40, max_walk: 15, south_facing: true}
```

**Custom URLs** let you set up a search on SUUMO's site and paste the URL of its results page. Rent, new house and used house searches are supported. The scraper replaces the URL's sort with newest first, and files each listing in the folder for its ward, taken from its address. Listings outside the 23 wards go to `other/`.

```yaml
custom:
  - url: https://suumo.jp/jj/chintai/ichiran/FR301FC001/?ar=030&bs=040&sc=13112&sc=13113&...
    pages: 15
```

`pages` sets how many result pages to fetch, newest first. One `pages` value covers every ward in a custom URL, so a busy ward can crowd out a quiet one.

## Columns

Scraped columns hold SUUMO's text as shown. Columns starting with `_` are calculated from it:

- Rentals:
  - money in yen: `_monthly_yen` (rent plus admin fee), `_move_in_yen`, `_yen_per_m2`
  - the flat: `_area_m2`, `_age_years`, `_floor`, `_rooms`
  - the nearest station on foot: `_walk_minutes`, `_station`, `_line`
- Houses:
  - ranges shown as `_min`/`_max` pairs: price, land area, building area, rooms
  - `_price_per_tsubo`, `_built_year` and `_age_years`
  - `_is_land`, which marks land plots that SUUMO mixes into the new-house results
- History, compared with earlier files in the same folder:
  - `_first_seen`: the day the listing first appeared
  - `_days_listed`: how many days it has been listed
  - `_price_change`: how much the price changed since it was last seen

  Listings already there on the first snapshot have no `_first_seen`, since the scraper can't know when they were listed.

## Running locally

```bash
pip install -r requirements.txt
```

```bash
python test_scrape.py
```

```bash
python scrape.py
```

The scraper waits 2 seconds between page requests.

## Viewing results

`app.py` is a Streamlit app for browsing the latest day's listings in each ward. It has:
- filters for type, ward, price, area, walking time, new listings only, and text;
- a sortable table with links to SUUMO;
- a Charts tab: price against area, median price per area by ward, and listings seen each day.

```bash
pip install -r requirements-app.txt
```

```bash
streamlit run app.py
```

The nightly job doesn't need these packages, which is why they're in a separate requirements file.

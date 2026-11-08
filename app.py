"""Browse the scraped listings in data/. Run: streamlit run app.py"""
import glob
import os

import pandas as pd
import streamlit as st

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
TYPES = {"Rent": "chintai", "New houses": "ikkodate", "Used houses": "chukoikkodate"}
# (price column, area column, value-for-money column) for each type
RENT = ("_monthly_yen", "_area_m2", "_yen_per_m2")
HOUSE = ("_price_yen_min", "_building_m2_min", "_price_per_tsubo")
TABLE = {
    "chintai": ["name", "_ward", "_station", "_walk_minutes", "layout", "_area_m2", "_monthly_yen", "_move_in_yen",
                "_yen_per_m2", "_age_years", "_floor", "_first_seen", "_days_listed", "_price_change", "url"],
    "house": ["title", "_ward", "_station", "_walk_minutes", "layout", "_price_yen_min", "_land_m2_min",
              "_building_m2_min", "_price_per_tsubo", "_age_years", "_is_land", "_first_seen", "_days_listed",
              "_price_change", "url"],
}
LABELS = {"name": "Building", "title": "Listing", "_ward": "Ward", "_station": "Station", "_walk_minutes": "Walk min",
          "layout": "Layout", "_area_m2": "m²", "_monthly_yen": "Monthly ¥", "_move_in_yen": "Move-in ¥",
          "_yen_per_m2": "¥/m²", "_age_years": "Age", "_floor": "Floor", "_first_seen": "First seen",
          "_days_listed": "Days listed", "_price_change": "Change ¥", "_price_yen_min": "Price ¥",
          "_land_m2_min": "Land m²", "_building_m2_min": "Building m²", "_price_per_tsubo": "¥/tsubo",
          "_is_land": "Land only"}


@st.cache_data
def load(files):
    """Every CSV of one type in one frame, tagged with its ward, day and file. files is part of the
    cache key, so a new nightly CSV reloads."""
    frames = [pd.read_csv(f, dtype={"id": str}).assign(_ward=f.split(os.sep)[-2], _file=os.path.basename(f))
              for f in files]
    df = pd.concat(frames, ignore_index=True)
    df["_day"] = df["_file"].str[:10]
    return df


def latest(df):
    """Each ward's latest day, merged across searches. A date-only file comes from before files were
    timestamped, possibly with an older config, so it's skipped when that day also has timestamped ones."""
    df = df[df["_day"] == df.groupby("_ward")["_day"].transform("max")]
    stamped = df["_file"].str.contains("T")
    df = df[stamped | ~stamped.groupby(df["_ward"]).transform("any")]
    return df.sort_values("_file").drop_duplicates(["_ward", "id"], keep="last")


def in_range(series, lo, hi):
    return series.isna() | series.between(lo, hi)  # keep listings with no value, e.g. price 未定


st.set_page_config(page_title="SUUMO listings", layout="wide")
st.title("SUUMO listings")

kind = TYPES[st.sidebar.radio("Type", list(TYPES))]
files = sorted(glob.glob(os.path.join(DATA, kind, "*", "*.csv")))
if not files:
    st.info(f"No data yet in data/{kind}/. Run python scrape.py first.")
    st.stop()
history = load(files)
df = latest(history)
price, area, value = RENT if kind == "chintai" else HOUSE

wards = sorted(df["_ward"].unique())
picked = st.sidebar.multiselect("Wards", wards, default=wards)
query = st.sidebar.text_input("Search name, station or address")
lo_p, hi_p = int(df[price].fillna(0).min()) // 10000, -(-int(df[price].fillna(0).max()) // 10000)
p = st.sidebar.slider("Price (万円)", lo_p, max(hi_p, lo_p + 1), (lo_p, max(hi_p, lo_p + 1)))
hi_a = int(df[area].fillna(0).max()) + 1
a = st.sidebar.slider("Area (m²)", 0, hi_a, (0, hi_a))
walk = st.sidebar.slider("Max walk (min)", 1, 30, 30)
only_new = st.sidebar.checkbox("New listings only")

shown = df[df["_ward"].isin(picked)
           & in_range(df[price], p[0] * 10000, p[1] * 10000)
           & in_range(df[area], *a)
           & in_range(df["_walk_minutes"], 0, walk)]
if walk < 30:  # bus-only listings have no walk time, so hide them once a limit is set
    shown = shown[shown["_walk_minutes"].notna()]
if only_new:
    shown = shown[shown["_first_seen"] == shown["_day"]]
if query:
    text = shown.reindex(columns=["name", "title", "address", "access"]).fillna("").astype(str).agg(" ".join, axis=1)
    shown = shown[text.str.contains(query, case=False, regex=False)]

new = (df["_first_seen"] == df["_day"]).sum()
st.caption(f"{len(shown)} of {len(df)} listings · {new} new · latest snapshot {df['_day'].max()}")

listings, charts = st.tabs(["Listings", "Charts"])
with listings:
    cols = TABLE["chintai" if kind == "chintai" else "house"]
    st.dataframe(
        shown[cols].rename(columns=LABELS),
        hide_index=True, use_container_width=True, height=600,
        column_config={"url": st.column_config.LinkColumn("SUUMO", display_text="open")},
    )

with charts:
    st.subheader("Price against area")
    st.scatter_chart(shown.rename(columns={"_ward": "Ward"}), x=area, y=price, color="Ward",
                     x_label=LABELS[area], y_label=LABELS[price])
    st.subheader(f"Median {LABELS[value]} by ward")
    st.bar_chart(shown.groupby("_ward")[value].median(), x_label="Ward", y_label=LABELS[value])
    st.subheader("Listings seen each day")
    counts = history[history["_ward"].isin(picked)].groupby(["_day", "_ward"])["id"].nunique().unstack()
    st.line_chart(counts, x_label="Day", y_label="Listings")

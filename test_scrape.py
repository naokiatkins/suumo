"""Self-checks for the value parsers, using formats seen on SUUMO. Run: python test_scrape.py"""
import datetime
import os
import tempfile

from scrape import add_history, area_span, calc_rent, nearest_station, price_span, rooms_span, yen

assert yen("33.5万円") == 335000
assert yen("15000円") == 15000
assert yen("3億980万円") == 309800000
assert yen("1億円") == 100000000
assert yen("-") is None and yen("未定") is None

assert price_span("5980万円") == (59800000, 59800000)
assert price_span("1億2980万円～1億4980万円") == (129800000, 149800000)
assert price_span("8980万円・1億1980万円") == (89800000, 119800000)
assert price_span("7980万円～1億2000万円台（予定）※1000万円単位") == (79800000, 120000000)
assert price_span("未定") == (None, None)

assert area_span("70.47m2") == (70.47, 70.47)
assert area_span("100.09m2 ～120.5m2 （30.27坪～36.45坪）（登記）") == (100.09, 120.5)
assert area_span("85.2m2 （25.77坪）（登記）、うち1階車庫12.5m2") == (85.2, 85.2)
assert area_span("98.5㎡（29.79坪）（登記）、路地状部分：12㎡含") == (98.5, 98.5)

assert rooms_span("ワンルーム") == (1, 1)
assert rooms_span("3LDK+2S（納戸）～4LDK") == (3, 4)
assert rooms_span("2LLDDKK") == (2, 2)
assert rooms_span("-") == (None, None)

assert nearest_station("小田急線/祖師ヶ谷大蔵駅 歩10分 小田急線/成城学園前駅 歩16分") == ("小田急線", "祖師ヶ谷大蔵", 10)
assert nearest_station("小田急線/成城学園前駅 歩14分 京王線/仙川駅 バス5分 (バス停)成城八丁目 歩5分") == ("小田急線", "成城学園前", 14)
assert nearest_station("小田急線「経堂」徒歩15分～17分") == ("小田急線", "経堂", 15)
assert nearest_station("小田急線「狛江」バス18分停歩2分") == (None, None, None)

today = datetime.date(2026, 11, 3)
rent = {"rent": "10万円", "admin_fee": "-", "deposit": "10万円", "key_money": "-", "area": "25m2",
        "access": "京王線/笹塚駅 歩5分", "age_floors": "築9年 地下1地上5階建", "floor": "B1階", "layout": "1K"}
c = calc_rent(rent, today)
assert (c["_monthly_yen"], c["_move_in_yen"], c["_yen_per_m2"]) == (100000, 200000, 4000)
assert (c["_age_years"], c["_building_floors"], c["_floor"]) == (9, 5, -1)
assert calc_rent({**rent, "age_floors": "新築 3階建", "floor": "1-2階"}, today)["_age_years"] == 0

with tempfile.TemporaryDirectory() as folder:
    rows = [{"id": "1", **rent, **c}]
    add_history(rows, folder, today, "_monthly_yen")
    assert "_first_seen" not in rows[0]  # first snapshot: history stays null
    with open(os.path.join(folder, "2026-10-31.csv"), "w", encoding="utf-8") as f:
        f.write("id,rent\n1,9万円\n")
    add_history(rows, folder, today, "_monthly_yen")
    assert "_first_seen" not in rows[0]  # pre-history CSV isn't a baseline
    with open(os.path.join(folder, "2026-11-01.csv"), "w", encoding="utf-8") as f:
        f.write("id,_monthly_yen,_first_seen\n1,90000,\n")
    rows = [{"id": "1", **rent, **c}, {"id": "2", **rent, **c}]
    add_history(rows, folder, today, "_monthly_yen")
    assert (rows[0]["_first_seen"], rows[0]["_price_change"]) == (None, 10000)
    assert (rows[1]["_first_seen"], rows[1]["_days_listed"], rows[1]["_price_change"]) == ("2026-11-03", 0, None)

print("ok")

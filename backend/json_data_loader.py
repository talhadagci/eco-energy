import json
import os
import pandas as pd
from datetime import datetime, timedelta

# Mapping from JSON IDs to our internal IDs
ID_MAP = {
    "OKUL_1": "school_1",
    "CAMI_1": "mosque_1",
    "EV_1": "house_1",
    "EV_2": "house_2",
    "EV_3": "house_3",
    "EV_4": "house_4",
    "EV_5": "house_5",
}

MONTH_MAP = {
    "Ocak": "01", "Şubat": "02", "Mart": "03", "Nisan": "04",
    "Mayıs": "05", "Haziran": "06", "Temmuz": "07", "Ağustos": "08",
    "Eylül": "09", "Ekim": "10", "Kasım": "11", "Aralık": "12"
}

def load_json_data():
    file_path = os.path.join(os.path.dirname(__file__), "..", "data", "90_gunluk_detayli_veri.json")
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    daily_records = []
    period_records = []

    start_date = datetime(2026, 1, 1)

    for i, day_data in enumerate(data):
        current_date = start_date + timedelta(days=i)
        date_str = current_date.strftime("%Y-%m-%d")

        daily_agg = {}
        daily_tip = {}

        for period in day_data["periyotlar"]:
            time_range = period["saat_dilimi"]
            for b in period["binalar"]:
                b_id = ID_MAP.get(b["id"], b["id"])
                tip = b["tip"]

                period_records.append({
                    "node_id": b_id,
                    "date": date_str,
                    "time": time_range,
                    "tip": tip,
                    "consumption_kwh": b["tuketim_kwh"],
                    "solar_kwh": b["uretim_kwh"]
                })

                if b_id not in daily_agg:
                    daily_agg[b_id] = {"cons": 0.0, "solar": 0.0}
                    daily_tip[b_id] = tip
                daily_agg[b_id]["cons"] += b["tuketim_kwh"]
                daily_agg[b_id]["solar"] += b["uretim_kwh"]

        for b_id, vals in daily_agg.items():
            daily_records.append({
                "node_id": b_id,
                "date": date_str,
                "tip": daily_tip[b_id],
                "consumption_kwh": round(vals["cons"], 2),
                "solar_kwh": round(vals["solar"], 2)
            })

    return pd.DataFrame(daily_records), pd.DataFrame(period_records)

# Cache data
_daily_df, _period_df = None, None

def get_data():
    global _daily_df, _period_df
    if _daily_df is None:
        _daily_df, _period_df = load_json_data()
    return _daily_df, _period_df

def get_latest_period_stats(node_id: str):
    _, period_df = get_data()
    node_periods = period_df[period_df["node_id"] == node_id]
    if node_periods.empty:
        return 0.0, 0.0
    latest = node_periods.iloc[-1]
    return float(latest["consumption_kwh"]), float(latest["solar_kwh"])

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

try:
    from json_data_loader import get_data
except ImportError:
    get_data = None

np.random.seed(42)

# Monthly seasonal multipliers per building type (index 0=Jan … 11=Dec)
_MONTHLY_FACTORS = {
    "house":     [1.20, 1.15, 1.00, 0.90, 0.85, 0.88, 1.05, 1.08, 0.95, 0.90, 1.05, 1.20],
    "school":    [1.10, 1.10, 1.05, 1.00, 1.00, 0.45, 0.15, 0.15, 1.00, 1.05, 1.10, 1.10],
    "mosque":    [1.15, 1.10, 1.05, 1.00, 0.95, 0.90, 0.88, 0.90, 0.95, 1.00, 1.05, 1.15],
    "apartment": [1.30, 1.25, 1.05, 0.90, 0.85, 0.95, 1.15, 1.18, 0.95, 0.88, 1.05, 1.25],
    "market":    [1.00, 0.98, 0.97, 0.96, 0.98, 1.05, 1.10, 1.10, 1.02, 0.98, 0.97, 1.00],
    "office":    [1.10, 1.10, 1.05, 1.00, 1.00, 0.65, 0.50, 0.55, 1.00, 1.05, 1.10, 1.10],
}

# Weekday multipliers per building type (0=Mon … 6=Sun)
_WEEKLY_FACTORS = {
    "house":     [0.85, 0.82, 0.83, 0.84, 0.88, 1.15, 1.18],
    "school":    [1.10, 1.10, 1.10, 1.10, 1.05, 0.25, 0.20],
    "mosque":    [0.95, 0.95, 0.95, 0.95, 1.30, 0.95, 1.05],
    "apartment": [0.88, 0.85, 0.85, 0.85, 0.90, 1.20, 1.22],
    "market":    [1.00, 1.00, 1.00, 1.00, 1.05, 1.08, 0.90],
    "office":    [1.10, 1.10, 1.10, 1.10, 1.00, 0.30, 0.25],
}

# ── Isparta / Güneş Sokak mahallesi ────────────────────────────────
NODES = [
    {"id": "house_1",     "name": "Ev 1",     "type": "house",     "lat": 37.7658, "lon": 30.5530, "base_consumption": 12.5, "base_solar": 4.2},
    {"id": "house_2",     "name": "Ev 2",     "type": "house",     "lat": 37.7658, "lon": 30.5534, "base_consumption": 14.1, "base_solar": 3.8},
    {"id": "house_3",     "name": "Ev 3",     "type": "house",     "lat": 37.7658, "lon": 30.5538, "base_consumption": 10.8, "base_solar": 5.1},
    {"id": "house_4",     "name": "Ev 4",     "type": "house",     "lat": 37.7658, "lon": 30.5542, "base_consumption": 16.3, "base_solar": 6.0},
    {"id": "house_5",     "name": "Ev 5",     "type": "house",     "lat": 37.7658, "lon": 30.5546, "base_consumption": 11.5, "base_solar": 0.0},
    {"id": "mosque_1",    "name": "Cami",     "type": "mosque",    "lat": 37.7655, "lon": 30.5555, "base_consumption": 35,  "base_solar":  8.0},
    {"id": "school_1",    "name": "Okul",     "type": "school",    "lat": 37.7645, "lon": 30.5525, "base_consumption": 55,  "base_solar": 12.0},
    # Güneş paneli olmayan yeni binalar
    {"id": "apartment_1", "name": "Apartman", "type": "apartment", "lat": 37.7650, "lon": 30.5548, "base_consumption": 38,  "base_solar":  0.0},
    {"id": "market_1",    "name": "Market",   "type": "market",    "lat": 37.7652, "lon": 30.5560, "base_consumption": 21,  "base_solar":  0.0},
    {"id": "office_1",    "name": "Ofis",     "type": "office",    "lat": 37.7660, "lon": 30.5562, "base_consumption": 17,  "base_solar":  0.0},
]


def generate_node_data(node: dict, days: int = 1095) -> pd.DataFrame:
    records = []
    
    # 1. LOAD FROM JSON FIRST (up to 90 days)
    json_days_count = 0
    if get_data:
        daily_df, _ = get_data()
        node_df = daily_df[daily_df["node_id"] == node["id"]].copy()
        if not node_df.empty:
            records = node_df.to_dict(orient="records")
            json_days_count = len(records)

    # 2. FILL REMAINING DAYS WITH SYNTHETIC DATA
    if json_days_count < days:
        base_c = node["base_consumption"]
        base_s = node["base_solar"]
        node_type = node.get("type", "house")
        monthly_f = _MONTHLY_FACTORS.get(node_type, _MONTHLY_FACTORS["house"])
        weekly_f  = _WEEKLY_FACTORS.get(node_type, _WEEKLY_FACTORS["house"])

        for i in range(json_days_count, days):
            date = datetime(2026, 1, 1) + timedelta(days=i)

            # Type-specific seasonal + weekly pattern
            seasonal_c = monthly_f[date.month - 1] - 1.0
            weekly     = weekly_f[date.weekday()] - 1.0
            sub_monthly = 0.08 * np.sin(2 * np.pi * i / 25)
            noise_c    = np.random.normal(0, 0.09)
            trend      = 0.0006 * i
            factor_c   = 1 + seasonal_c + weekly + sub_monthly + noise_c + trend
            cons = max(0.1, round(base_c * factor_c, 2))

            # Solar Logic (unchanged — type-independent, driven by base_solar)
            seasonal_s = 0.35 * np.sin(2 * np.pi * (date.timetuple().tm_yday - 170) / 365)
            noise_s     = np.random.normal(0, 0.15)
            cloud_factor = 0.10 if np.random.random() < 0.15 else 1.0
            solar = round(max(0.0, base_s * (1 + seasonal_s + noise_s) * cloud_factor), 2)
            
            records.append({
                "node_id":         node["id"],
                "date":            date.strftime("%Y-%m-%d"),
                "consumption_kwh": cons,
                "solar_kwh":       solar
            })

    df = pd.DataFrame(records)
    if not df.empty:
        df["day_of_week"] = pd.to_datetime(df["date"]).dt.dayofweek
        df["day_of_year"] = pd.to_datetime(df["date"]).dt.dayofyear
    return df


def generate_consumption_data(node: dict, days: int = 1095) -> pd.DataFrame:
    return generate_node_data(node, days)


def generate_solar_data(node: dict, days: int = 1095) -> pd.DataFrame:
    return generate_node_data(node, days)


def get_latest_solar(node_id: str) -> float:
    node = next(n for n in NODES if n["id"] == node_id)
    df = generate_node_data(node, days=365) # Just need recent
    return float(df["solar_kwh"].iloc[-1])


def get_node_averages(node_id: str):
    node = next(n for n in NODES if n["id"] == node_id)
    df = generate_node_data(node, days=365)
    return float(df["consumption_kwh"].mean()), float(df["solar_kwh"].mean())


def get_all_data() -> pd.DataFrame:
    frames = [generate_node_data(n) for n in NODES]
    return pd.concat(frames, ignore_index=True)


def get_full_daily_data() -> pd.DataFrame:
    """JSON verisi olan node'lar için gerçek veri, yeni node'lar için sentetik 90 günlük veri döner."""
    try:
        from json_data_loader import get_data
        daily_df, _ = get_data()
        json_ids = set(daily_df["node_id"].unique())
    except Exception:
        daily_df = pd.DataFrame()
        json_ids = set()

    extra = []
    for node in NODES:
        if node["id"] not in json_ids:
            df = generate_node_data(node, days=1095).tail(90).copy()
            df["tip"] = node["type"]
            extra.append(df[["node_id", "date", "consumption_kwh", "solar_kwh", "tip"]])

    if extra:
        return pd.concat([daily_df] + extra, ignore_index=True)
    return daily_df


if __name__ == "__main__":
    df = get_all_data()
    print(f"Loaded/Generated {len(df)} rows for {len(NODES)} nodes")


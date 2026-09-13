"""
Generates synthetic retail sales data and loads it into Exasol Personal.

Run once before starting the app:
    python load_data.py
"""
import os
import ssl
import numpy as np
import pandas as pd
import pyexasol
from dotenv import load_dotenv

load_dotenv()

HOST = os.environ["EXASOL_HOST"]
PORT = os.environ["EXASOL_PORT"]
USER = os.environ["EXASOL_USER"]
PASSWORD = os.environ["EXASOL_PASSWORD"]
SCHEMA = os.environ.get("EXASOL_SCHEMA", "RETAIL")

REGIONS = ["North", "South", "East", "West", "Central"]
CATEGORIES = {
    "Electronics": ["Headphones", "Smartwatch", "Bluetooth Speaker", "Laptop Stand"],
    "Home": ["Blender", "Desk Lamp", "Air Purifier", "Cookware Set"],
    "Apparel": ["Running Shoes", "Jacket", "Backpack", "Sunglasses"],
    "Beauty": ["Face Serum", "Hair Dryer", "Makeup Kit", "Perfume"],
}
SEGMENTS = ["New", "Returning", "VIP"]


def generate_data(n_days: int = 120, rows_per_day: int = 25, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    start_date = pd.Timestamp.today().normalize() - pd.Timedelta(days=n_days)

    records = []
    order_id = 100000

    for day_offset in range(n_days):
        order_date = start_date + pd.Timedelta(days=day_offset)
        day_rows = rows_per_day + rng.integers(-5, 6)

        for _ in range(max(day_rows, 1)):
            order_id += 1
            region = rng.choice(REGIONS)
            category = rng.choice(list(CATEGORIES.keys()))
            product = rng.choice(CATEGORIES[category])
            quantity = int(rng.integers(1, 6))
            unit_price = round(float(rng.uniform(15, 250)), 2)
            segment = rng.choice(SEGMENTS, p=[0.4, 0.45, 0.15])
            is_refund = False

            records.append(
                {
                    "ORDER_ID": order_id,
                    "ORDER_DATE": order_date.date(),
                    "REGION": region,
                    "CATEGORY": category,
                    "PRODUCT": product,
                    "QUANTITY": quantity,
                    "UNIT_PRICE": unit_price,
                    "TOTAL_AMOUNT": round(quantity * unit_price, 2),
                    "CUSTOMER_SEGMENT": segment,
                    "IS_REFUND": is_refund,
                }
            )

    df = pd.DataFrame.from_records(records)

    # --- Inject deliberate anomalies for the demo ---
    # 1) A refund spike in the "East" region during one specific week.
    spike_start = start_date + pd.Timedelta(days=n_days - 25)
    spike_end = spike_start + pd.Timedelta(days=6)
    spike_mask = (
        (pd.to_datetime(df["ORDER_DATE"]) >= spike_start)
        & (pd.to_datetime(df["ORDER_DATE"]) <= spike_end)
        & (df["REGION"] == "East")
    )
    spike_idx = df[spike_mask].sample(frac=0.6, random_state=1).index
    df.loc[spike_idx, "IS_REFUND"] = True

    # 2) An unusually large single order (outlier) in the last week.
    outlier_idx = df.tail(30).sample(1, random_state=2).index
    df.loc[outlier_idx, "QUANTITY"] = 40
    df.loc[outlier_idx, "TOTAL_AMOUNT"] = df.loc[outlier_idx, "QUANTITY"] * df.loc[outlier_idx, "UNIT_PRICE"]

    return df


def main():
    df = generate_data()
    print(f"Generated {len(df)} rows.")

    dsn = f"{HOST}:{PORT}"
    conn = pyexasol.connect(
        dsn=dsn,
        user=USER,
        password=PASSWORD,
        compression=True,
        websocket_sslopt={"cert_reqs": ssl.CERT_NONE},
    )

    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    conn.execute(f"OPEN SCHEMA {SCHEMA}")

    conn.execute(
        f"""
        CREATE OR REPLACE TABLE {SCHEMA}.SALES (
            ORDER_ID DECIMAL(18,0),
            ORDER_DATE DATE,
            REGION VARCHAR(50),
            CATEGORY VARCHAR(50),
            PRODUCT VARCHAR(100),
            QUANTITY DECIMAL(9,0),
            UNIT_PRICE DECIMAL(12,2),
            TOTAL_AMOUNT DECIMAL(14,2),
            CUSTOMER_SEGMENT VARCHAR(20),
            IS_REFUND BOOLEAN
        )
        """
    )

    conn.import_from_pandas(df, (SCHEMA, "SALES"))
    count = conn.execute(f"SELECT COUNT(*) FROM {SCHEMA}.SALES").fetchone()[0]
    print(f"Loaded {count} rows into {SCHEMA}.SALES")
    conn.close()


if __name__ == "__main__":
    main()

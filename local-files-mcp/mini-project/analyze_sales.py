import pandas as pd


def total_by_customer(frame: pd.DataFrame) -> pd.Series:
    totals = frame.groupby("customer")["amount"].sum()
    return totals.sort_values(ascending=False)

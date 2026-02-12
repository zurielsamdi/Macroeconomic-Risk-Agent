from pathlib import Path
from datetime import datetime
import json

from utils.excel_writer import open_template, ensure_sheet, write_text, write_table, freeze_panes, autosize_columns_basic, TableSpec
from utils.fred_client import fetch_latest_and_prev
from utils.curve_plotter import plot_yield_curve

TEMPLATE_PATH = Path("templates/Morning_Brief_Template.xlsx")
REPORTS_DIR = Path("reports")
STATE_PATH = Path("state/last_run.json")


# FRED series for US Treasury constant maturity yields (%)
US_SERIES = [
    ("1M",  1/12, "DGS1MO"),
    ("3M",  3/12, "DGS3MO"),
    ("6M",  6/12, "DGS6MO"),
    ("1Y",  1.0,  "DGS1"),
    ("2Y",  2.0,  "DGS2"),
    ("3Y",  3.0,  "DGS3"),
    ("5Y",  5.0,  "DGS5"),
    ("7Y",  7.0,  "DGS7"),
    ("10Y", 10.0, "DGS10"),
    ("20Y", 20.0, "DGS20"),
    ("30Y", 30.0, "DGS30"),
]



def main():
    wb = open_template(TEMPLATE_PATH)

    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    file_stamp = now.strftime("%Y%m%d_%H%M%S")

    # Timestamp on Desk_Commentary
    ws_commentary = ensure_sheet(wb, "Desk_Commentary")
    write_text(ws_commentary, "B1", now_str)

    # Build Curve_US table from FRED
    rows = []
    curve_points = []  # (x_years, y_yield)

    for tenor, x_years, series_id in US_SERIES:
        (d0, y0), (d1, y1) = fetch_latest_and_prev(series_id)
        chg_bp = (y0 - y1) * 100.0
        rows.append([tenor, y0, chg_bp, d0])
        curve_points.append((x_years, y0))


    ws = ensure_sheet(wb, "Curve_US")
    cols = ["Tenor", "Yield (%)", "Chg (bp)", "As of"]
    formats = [None, "0.00", "0.0", None]

    write_table(
        ws,
        spec=TableSpec(start_row=1, start_col=1, header=True),
        columns=cols,
        rows=rows,
        number_formats=formats,
    )

    freeze_panes(ws, "A2")
    autosize_columns_basic(ws, start_col=1, end_col=4)

    # Save report
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / f"Morning_Brief_{file_stamp}.xlsx"
    curve_points.sort(key=lambda x: x[0])
    x = [p[0] for p in curve_points]
    y = [p[1] for p in curve_points]

    plot_path = REPORTS_DIR / "plots" / f"US_Curve_{file_stamp}.png"
    plot_yield_curve(x, y, "US Treasury Yield Curve", plot_path)
    print(f"Saved plot: {plot_path.resolve()}")

    wb.save(out_path)

    # Update state
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps({"last_run": now_str, "last_report": str(out_path)}, indent=2),
        encoding="utf-8",
    )

    print(f"Saved report: {out_path.resolve()}")
    print("Wrote Curve_US using FRED data.")


if __name__ == "__main__":
    main()

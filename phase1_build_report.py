from pathlib import Path
from datetime import datetime
import json

from utils.excel_writer import (
    open_template,
    ensure_sheet,
    write_text,
    write_table,
    freeze_panes,
    autosize_columns_basic,
    TableSpec,
)

TEMPLATE_PATH = Path("templates/Morning_Brief_Template.xlsx")
REPORTS_DIR = Path("reports")
STATE_PATH = Path("state/last_run.json")


def main():
    # 1) Load template (in-memory)
    wb = open_template(TEMPLATE_PATH)

    # 2) Timestamp strings
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    file_stamp = now.strftime("%Y%m%d_%H%M%S")

    # 3) Write "Last Updated" in Desk_Commentary
    ws_commentary = ensure_sheet(wb, "Desk_Commentary")
    write_text(ws_commentary, "B1", now_str)

    # 4) Write sample table: Curve_US
    ws_curve_us = ensure_sheet(wb, "Curve_US")
    curve_cols = ["Tenor", "Yield", "Chg (bp)"]
    curve_rows = [
        ["2Y", 4.25, -2.0],
        ["5Y", 4.10, -1.0],
        ["10Y", 4.05, 0.0],
        ["30Y", 4.20, 1.0],
    ]
    curve_formats = [None, "0.00", "0.0"]

    write_table(
        ws_curve_us,
        spec=TableSpec(start_row=1, start_col=1, header=True),
        columns=curve_cols,
        rows=curve_rows,
        number_formats=curve_formats,
    )
    freeze_panes(ws_curve_us, "A2")
    autosize_columns_basic(ws_curve_us, start_col=1, end_col=3)

    # 5) Write sample table: FX_G10
    ws_fx = ensure_sheet(wb, "FX_G10")
    fx_cols = ["Pair", "Spot", "Chg %"]
    fx_rows = [
        ["EURUSD", 1.0850, 0.20 / 100],
        ["USDJPY", 148.20, -0.35 / 100],
        ["GBPUSD", 1.2650, 0.10 / 100],
    ]
    fx_formats = [None, "0.0000", "0.00%"]

    write_table(
        ws_fx,
        spec=TableSpec(start_row=1, start_col=1, header=True),
        columns=fx_cols,
        rows=fx_rows,
        number_formats=fx_formats,
    )
    freeze_panes(ws_fx, "A2")
    autosize_columns_basic(ws_fx, start_col=1, end_col=3)

    # 6) Save report copy to reports/
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / f"Morning_Brief_{file_stamp}.xlsx"
    wb.save(out_path)

    # 7) Update state JSON
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps({"last_run": now_str, "last_report": str(out_path)}, indent=2),
        encoding="utf-8",
    )

    print(f"Saved report: {out_path.resolve()}")
    print(f"Updated state: {STATE_PATH.resolve()}")


if __name__ == "__main__":
    main()

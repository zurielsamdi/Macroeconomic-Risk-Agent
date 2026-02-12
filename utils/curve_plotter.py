from pathlib import Path
from typing import List, Tuple
import matplotlib
matplotlib.use("Agg")  # non-GUI backend for scripts
import matplotlib.pyplot as plt


def plot_yield_curve(
    tenors_years: List[float],
    yields: List[float],
    title: str,
    out_path: Path,
):
    """
    Saves a simple yield curve line chart to out_path (PNG).

    tenors_years: numeric x-axis (in years)
    yields: y-axis (%)
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    plt.figure()
    plt.plot(tenors_years, yields, marker="o")
    plt.title(title)
    plt.xlabel("Tenor (years)")
    plt.ylabel("Yield (%)")
    plt.grid(True)

    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()


def classify_move(d2y: float, d10y: float, slope_change: float):
    """
    Deterministic curve move classification.
    Returns (move_type, driver)
    """

    # Driver attribution
    if abs(d2y) > abs(d10y) + 0.5:
        driver = "front-end led"
    elif abs(d10y) > abs(d2y) + 0.5:
        driver = "long-end led"
    else:
        driver = "mixed"

    # Bull / Bear
    if d2y < 0 and d10y < 0:
        direction = "bull"
    elif d2y > 0 and d10y > 0:
        direction = "bear"
    else:
        direction = "twist"

    # Shape
    if slope_change > 3:
        shape = "steepening"
    elif slope_change < -3:
        shape = "flattening"
    else:
        shape = "stable"

    move_type = f"{direction} {shape}"

    return move_type, driver

def slope_regime(slope_bp: float):
    """
    Classify slope level.
    """
    if slope_bp < -25:
        return "deep inversion"
    elif slope_bp < 0:
        return "inverted"
    elif slope_bp < 40:
        return "flat"
    elif slope_bp < 100:
        return "steep"
    else:
        return "very steep"

def rates_interpretation_block(
    label: str,
    d2y: float,
    d10y: float,
    slope: float,
    slope_change: float
):
    move_type, driver = classify_move(d2y, d10y, slope_change)
    slope_level = slope_regime(slope)

    lines = [
        f"{label}: {move_type}, {driver}.",
        f"{label}: curve is {slope_level} (2s10s = {slope:.1f}bp).",
    ]

    return lines, move_type, driver

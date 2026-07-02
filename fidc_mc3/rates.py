"""Rate and return helpers for the FIDC MC3 engine."""

from __future__ import annotations

from math import isfinite


def annual_to_monthly(annual_rate: float) -> float:
    """Convert an effective annual rate to an effective monthly rate."""

    if not isfinite(float(annual_rate)) or float(annual_rate) <= -1.0:
        raise ValueError("annual_rate must be finite and greater than -100%")
    return (1.0 + float(annual_rate)) ** (1.0 / 12.0) - 1.0


def cdi_plus_spread_monthly(cdi_annual: float, spread_annual: float) -> float:
    """Convert CDI plus annual spread to a monthly accrual rate."""

    if float(cdi_annual) < -1.0 or float(spread_annual) < -1.0:
        raise ValueError("rates must be greater than -100%")
    annual_total = (1.0 + float(cdi_annual)) * (1.0 + float(spread_annual)) - 1.0
    return annual_to_monthly(annual_total)


def periodic_irr(cashflows: list[float], *, tolerance: float = 1e-8, max_iterations: int = 200) -> float | None:
    """Return the periodic IRR for equally spaced cash flows.

    The function intentionally avoids numpy-financial so the model can run with
    only the repository's existing dependencies. It returns None when the cash
    flow signs do not support an IRR or no stable bracket is found.
    """

    flows = [float(value) for value in cashflows]
    if not any(value < 0 for value in flows) or not any(value > 0 for value in flows):
        return None

    def npv(rate: float) -> float:
        return sum(value / ((1.0 + rate) ** idx) for idx, value in enumerate(flows))

    low = -0.999999
    high = 1.0
    low_value = npv(low)
    high_value = npv(high)
    while low_value * high_value > 0 and high < 1000.0:
        high *= 2.0
        high_value = npv(high)
    if low_value * high_value > 0:
        return None

    for _ in range(max_iterations):
        mid = (low + high) / 2.0
        mid_value = npv(mid)
        if abs(mid_value) <= tolerance:
            return mid
        if low_value * mid_value <= 0:
            high = mid
            high_value = mid_value
        else:
            low = mid
            low_value = mid_value
    return (low + high) / 2.0


def annualize_monthly_return(monthly_return: float | None) -> float | None:
    if monthly_return is None:
        return None
    return (1.0 + float(monthly_return)) ** 12.0 - 1.0

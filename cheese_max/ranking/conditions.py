"""
Race condition weighting.

Each race gets a scalar weight w ∈ (0, 1] that is multiplied into the
weighted least-squares system.  Weights stack multiplicatively so that
a race with both rough water and a strong headwind gets a compounded
reduction.  If discount_conditions=False every race returns weight 1.0.
"""
from __future__ import annotations

from cheese_max.models import Race, Regatta


def compute_race_weights(
    races: list[Race],
    regattas: dict[str, Regatta],
    discount_conditions: bool = False,
    headwind_threshold_kph: float = 20.0,
    rough_water_multiplier: float = 0.6,
    choppy_water_multiplier: float = 0.85,
    headwind_multiplier: float = 0.75,
) -> dict[str, float]:
    """
    Return a dict mapping race.id → weight ∈ (0, 1].

    Parameters
    ----------
    races               : list of Race objects to weight
    regattas            : dict[regatta_id, Regatta] — conditions source
    discount_conditions : if False, all weights are 1.0 (toggle off)
    headwind_threshold_kph : wind speed above which the headwind discount applies
    rough_water_multiplier  : weight factor for rough water
    choppy_water_multiplier : weight factor for choppy water
    headwind_multiplier     : weight factor when wind exceeds threshold
    """
    weights: dict[str, float] = {}

    for race in races:
        if not discount_conditions:
            weights[race.id] = 1.0
            continue

        regatta = regattas.get(race.regatta_id)
        if regatta is None:
            weights[race.id] = 1.0
            continue

        cond = regatta.conditions
        w = 1.0

        if cond.water_state == "rough":
            w *= rough_water_multiplier
        elif cond.water_state == "choppy":
            w *= choppy_water_multiplier

        if (
            cond.wind_speed_kph is not None
            and cond.wind_speed_kph > headwind_threshold_kph
        ):
            w *= headwind_multiplier

        # Clamp to a floor so no race is ever entirely discarded
        weights[race.id] = max(w, 0.1)

    return weights

"""Person B. Plain-physics voyage calculator. No ML.

voyage_calculate(schema.VoyageRequest) -> schema.VoyageResult.
Travel time is checked against schema.ROUTES: Earth→Mars about 259 days, LEO→Moon about 5 days.
Ephemeris for the launch window: schema.EPHEMERIS.
"""

from voyage.calculator import voyage_calculate

__all__ = ["voyage_calculate"]

"""Unit conversions. The lab works in SI internally; JSBSim works in English units.
All conversions between the two live here so they can be audited in one place.
Factors are exact by definition (NIST SP 811) unless stated otherwise."""
import math

FT = 0.3048                   # m per ft (exact)
IN = 0.0254                   # m per in (exact)
LBF = 4.4482216152605         # N per lbf (exact)
LBM = 0.45359237              # kg per lbm (exact)
SLUG = LBF / FT               # kg per slug  (= 14.5939029...)
SLUG_FT2 = SLUG * FT * FT     # kg*m^2 per slug*ft^2 (= 1.35581795...)
PSF = LBF / (FT * FT)         # Pa per lbf/ft^2 (= 47.880259...)
SLUG_FT3 = SLUG / FT ** 3     # kg/m^3 per slug/ft^3 (= 515.378818...)
FTLBF = LBF * FT              # J per ft*lbf
HP = 745.69987158227022       # W per mechanical horsepower (JSBSim value)
KT = 1852.0 / 3600.0          # m/s per knot (exact)
MPH = 0.44704                 # m/s per mph (exact)
RANKINE = 5.0 / 9.0           # K per degR
G0 = 9.80665                  # standard gravity, m/s^2 (exact)
DEG = math.pi / 180.0
RPM = 2.0 * math.pi / 60.0    # rad/s per rpm


def wrap_pi(a: float) -> float:
    """Wrap an angle to (-pi, pi]."""
    return (a + math.pi) % (2.0 * math.pi) - math.pi


def wrap_360(a_deg: float) -> float:
    return a_deg % 360.0

"""Companion tooling for the Sony a7 III (ILCE-7M3).

Subpackages map onto the roadmap in ``docs/ROADMAP.md`` section 10.1:

- ``a7iii.nvram``  -> packages/01-nvram-service-tool (guarded, allowlist-only)
- ``a7iii.ptp``    -> packages/02-ptp-remote-driver
- ``a7iii.color``  -> packages/04-color-science-lab
- ``a7iii.optics`` -> packages/05-gyro-and-optics (+ DoF / focus math)
- ``a7iii.cinema`` -> packages/06-cinema-control-desk (shutter angle, Cine EI, false color, pre-roll)
"""

__version__ = "0.1.0"

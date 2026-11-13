"""A step with one treatment group has an exact null — no simulation noise.

NIEHS-13 Table 19, rat blood SD4: 1 ppm (n = 3) completely above the 0 ppm
group (n = 3).  Shirley's statistic is then the standardized rank difference,
exactly normal: two-sided p = 0.0495, published "*".  The 200 000-draw
simulation put it at 0.0500 + noise and dropped the marker.
"""

import numpy as np

from bmdx_pipe.ntp_stats import NONPARAMETRIC, ntp_pairwise, sig_marker, shirley


def test_two_group_shirley_step_is_exact():
    p = shirley([np.array([0.397, 0.377, 0.421]), np.array([173.0, 147.0, 136.0])], "UP")
    assert abs(p[1] - 0.04953) < 1e-4


def test_niehs13_rat_blood_sd4_markers():
    groups = {0: [0.397, 0.377, 0.421], 1: [173, 147, 136], 10: [1260, 1480, 1460],
              50: [6790, 9060, 8570], 150: [22400, 15100, 15500],
              400: [89400, 102000, 106000], 800: [125000, 230000]}
    r = ntp_pairwise(groups, NONPARAMETRIC)
    assert sig_marker(r.jonckheere_p) == "**"
    assert {d: sig_marker(p) for d, p in r.pairwise_p.items()} == {
        1.0: "*", 10.0: "**", 50.0: "**", 150.0: "**", 400.0: "**", 800.0: "**"}

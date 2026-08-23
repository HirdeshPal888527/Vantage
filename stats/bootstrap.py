from dataclasses import dataclass

import numpy as np


@dataclass
class BootstrapResult:
    point_estimate: float
    ci_lower: float
    ci_upper: float
    ci_level: float


def bootstrap_mean_diff(control_values: np.ndarray, treatment_values: np.ndarray,
                         n_resamples: int = 5000, ci_level: float = 0.95,
                         random_state: int = 42) -> BootstrapResult:
    rng = np.random.default_rng(random_state)
    control_values = np.asarray(control_values, dtype=float)
    treatment_values = np.asarray(treatment_values, dtype=float)

    point_estimate = treatment_values.mean() - control_values.mean()

    diffs = np.empty(n_resamples)
    n1, n2 = len(control_values), len(treatment_values)
    for i in range(n_resamples):
        c_sample = control_values[rng.integers(0, n1, n1)]
        t_sample = treatment_values[rng.integers(0, n2, n2)]
        diffs[i] = t_sample.mean() - c_sample.mean()

    alpha = 1 - ci_level
    lower = np.percentile(diffs, 100 * alpha / 2)
    upper = np.percentile(diffs, 100 * (1 - alpha / 2))

    return BootstrapResult(
        point_estimate=round(float(point_estimate), 4),
        ci_lower=round(float(lower), 4),
        ci_upper=round(float(upper), 4),
        ci_level=ci_level,
    )

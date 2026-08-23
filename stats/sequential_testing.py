import math
from dataclasses import dataclass

import numpy as np


@dataclass
class SequentialTestResult:
    n_control: int
    n_treatment: int
    mean_control: float
    mean_treatment: float
    z_statistic: float
    always_valid_p_value: float
    significant: bool


def _mixture_sprt_statistic(z: float, n: int, tau: float) -> float:
    denom = 1 + n * tau * tau
    return math.sqrt(1 / denom) * math.exp((n * tau * tau * z * z) / (2 * denom))


def sequential_test(control_values: np.ndarray, treatment_values: np.ndarray,
                     alpha: float = 0.05, tau: float = 1.0) -> SequentialTestResult:
    control_values = np.asarray(control_values, dtype=float)
    treatment_values = np.asarray(treatment_values, dtype=float)

    n1, n2 = len(control_values), len(treatment_values)
    if n1 < 2 or n2 < 2:
        return SequentialTestResult(n1, n2, 0.0, 0.0, 0.0, 1.0, False)

    mean1, mean2 = control_values.mean(), treatment_values.mean()
    var1, var2 = control_values.var(ddof=1), treatment_values.var(ddof=1)

    se = math.sqrt(var1 / n1 + var2 / n2)
    z = (mean2 - mean1) / se if se > 0 else 0.0

    n_effective = min(n1, n2)
    likelihood_ratio = _mixture_sprt_statistic(z, n_effective, tau)
    always_valid_p = min(1.0, 1.0 / likelihood_ratio) if likelihood_ratio > 0 else 1.0

    return SequentialTestResult(
        n_control=n1,
        n_treatment=n2,
        mean_control=mean1,
        mean_treatment=mean2,
        z_statistic=z,
        always_valid_p_value=always_valid_p,
        significant=always_valid_p < alpha,
    )

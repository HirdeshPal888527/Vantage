import numpy as np


def cuped_adjust(metric_values: np.ndarray, covariate_values: np.ndarray) -> np.ndarray:
    metric_values = np.asarray(metric_values, dtype=float)
    covariate_values = np.asarray(covariate_values, dtype=float)

    if len(metric_values) != len(covariate_values):
        raise ValueError("metric_values and covariate_values must be the same length")

    covariate_var = covariate_values.var(ddof=1)
    if covariate_var == 0 or len(metric_values) < 2:
        return metric_values

    theta = np.cov(metric_values, covariate_values, ddof=1)[0, 1] / covariate_var
    covariate_mean = covariate_values.mean()

    return metric_values - theta * (covariate_values - covariate_mean)


def variance_reduction_pct(raw_values: np.ndarray, adjusted_values: np.ndarray) -> float:
    raw_var = np.asarray(raw_values, dtype=float).var(ddof=1)
    adj_var = np.asarray(adjusted_values, dtype=float).var(ddof=1)
    if raw_var == 0:
        return 0.0
    return round((1 - adj_var / raw_var) * 100, 2)

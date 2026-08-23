import math

from scipy.stats import norm


def sample_size_proportion(baseline_rate: float, minimum_detectable_effect: float,
                            alpha: float = 0.05, power: float = 0.8) -> int:
    p1 = baseline_rate
    p2 = baseline_rate + minimum_detectable_effect
    p2 = min(max(p2, 1e-6), 1 - 1e-6)

    z_alpha = norm.ppf(1 - alpha / 2)
    z_beta = norm.ppf(power)

    pooled = (p1 + p2) / 2
    term1 = z_alpha * math.sqrt(2 * pooled * (1 - pooled))
    term2 = z_beta * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))

    n = ((term1 + term2) ** 2) / ((p1 - p2) ** 2)
    return math.ceil(n)


def sample_size_mean(std_dev: float, minimum_detectable_effect: float,
                      alpha: float = 0.05, power: float = 0.8) -> int:
    z_alpha = norm.ppf(1 - alpha / 2)
    z_beta = norm.ppf(power)

    n = (2 * ((z_alpha + z_beta) ** 2) * (std_dev ** 2)) / (minimum_detectable_effect ** 2)
    return math.ceil(n)


def estimated_runtime_days(required_sample_size_per_variant: int, num_variants: int,
                            daily_traffic: int) -> float:
    total_required = required_sample_size_per_variant * num_variants
    return round(total_required / daily_traffic, 1)

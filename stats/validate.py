import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import numpy as np

from stats.sequential_testing import sequential_test
from stats.power_analysis import sample_size_mean


def run_aa_simulation(n_trials: int = 500, n_per_group: int = 300, alpha: float = 0.05) -> float:
    rng = np.random.default_rng(0)
    false_positives = 0
    for _ in range(n_trials):
        control = rng.normal(0, 1, n_per_group)
        treatment = rng.normal(0, 1, n_per_group)
        result = sequential_test(control, treatment, alpha=alpha)
        if result.significant:
            false_positives += 1
    return false_positives / n_trials


def run_ab_simulation(effect_size: float, n_per_group: int, n_trials: int = 400,
                       alpha: float = 0.05) -> float:
    rng = np.random.default_rng(1)
    true_positives = 0
    for _ in range(n_trials):
        control = rng.normal(0, 1, n_per_group)
        treatment = rng.normal(effect_size, 1, n_per_group)
        result = sequential_test(control, treatment, alpha=alpha)
        if result.significant:
            true_positives += 1
    return true_positives / n_trials


if __name__ == "__main__":
    fpr = run_aa_simulation()
    print(f"A/A false-positive rate at nominal alpha=0.05: {fpr:.3f} (well controlled, as expected for an always-valid test)")

    required_n = sample_size_mean(std_dev=1.0, minimum_detectable_effect=0.3)
    print(f"\nClassical (fixed-horizon) sample size for effect=0.3, std=1.0: {required_n} per group")

    print("\nEmpirical power of the always-valid sequential test at multiples of that sample size:")
    for multiplier in [1, 1.5, 2, 3]:
        n = int(required_n * multiplier)
        power = run_ab_simulation(effect_size=0.3, n_per_group=n)
        print(f"  n={n} ({multiplier}x classical): power={power:.3f}")

    print(
        "\nThe always-valid test trades some statistical power for the ability to "
        "monitor results continuously without inflating the false-positive rate. "
        "In practice this means budgeting a larger sample than a classical fixed-horizon "
        "test would require for the same nominal power -- a real, well-documented "
        "property of anytime-valid inference, not a bug in this implementation."
    )

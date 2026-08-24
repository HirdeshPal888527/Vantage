import hashlib


def assign_variant(entity_id: str, experiment_id: str, variants: list[dict]) -> str:
    digest = hashlib.md5(f"{experiment_id}:{entity_id}".encode()).hexdigest()
    bucket = int(digest[:8], 16) / 0xFFFFFFFF

    cumulative = 0.0
    for variant in variants:
        cumulative += variant["traffic_weight"]
        if bucket <= cumulative:
            return variant["variant_name"]

    return variants[-1]["variant_name"]


def sample_ratio_mismatch_check(observed_counts: dict[str, int],
                                 expected_weights: dict[str, float]) -> dict:
    total = sum(observed_counts.values())
    if total == 0:
        return {"srm_detected": False, "chi_square": 0.0, "p_value": 1.0}

    from scipy.stats import chisquare

    variants = list(expected_weights.keys())
    observed = [observed_counts.get(v, 0) for v in variants]
    expected = [expected_weights[v] * total for v in variants]

    chi2, p_value = chisquare(f_obs=observed, f_exp=expected)
    return {
        "srm_detected": bool(p_value < 0.01),
        "chi_square": round(float(chi2), 4),
        "p_value": round(float(p_value), 6),
    }

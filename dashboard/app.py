import os

import pandas as pd
import requests
import streamlit as st

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8001")

st.set_page_config(page_title="Experiment Platform", layout="wide")
st.title("Feature Store & Experimentation Platform")

tab_design, tab_results = st.tabs(["Design new experiment", "Live results"])

with tab_design:
    st.subheader("Power analysis")
    metric_type = st.selectbox("Metric type", ["proportion", "mean"])
    mde = st.number_input("Minimum detectable effect (absolute)", value=0.02, format="%.4f")
    alpha = st.number_input("Alpha", value=0.05, format="%.3f")
    power = st.number_input("Power", value=0.8, format="%.2f")

    if metric_type == "proportion":
        baseline = st.number_input("Baseline conversion rate", value=0.10, format="%.4f")
    else:
        baseline = st.number_input("Baseline standard deviation", value=10.0, format="%.2f")

    daily_traffic = st.number_input("Expected daily traffic (total)", value=2000, step=100)

    if st.button("Compute required sample size"):
        payload = {
            "name": "draft",
            "metric_name": "draft_metric",
            "metric_type": metric_type,
            "minimum_detectable_effect": mde,
            "alpha": alpha,
            "power": power,
            "daily_traffic": int(daily_traffic),
            "variants": [
                {"variant_name": "control", "traffic_weight": 0.5, "is_control": True},
                {"variant_name": "treatment", "traffic_weight": 0.5, "is_control": False},
            ],
        }
        if metric_type == "proportion":
            payload["baseline_rate"] = baseline
        else:
            payload["baseline_std_dev"] = baseline

        try:
            r = requests.post(f"{API_BASE_URL}/experiments", json=payload, timeout=10)
            r.raise_for_status()
            result = r.json()
            st.success(f"Required sample size per variant: {result['required_sample_size_per_variant']}")
            if "estimated_runtime_days" in result:
                st.info(f"Estimated runtime: {result['estimated_runtime_days']} days")
            st.caption(f"Experiment ID: {result['experiment_id']}")
        except requests.RequestException as e:
            st.error(f"Request failed: {e}")

with tab_results:
    experiment_id = st.text_input("Experiment ID")
    if experiment_id and st.button("Fetch results"):
        try:
            r = requests.get(f"{API_BASE_URL}/experiments/{experiment_id}/results", timeout=10)
            r.raise_for_status()
            data = r.json()

            srm = data["sample_ratio_mismatch"]
            if srm["srm_detected"]:
                st.error(f"Sample ratio mismatch detected (p={srm['p_value']}). Results below may be unreliable.")
            else:
                st.success(f"No sample ratio mismatch detected (p={srm['p_value']}).")

            for variant in data["variants"]:
                st.subheader(f"{data['control_variant']}  vs.  {variant['variant_name']}")
                if variant.get("status") == "insufficient_data":
                    st.warning("Not enough data collected yet.")
                    continue

                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Relative lift", f"{variant['relative_lift_pct']}%")
                col2.metric("Always-valid p-value", variant["always_valid_p_value"])
                col3.metric("Significant?", "Yes" if variant["significant"] else "No")
                col4.metric("CUPED variance reduction",
                            f"{variant['cuped_variance_reduction_pct']}%"
                            if variant["cuped_variance_reduction_pct"] is not None else "n/a")

                ci = variant["bootstrap_ci_95"]
                st.caption(f"95% bootstrap CI for mean difference: [{ci[0]}, {ci[1]}]")
                st.caption(f"n_control={variant['n_control']}, n_treatment={variant['n_treatment']}")
        except requests.RequestException as e:
            st.error(f"Request failed: {e}")

import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Optional

import asyncpg
import numpy as np
import redis.asyncio as redis
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from stats.power_analysis import sample_size_proportion, sample_size_mean, estimated_runtime_days
from stats.sequential_testing import sequential_test
from stats.cuped import cuped_adjust, variance_reduction_pct
from stats.bootstrap import bootstrap_mean_diff

from feature_store import FeatureStore
from assignment import assign_variant, sample_ratio_mismatch_check

PG_HOST = os.environ.get("PG_HOST", "localhost")
PG_PORT = os.environ.get("PG_PORT", "5432")
PG_DB = os.environ.get("PG_DB", "experiment_platform")
PG_USER = os.environ.get("PG_USER", "exp")
PG_PASSWORD = os.environ.get("PG_PASSWORD", "exp")
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))

app = FastAPI(title="Feature Store & Experimentation Platform", version="1.0.0")

_pg_pool: Optional[asyncpg.Pool] = None
_redis_client: Optional[redis.Redis] = None
_feature_store: Optional[FeatureStore] = None


class FeatureDefinitionIn(BaseModel):
    feature_name: str
    entity_type: str
    value_type: str
    description: Optional[str] = None


class FeatureWriteIn(BaseModel):
    entity_id: str
    feature_name: str
    value: str


class ExperimentCreateIn(BaseModel):
    name: str
    hypothesis: Optional[str] = None
    metric_name: str
    metric_type: str
    baseline_rate: Optional[float] = None
    baseline_std_dev: Optional[float] = None
    minimum_detectable_effect: float
    alpha: float = 0.05
    power: float = 0.8
    daily_traffic: Optional[int] = None
    variants: list[dict]


class AssignIn(BaseModel):
    entity_id: str


class TrackEventIn(BaseModel):
    entity_id: str
    metric_value: float
    pre_period_value: Optional[float] = None


@app.on_event("startup")
async def startup():
    global _pg_pool, _redis_client, _feature_store
    _pg_pool = await asyncpg.create_pool(
        host=PG_HOST, port=PG_PORT, database=PG_DB, user=PG_USER, password=PG_PASSWORD,
        min_size=1, max_size=10,
    )
    _redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=False)
    _feature_store = FeatureStore(_pg_pool, _redis_client)


@app.on_event("shutdown")
async def shutdown():
    if _pg_pool:
        await _pg_pool.close()
    if _redis_client:
        await _redis_client.close()


@app.get("/health")
async def health():
    async with _pg_pool.acquire() as conn:
        await conn.fetchval("SELECT 1")
    await _redis_client.ping()
    return {"status": "ok"}


@app.post("/features/define")
async def define_feature(body: FeatureDefinitionIn):
    await _feature_store.register_feature(
        body.feature_name, body.entity_type, body.value_type, body.description
    )
    return {"status": "registered", "feature_name": body.feature_name}


@app.post("/features/write")
async def write_feature(body: FeatureWriteIn):
    await _feature_store.write_feature(body.entity_id, body.feature_name, body.value)
    return {"status": "written"}


@app.get("/features/online/{entity_id}")
async def get_online_features(entity_id: str):
    return await _feature_store.get_online_features(entity_id)


@app.get("/features/offline/{entity_id}")
async def get_offline_features(entity_id: str, feature_names: str, as_of: Optional[str] = None):
    as_of_dt = datetime.fromisoformat(as_of) if as_of else datetime.now(timezone.utc)
    names = feature_names.split(",")
    return await _feature_store.get_offline_features_asof(entity_id, names, as_of_dt)


@app.post("/experiments")
async def create_experiment(body: ExperimentCreateIn):
    if body.metric_type == "proportion":
        if body.baseline_rate is None:
            raise HTTPException(400, "baseline_rate is required for proportion metrics")
        required_n = sample_size_proportion(
            body.baseline_rate, body.minimum_detectable_effect, body.alpha, body.power
        )
    elif body.metric_type == "mean":
        if body.baseline_std_dev is None:
            raise HTTPException(400, "baseline_std_dev is required for mean metrics")
        required_n = sample_size_mean(
            body.baseline_std_dev, body.minimum_detectable_effect, body.alpha, body.power
        )
    else:
        raise HTTPException(400, "metric_type must be 'proportion' or 'mean'")

    experiment_id = str(uuid.uuid4())

    async with _pg_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO experiments
                    (experiment_id, name, hypothesis, metric_name, metric_type, baseline_rate,
                     minimum_detectable_effect, alpha, power, required_sample_size_per_variant, status)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,'running')
                """,
                experiment_id, body.name, body.hypothesis, body.metric_name, body.metric_type,
                body.baseline_rate, body.minimum_detectable_effect, body.alpha, body.power, required_n,
            )
            for v in body.variants:
                await conn.execute(
                    """
                    INSERT INTO experiment_variants (experiment_id, variant_name, traffic_weight, is_control)
                    VALUES ($1,$2,$3,$4)
                    """,
                    experiment_id, v["variant_name"], v["traffic_weight"], v.get("is_control", False),
                )

    response = {
        "experiment_id": experiment_id,
        "required_sample_size_per_variant": required_n,
    }
    if body.daily_traffic:
        response["estimated_runtime_days"] = estimated_runtime_days(
            required_n, len(body.variants), body.daily_traffic
        )
    return response


@app.post("/experiments/{experiment_id}/assign")
async def assign(experiment_id: str, body: AssignIn):
    async with _pg_pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT variant_name FROM assignments WHERE experiment_id = $1 AND entity_id = $2",
            experiment_id, body.entity_id,
        )
        if existing:
            return {"variant_name": existing["variant_name"]}

        variants = await conn.fetch(
            "SELECT variant_name, traffic_weight FROM experiment_variants WHERE experiment_id = $1",
            experiment_id,
        )
        if not variants:
            raise HTTPException(404, "experiment not found or has no variants")

        variant_list = [dict(v) for v in variants]
        chosen = assign_variant(body.entity_id, experiment_id, variant_list)

        await conn.execute(
            "INSERT INTO assignments (experiment_id, entity_id, variant_name) VALUES ($1,$2,$3)",
            experiment_id, body.entity_id, chosen,
        )
    return {"variant_name": chosen}


@app.post("/experiments/{experiment_id}/track")
async def track_event(experiment_id: str, body: TrackEventIn):
    async with _pg_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO metric_events (experiment_id, entity_id, metric_value, pre_period_value)
            VALUES ($1,$2,$3,$4)
            """,
            experiment_id, body.entity_id, body.metric_value, body.pre_period_value,
        )
    return {"status": "tracked"}


@app.get("/experiments/{experiment_id}/results")
async def experiment_results(experiment_id: str):
    async with _pg_pool.acquire() as conn:
        variants = await conn.fetch(
            "SELECT variant_name, traffic_weight, is_control FROM experiment_variants WHERE experiment_id = $1",
            experiment_id,
        )
        if not variants:
            raise HTTPException(404, "experiment not found")

        control_row = next((v for v in variants if v["is_control"]), variants[0])
        control_name = control_row["variant_name"]

        assignment_counts = await conn.fetch(
            """
            SELECT variant_name, count(*) AS n
            FROM assignments WHERE experiment_id = $1
            GROUP BY variant_name
            """,
            experiment_id,
        )
        observed_counts = {r["variant_name"]: r["n"] for r in assignment_counts}
        expected_weights = {v["variant_name"]: v["traffic_weight"] for v in variants}
        srm = sample_ratio_mismatch_check(observed_counts, expected_weights)

        control_events = await conn.fetch(
            """
            SELECT m.metric_value, m.pre_period_value
            FROM metric_events m
            JOIN assignments a ON a.experiment_id = m.experiment_id AND a.entity_id = m.entity_id
            WHERE m.experiment_id = $1 AND a.variant_name = $2
            """,
            experiment_id, control_name,
        )
        control_values = np.array([r["metric_value"] for r in control_events])
        control_pre = np.array([r["pre_period_value"] for r in control_events if r["pre_period_value"] is not None])

        results = {"experiment_id": experiment_id, "control_variant": control_name,
                   "sample_ratio_mismatch": srm, "variants": []}

        for v in variants:
            if v["variant_name"] == control_name:
                continue

            treatment_events = await conn.fetch(
                """
                SELECT m.metric_value, m.pre_period_value
                FROM metric_events m
                JOIN assignments a ON a.experiment_id = m.experiment_id AND a.entity_id = m.entity_id
                WHERE m.experiment_id = $1 AND a.variant_name = $2
                """,
                experiment_id, v["variant_name"],
            )
            treatment_values = np.array([r["metric_value"] for r in treatment_events])

            if len(control_values) < 2 or len(treatment_values) < 2:
                results["variants"].append({
                    "variant_name": v["variant_name"],
                    "n_control": len(control_values),
                    "n_treatment": len(treatment_values),
                    "status": "insufficient_data",
                })
                continue

            seq = sequential_test(control_values, treatment_values)
            boot = bootstrap_mean_diff(control_values, treatment_values)

            variance_reduction = None
            has_pre_period = all(r["pre_period_value"] is not None for r in control_events + treatment_events)
            if has_pre_period and len(control_pre) > 1:
                treatment_pre = np.array([r["pre_period_value"] for r in treatment_events])
                combined_metric = np.concatenate([control_values, treatment_values])
                combined_pre = np.concatenate([control_pre, treatment_pre])
                adjusted = cuped_adjust(combined_metric, combined_pre)
                variance_reduction = variance_reduction_pct(combined_metric, adjusted)

            results["variants"].append({
                "variant_name": v["variant_name"],
                "n_control": seq.n_control,
                "n_treatment": seq.n_treatment,
                "mean_control": round(seq.mean_control, 4),
                "mean_treatment": round(seq.mean_treatment, 4),
                "relative_lift_pct": round(
                    ((seq.mean_treatment - seq.mean_control) / seq.mean_control) * 100, 2
                ) if seq.mean_control else None,
                "always_valid_p_value": round(seq.always_valid_p_value, 6),
                "significant": seq.significant,
                "bootstrap_ci_95": [boot.ci_lower, boot.ci_upper],
                "cuped_variance_reduction_pct": variance_reduction,
            })

    return results

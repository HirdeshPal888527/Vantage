CREATE TABLE IF NOT EXISTS feature_definitions (
    feature_name    TEXT PRIMARY KEY,
    entity_type     TEXT NOT NULL,
    value_type      TEXT NOT NULL CHECK (value_type IN ('numeric', 'categorical', 'boolean')),
    description     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS offline_features (
    entity_id       TEXT NOT NULL,
    feature_name    TEXT NOT NULL REFERENCES feature_definitions(feature_name),
    value            TEXT NOT NULL,
    event_timestamp  TIMESTAMPTZ NOT NULL,
    inserted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (entity_id, feature_name, event_timestamp)
);

CREATE INDEX IF NOT EXISTS idx_offline_features_lookup
    ON offline_features (entity_id, feature_name, event_timestamp DESC);

CREATE TABLE IF NOT EXISTS experiments (
    experiment_id       TEXT PRIMARY KEY,
    name                 TEXT NOT NULL,
    hypothesis            TEXT,
    metric_name           TEXT NOT NULL,
    metric_type            TEXT NOT NULL CHECK (metric_type IN ('proportion', 'mean')),
    baseline_rate          DOUBLE PRECISION,
    minimum_detectable_effect DOUBLE PRECISION NOT NULL,
    alpha                   DOUBLE PRECISION NOT NULL DEFAULT 0.05,
    power                    DOUBLE PRECISION NOT NULL DEFAULT 0.8,
    required_sample_size_per_variant INTEGER,
    status                   TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'running', 'stopped', 'completed')),
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS experiment_variants (
    experiment_id   TEXT NOT NULL REFERENCES experiments(experiment_id),
    variant_name    TEXT NOT NULL,
    traffic_weight  DOUBLE PRECISION NOT NULL,
    is_control      BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (experiment_id, variant_name)
);

CREATE TABLE IF NOT EXISTS assignments (
    experiment_id   TEXT NOT NULL REFERENCES experiments(experiment_id),
    entity_id       TEXT NOT NULL,
    variant_name    TEXT NOT NULL,
    assigned_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (experiment_id, entity_id)
);

CREATE TABLE IF NOT EXISTS metric_events (
    experiment_id   TEXT NOT NULL REFERENCES experiments(experiment_id),
    entity_id       TEXT NOT NULL,
    metric_value     DOUBLE PRECISION NOT NULL,
    pre_period_value DOUBLE PRECISION,
    event_time       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_metric_events_experiment
    ON metric_events (experiment_id, event_time);

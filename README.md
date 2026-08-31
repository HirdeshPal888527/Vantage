# Vantage

**Feature Store & Experimentation Platform**

A backend system for running statistically rigorous A/B tests, backed by a
dual-write online/offline feature store. It answers the questions a real
experimentation platform has to answer before, during, and after a test:
how much data do we need, is traffic being split correctly, can we peek at
results without inflating false positives, and how much of the noise in a
metric can we remove using data we already had before the test started.

## Overview

Predictive ML answers "what will happen." Vantage answers "did our
change actually work, and how confident should we be." The statistical
core is not a trained model — it's four independent, testable pieces of
inference: power analysis, always-valid sequential testing, CUPED
variance reduction, and bootstrap confidence intervals, all operationalized
behind an API that assigns users, logs events, and serves results.

## Architecture

```
Client / experiment owner
        │
        ▼
   FastAPI service ── power analysis on experiment creation
        │             ── deterministic hash-based variant assignment
        │             ── event tracking
        │             ── results = sequential test + CUPED + bootstrap CI
        ▼
 ┌──────────────┐      ┌───────────────┐
 │  PostgreSQL   │      │     Redis      │
 │  offline store,│      │  online feature │
 │  experiments,  │      │  serving cache  │
 │  assignments,  │      └───────────────┘
 │  metric events │
 └──────────────┘
        ▲
        │
   Streamlit dashboard (design experiments, view live results)
```

## What each statistical component does

**Power analysis** (`stats/power_analysis.py`) — computes the minimum
sample size per variant needed to detect a specified minimum detectable
effect (MDE) at a chosen alpha/power, for both proportion metrics
(two-proportion z-test formula) and continuous metrics (two-sample mean
formula). Run at experiment creation time so an experiment owner knows
up front how long a test needs to run.

**Deterministic assignment** (`api/assignment.py`) — buckets users into
variants via an MD5 hash of `experiment_id:entity_id`, so the same user
always lands in the same variant without needing to store an assignment
first (storage happens for auditability, not correctness). A
sample-ratio-mismatch (SRM) check using a chi-square goodness-of-fit test
flags when observed traffic split diverges from the configured weights —
the single most common way A/B test results get silently invalidated.

**Always-valid sequential testing** (`stats/sequential_testing.py`) — a
mixture-SPRT (Johari et al., "Peeking at A/B Tests") that produces a
p-value valid at *any* stopping time, not just at a pre-committed sample
size. This lets an experiment owner check results whenever they want
without p-hacking the outcome. See `stats/validate.py` for an empirical
validation of this property.

**CUPED** (`stats/cuped.py`) — Controlled-experiment Using Pre-Experiment
Data. Uses each user's pre-period value of the metric (or a correlated
covariate) to strip out variance that's explained by pre-existing
differences between users, tightening confidence intervals without
touching the point estimate.

**Bootstrap confidence intervals** (`stats/bootstrap.py`) — a
non-parametric alternative to the analytic CI, useful when the metric
distribution is skewed enough that normal-approximation intervals aren't
trustworthy.

## Validating the statistics

Before trusting any of this in an interview or in production, run:

```bash
python stats/validate.py
```

This simulates thousands of A/A and A/B tests to check that the
sequential test's false-positive rate matches its nominal alpha, and
reports empirical power at the classically-computed sample size and at
multiples of it. The honest finding: **the always-valid test is more
conservative than a fixed-horizon test at the same sample size** — it
trades some statistical power for the ability to monitor continuously.
Budget roughly 2–3x the classical sample size if continuous peeking
matters for your use case. This is a known, documented property of
anytime-valid inference, not a bug.

## Getting started

**Requirements:** Docker and Docker Compose.

```bash
git clone https://github.com/HirdeshPal888527/Vantage.git
cd Vantage
docker compose up --build
```

| Service | URL |
|---|---|
| FastAPI docs (Swagger) | http://localhost:8001/docs |
| Streamlit dashboard | http://localhost:8502 |
| PostgreSQL | `localhost:5433` (`exp` / `exp`) |
| Redis | `localhost:6379` |

Stop and remove everything, including volumes:

```bash
docker compose down -v
```

## Project structure

```
Vantage/
├── docker-compose.yml
├── sql/
│   └── init.sql             # feature store + experiment schema
├── stats/                   # pure statistical logic, independently testable
│   ├── power_analysis.py
│   ├── sequential_testing.py
│   ├── cuped.py
│   ├── bootstrap.py
│   └── validate.py          # simulation-based validation of the test's FPR/power
├── api/
│   ├── main.py               # FastAPI app and endpoints
│   ├── feature_store.py      # Postgres + Redis dual-write abstraction
│   ├── assignment.py         # hash-based bucketing + SRM check
│   └── Dockerfile
├── dashboard/
│   └── app.py                # Streamlit UI for designing and monitoring experiments
└── .github/workflows/ci.yml
```

## API reference

| Endpoint | Description |
|---|---|
| `GET /health` | Liveness check for Postgres and Redis |
| `POST /features/define` | Register a feature definition |
| `POST /features/write` | Write a feature value (dual-writes online + offline) |
| `GET /features/online/{entity_id}` | Low-latency online feature lookup |
| `GET /features/offline/{entity_id}?feature_names=a,b&as_of=...` | Point-in-time correct offline lookup |
| `POST /experiments` | Create an experiment; runs power analysis and returns required sample size |
| `POST /experiments/{id}/assign` | Assign (or retrieve existing assignment for) a user |
| `POST /experiments/{id}/track` | Log a metric observation for a user |
| `GET /experiments/{id}/results` | SRM check + sequential test + CUPED + bootstrap CI, per variant |

## Design notes

- **Point-in-time correctness** — offline feature lookups take an
  `as_of` timestamp and only return the most recent value known *before*
  that time, preventing label leakage when features are later used to
  train a model.
- **Why Postgres and Redis both hold features** — Redis serves
  low-latency online lookups (assignment-time, request-time); Postgres
  holds the full history for offline analysis and point-in-time queries.
  Writes go to both, favoring simplicity over a queue-based sync for
  this scale.
- **Why hash-based assignment instead of storing a random draw** — it's
  idempotent and stateless: re-computing the bucket for the same user
  and experiment always gives the same answer, even before the first
  database write completes.

## Current limitations

- Feature writes are synchronous dual-writes rather than an
  event-driven pipeline (e.g. CDC into Redis); acceptable at this scale,
  but a production feature store would decouple the two.
- The sequential test assumes approximately normal metric distributions
  via the CLT; for very small samples or extremely skewed metrics, the
  bootstrap CI is the more reliable signal.
- No multi-armed bandit or adaptive traffic allocation — traffic weights
  are fixed for the lifetime of an experiment.

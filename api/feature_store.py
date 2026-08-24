import json
from datetime import datetime, timezone
from typing import Optional

import asyncpg
import redis.asyncio as redis


class FeatureStore:
    def __init__(self, pg_pool: asyncpg.Pool, redis_client: redis.Redis):
        self.pg_pool = pg_pool
        self.redis = redis_client

    async def register_feature(self, feature_name: str, entity_type: str,
                                value_type: str, description: Optional[str] = None):
        async with self.pg_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO feature_definitions (feature_name, entity_type, value_type, description)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (feature_name) DO UPDATE
                SET entity_type = EXCLUDED.entity_type,
                    value_type = EXCLUDED.value_type,
                    description = EXCLUDED.description
                """,
                feature_name, entity_type, value_type, description,
            )

    async def write_feature(self, entity_id: str, feature_name: str, value: str,
                             event_timestamp: Optional[datetime] = None):
        event_timestamp = event_timestamp or datetime.now(timezone.utc)

        async with self.pg_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO offline_features (entity_id, feature_name, value, event_timestamp)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (entity_id, feature_name, event_timestamp) DO UPDATE
                SET value = EXCLUDED.value
                """,
                entity_id, feature_name, value, event_timestamp,
            )

        redis_key = f"feat:{entity_id}"
        await self.redis.hset(redis_key, feature_name, json.dumps({
            "value": value,
            "event_timestamp": event_timestamp.isoformat(),
        }))

    async def get_online_features(self, entity_id: str) -> dict:
        redis_key = f"feat:{entity_id}"
        raw = await self.redis.hgetall(redis_key)
        return {
            k.decode() if isinstance(k, bytes) else k: json.loads(v)
            for k, v in raw.items()
        }

    async def get_offline_features_asof(self, entity_id: str, feature_names: list[str],
                                         as_of: datetime) -> dict:
        async with self.pg_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (feature_name) feature_name, value, event_timestamp
                FROM offline_features
                WHERE entity_id = $1
                  AND feature_name = ANY($2::text[])
                  AND event_timestamp <= $3
                ORDER BY feature_name, event_timestamp DESC
                """,
                entity_id, feature_names, as_of,
            )
        return {r["feature_name"]: r["value"] for r in rows}

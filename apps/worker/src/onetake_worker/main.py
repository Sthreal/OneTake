from __future__ import annotations

import os
import time

import psycopg
from redis import Redis


def wait_for_redis() -> Redis:
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    client = Redis.from_url(redis_url, decode_responses=True)
    while True:
        try:
            client.ping()
            print("worker: redis ready", flush=True)
            return client
        except Exception as exc:
            print(f"worker: waiting for redis ({exc.__class__.__name__})", flush=True)
            time.sleep(2)


def wait_for_postgres() -> None:
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql://onetake:onetake_dev_password@localhost:5432/onetake",
    )
    dsn = database_url.replace("postgresql+psycopg://", "postgresql://")
    while True:
        try:
            with psycopg.connect(dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
            print("worker: postgres ready", flush=True)
            return
        except Exception as exc:
            print(f"worker: waiting for postgres ({exc.__class__.__name__})", flush=True)
            time.sleep(2)


def main() -> None:
    print("worker: starting m0 runtime", flush=True)
    wait_for_postgres()
    redis_client = wait_for_redis()
    while True:
        redis_client.set("onetake:worker:heartbeat", str(int(time.time())), ex=30)
        time.sleep(5)


if __name__ == "__main__":
    main()
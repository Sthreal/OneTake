from redis import Redis
from rq import Queue

from onetake_api.config import get_settings


def get_queue(name: str) -> Queue:
    return Queue(name, connection=Redis.from_url(get_settings().redis_url))

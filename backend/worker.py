# backend/worker.py

import os
import redis
from rq import Worker, Queue, Connection

# The worker will listen on the 'default' queue
listen = ['default']

# Get the Redis URL from environment variables, with a fallback for local development
redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')

conn = redis.from_url(redis_url)

if __name__ == '__main__':
    with Connection(conn):
        worker = Worker(map(Queue, listen))
        worker.work()
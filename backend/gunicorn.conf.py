"""Gunicorn settings for the backend image. Sizes come from the environment."""

import os
from pathlib import Path

from app.logging import gunicorn_log_config

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"

# Threads, because requests spend most of their time waiting on PostgreSQL,
# Redis or a model provider; each worker keeps its own connection pools.
worker_class = "gthread"
workers = int(os.environ.get("GUNICORN_WORKERS", "2"))
threads = int(os.environ.get("GUNICORN_THREADS", "4"))

# For gthread workers this is the worker's heartbeat, not a request limit:
# Nginx's proxy_read_timeout bounds how long a request may take.
timeout = 30
graceful_timeout = 30
# Longer than Nginx keeps an idle upstream connection, so Nginx closes first.
keepalive = 75
# Replaces each worker after a while, which bounds any slow memory growth.
max_requests = 2000
max_requests_jitter = 200
# The heartbeat file lives in memory, not on the container's disk, as
# Gunicorn's docs advise for containers. No data is written there. Outside
# Linux (gunicorn run directly on a Mac for a benchmark) there is no
# /dev/shm, and Gunicorn's default temporary directory is used.
_SHARED_MEMORY = "/dev/shm"  # noqa: S108
worker_tmp_dir = _SHARED_MEMORY if Path(_SHARED_MEMORY).is_dir() else None
# The runtime control socket (gunicornc) is not used: the container's
# orchestrator starts, scales and stops the server.
control_socket_disable = True

# The app writes its own access log line, with the request id and duration.
accesslog = None
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "INFO").lower()
logconfig_dict = gunicorn_log_config(os.environ.get("LOG_LEVEL", "INFO"))

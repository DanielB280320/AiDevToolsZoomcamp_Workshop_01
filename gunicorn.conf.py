"""Gunicorn configuration.

architecture.md §1 chose Gunicorn plus WhiteNoise over a separate nginx: a
household-scale app serving five-plus people does not need a second process to
hand out a stylesheet.
"""

import multiprocessing
import os

bind = os.environ.get("BIND", "0.0.0.0:8000")

# Sync workers. Every view here is a short database round trip with no outbound
# calls, so there is nothing for an async worker to overlap.
workers = int(os.environ.get("WEB_CONCURRENCY", multiprocessing.cpu_count() * 2 + 1))
worker_class = "sync"
timeout = 30

# The app is behind a TLS-terminating proxy in every documented deployment, and
# prod.py trusts X-Forwarded-Proto. Say so here too, so a request forwarded by
# something other than the documented proxy is not silently trusted.
forwarded_allow_ips = os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1")

accesslog = "-"
errorlog = "-"
capture_output = True

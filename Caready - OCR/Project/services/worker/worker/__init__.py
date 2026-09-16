"""Caready background workers.

Job implementations land here milestone by milestone:

    M2  icr_extract, cross_check, phash_index
    M5  price_compute
    M6  vision_detect, grade_compute
    M8  pii_purge, anchor_recompute

`main.py` is the worker process; each job module registers a callable that RQ
enqueues by dotted path.
"""

__version__ = "0.1.0"

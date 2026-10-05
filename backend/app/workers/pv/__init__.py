"""Worker boundary for PV-owned safety background jobs.

PV workers reuse the shared coordination, export, and object-storage primitives
but never query or mutate EDC clinical tables or CTMS operational tables.
"""

PV_WORKER_PACKAGE = "app.workers.pv"

__all__ = ["PV_WORKER_PACKAGE"]

"""Worker for batch PV/EDC adverse-event reconciliation jobs.

Reconciliation is one-way and read-only over the approved minimized
Safety_Operational_Projection; this worker never mutates any EDC clinical
record. Concrete behavior lands in the reconciliation task; this module
establishes the additive worker boundary.
"""

from __future__ import annotations

WORKER_NAME = "pv-reconciliation"

__all__ = ["WORKER_NAME"]

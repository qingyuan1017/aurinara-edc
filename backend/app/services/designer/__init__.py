"""Designer_Module service boundary.

Owns the design-time Study_Design lifecycle (draft, publish, version, amend)
and all Designer_Definitions. Operational EDC code never writes through this
package; it reads published designs through the Design_Consumption_Contract.

The ``DesignConsumptionService`` is that read port: it exposes only published
design content as frozen view objects and is the sole way the EDC_Module reads a
``Published_Design`` (R2.5, R2.6).
"""

from app.services.designer.design_consumption_service import (
    DesignConsumptionService,
    design_consumption_service,
)

__all__ = [
    "DesignConsumptionService",
    "design_consumption_service",
]

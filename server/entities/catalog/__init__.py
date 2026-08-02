"""Catalog ORM models.

Importing every entity here registers all tables (and their foreign keys) on
``Base.metadata``. Without this, a foreign key whose target table's module was
never imported — e.g. ``sku_job.job_id`` -> ``job.id`` — fails to resolve at
flush time with ``NoReferencedTableError``.
"""

from entities.catalog.attribute_master import AttributeMaster
from entities.catalog.base import Base
from entities.catalog.brand import Brand
from entities.catalog.job import Job
from entities.catalog.job_attribute import JobAttribute
from entities.catalog.marketplace import Marketplace
from entities.catalog.sku_job import SkuJob
from entities.catalog.sku_marketplace_attribute_value import SkuMarketplaceAttributeValue

__all__ = [
    "AttributeMaster",
    "Base",
    "Brand",
    "Job",
    "JobAttribute",
    "Marketplace",
    "SkuJob",
    "SkuMarketplaceAttributeValue",
]

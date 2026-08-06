"""Catalog ORM models.

Importing every entity here registers all tables (and their foreign keys) on
``Base.metadata``. Without this, a foreign key whose target table's module was
never imported — e.g. ``sku_generation_job.job_id`` -> ``job.id`` — fails to resolve at
flush time with ``NoReferencedTableError``.
"""

from entities.catalog.attribute_master import AttributeMaster
from entities.catalog.base import Base
from entities.catalog.brand import Brand
from entities.catalog.category import Category
from entities.catalog.category_closure import CategoryClosure
from entities.catalog.job import Job
from entities.catalog.job_attribute import JobAttribute
from entities.catalog.marketplace import Marketplace
from entities.catalog.sku_generation_job import SkuGenerationJob
from entities.catalog.sku_marketplace_attribute_value import SkuMarketplaceAttributeValue
from entities.catalog.sku_master import SkuMaster

__all__ = [
    "AttributeMaster",
    "Base",
    "Brand",
    "Category",
    "CategoryClosure",
    "Job",
    "JobAttribute",
    "Marketplace",
    "SkuGenerationJob",
    "SkuMarketplaceAttributeValue",
    "SkuMaster",
]

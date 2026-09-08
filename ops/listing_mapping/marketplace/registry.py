"""Resolve marketplace adapters by MarketplaceId."""

from __future__ import annotations

from listing_mapping.marketplace import MarketplaceId
from listing_mapping.marketplace.amazon import AmazonAdapter
from listing_mapping.marketplace.base import MarketplaceAdapter
from listing_mapping.marketplace.flipkart import FlipkartAdapter
from listing_mapping.marketplace.myntra import MyntraAdapter

_ADAPTERS: dict[MarketplaceId, MarketplaceAdapter] = {
    MarketplaceId.AMAZON: AmazonAdapter(),
    MarketplaceId.FLIPKART: FlipkartAdapter(),
    MarketplaceId.MYNTRA: MyntraAdapter(),
}


def get_adapter(marketplace_id: MarketplaceId) -> MarketplaceAdapter:
    try:
        return _ADAPTERS[marketplace_id]
    except KeyError as exc:
        raise ValueError(f"No adapter registered for {marketplace_id.value}") from exc

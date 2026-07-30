-- 001_sku.sql
-- Adds catalog SKU master used by generate persistence (sku_job.sku_id).
-- Apply manually until Alembic is introduced.

CREATE TABLE IF NOT EXISTS sku (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    external_id UUID NOT NULL UNIQUE,
    product_key TEXT NOT NULL UNIQUE,
    brand_id BIGINT REFERENCES brand (id),
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    primary_image_url TEXT,
    pim_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS sku_brand_id_idx ON sku (brand_id);

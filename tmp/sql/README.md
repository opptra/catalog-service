# Human-run SQL for listing template fill / category junction cleanup.
#
# Apply in order (do not let the agent run these):
#   1. 001_category_intelligence_and_listing.sql
#   2. 002_bed_linen_listing_columns.sql  (set :cm_id / :lt_id first)
#
# Also upload the blank BED_LINEN_SET.xlsm via PUT /api/catalog/listing-template
# (or point listing_template.gcs_object_key at the uploaded object).

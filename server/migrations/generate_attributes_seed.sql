-- Seed attribute_master rows required by generate persistence.
-- Safe to re-run: skips names that already exist.

INSERT INTO attribute_master (external_id, name, data_type, allows_quantity, group_label, status_group)
SELECT gen_random_uuid(), v.name, v.data_type, v.allows_quantity, v.group_label, v.status_group
FROM (
    VALUES
        ('title', 'text', false, 'listing_text', 'content'),
        ('bullet_points', 'json', false, 'listing_text', 'content'),
        ('item_highlights', 'json', false, 'listing_text', 'content'),
        ('hero', 'image_uri', true, 'listing_images', 'content'),
        ('infographic', 'image_uri', true, 'listing_images', 'content'),
        ('lifestyle', 'image_uri', true, 'listing_images', 'content'),
        ('a_plus', 'image_uri', true, 'listing_images', 'content')
) AS v(name, data_type, allows_quantity, group_label, status_group)
WHERE NOT EXISTS (
    SELECT 1 FROM attribute_master am WHERE am.name = v.name
);

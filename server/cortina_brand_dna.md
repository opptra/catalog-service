# Brand DNA: Cortina
## Visual Cataloging Configuration

---

## IDENTITY

- **brand_name**: Cortina
- **brand_description**: Direct-manufacturer home furnishings brand focused on affordable, premium-looking curtains and protective furniture covers.
- **brand_personality_traits**: [trustworthy, practical, style-forward]
- **brand_voice_tone**: warm
- **brand_premium_level**: mid-premium

---

## TARGET AUDIENCE

- **target_audience_primary**: Value-conscious urban households upgrading living-room and bedroom decor with functional products.
- **target_audience_secondary**: Small hospitality buyers (HoReCa), renters, and gift shoppers seeking home-improvement products.
- **target_age_range**: 24-50
- **target_gender_profile**: gender neutral

---

## VISUAL IDENTITY

### Color Palette (reference, not prescription)
These are the brand's core colors. The builder has them as a PALETTE to draw from - but should REASON about which colors work best for each specific image based on the product's own colors, the chosen background, readability needs, and the mood of the shot.

- **brand_colors_primary**: [#FFFFFF (White), #2F2F2F (Charcoal)]
- **brand_colors_secondary**: [#8A8F98 (Cool Gray), #DCC7A1 (Warm Beige)]
- **accent_color_rules**: Use restrained accents for callouts and badges; never overpower product fabric color or blackout demonstration.

### Color Personality (this is what the builder actually uses to REASON)
- **color_temperature**: neutral - balanced warm/cool for modern Indian interiors
- **color_energy**: muted - premium, clean, non-neon presentation
- **color_mood**: calm, reliable, homely, practical-elegant
- **when_to_use_exact_brand_colors**: Header chips, icon badges, feature ribbons, and trust blocks where brand recognition matters.
- **when_to_use_complementary_colors**: Background walls, card surfaces, infographic panels, and props; use warm creams, taupe, soft slate, dusty pastels to support many curtain colors.
- **banned_colors**: [neon green, neon magenta, highly saturated cyber blue]
- **text_color_reasoning**: Use near-black on light surfaces and white on dark surfaces; always prioritize readability over strict palette matching.

### Mood & Style
- **visual_mood**: clean
- **photography_style**: catalog

### Typography
(Fonts for AI-generated text elements - infographic callouts, dimension labels, badges)
- **primary_font**: Montserrat Bold - used for headings and short claim blocks; modern, high legibility, marketplace-friendly.
- **secondary_font**: Open Sans Regular - used for explanatory copy and callout details; neutral and readable at small sizes.
- **dimension_font**: DIN Pro Medium - used for LBH and measurement overlays; technical clarity.
- **font_pairing_rationale**: Montserrat gives premium modern emphasis while Open Sans keeps details easy to scan; DIN adds engineering-like precision for dimensions.
- **font_color_reasoning**: Choose contrast-first per image; do not force a single color if background changes.
- **banned_font_styles**: [script/cursive, brush lettering, comic fonts]

---

## RESTRICTIONS

### Anti-Patterns (visual things to ALWAYS avoid)
- Overcrowded composition with too many props competing with curtain texture.
- Exaggerated blackout claims without visual proof context.

### Forbidden Visual Styles
- Cartoon-style rendering

### Forbidden Contexts
- Unrealistic fantasy environments not resembling homes or practical interiors.

### Forbidden Audience Representations
- Children in unsafe situations

### Forbidden Moods
- Dark, horror, gothic

---

## BRAND ASSETS

- **brand_logo_primary**: https://cortinaindia.com/cdn/shop/files/cortinalogo_140x.png?v=1735900797
- **brand_logo_alternate**: https://cortinaindia.com/cdn/shop/files/cortinalogo_140x.png
- **logo_usage_in_catalog**: Keep logo small and non-intrusive; avoid placing over curtain focal folds or measurement diagrams.

---

## PRODUCT SCOPE

### Categories
- Curtains & Drapes
- Home Furnishing Covers

### Subcategories
- Window Curtains
- Door Curtains
- Long Door Curtains

---

## BRAND-SPECIFIC NEGATIVE PROMPTS
(These get ADDED to universal negative prompts for all images of this brand)
```json
[
  "overcrowded room clutter, distracting prop-heavy compositions",
  "cartoon, anime, 3d render, painterly, illustration style",
  "gloomy horror mood, gothic shadows, unsafe domestic scenarios"
]
```

---

## LIFESTYLE CONCEPT POOL

### Philosophy (NOT a scene menu - reason per product)
DO NOT select from pre-defined scene lists. Instead, reason about each product individually:
1. What are THIS product's 3 most distinctive visual features? (color, shape, texture, material)
2. What WORLD does this product naturally belong in? (derive from visual identity, not category)
3. What TIME OF DAY creates the most compelling light interaction with this product's colors?
4. What SURFACE/TERRAIN reflects this product's personality?
5. What ATMOSPHERIC ELEMENTS complete the story?

### Brand Constraints for Lifestyle:
- Match brand color_temperature and visual_mood from the VISUAL IDENTITY section above
- Scale: Always respect LBH from PIM
- No humans/hands (marketplace compliance)

### What makes a GOOD lifestyle image:
- Scene feels tailored to the specific curtain color/material and room use.
- Product coverage, fall, pleats, and drape behavior are clearly visible.
- Product is the clear hero; props only support practicality and decor context.

### What makes a BAD lifestyle image:
- Reused identical room scene across all SKUs.
- Background stronger than product texture/opacity cues.
- Overprocessed HDR look that makes fabric appear fake.

---

## INFOGRAPHIC RULES
(Brand-specific rules for infographic callouts)

- **preferred_layout_styles**: [side_panel_icons, overlay_cards, exploded_spotlight]
- **callout_count_range**: [4, 6]
- **headline_font**: Use primary_font from Typography section above
- **callout_label_font**: Use primary_font from Typography section above
- **callout_detail_font**: Use secondary_font from Typography section above
- **callout_line_style**: solid-thin
- **callout_color_reasoning**: Use brand primary/secondary colors for headers and key badges; use complementary neutrals for card fills; readability and feature hierarchy come first.
- **icon_style**: Circular or rounded-square minimalist icon badges with high-contrast symbols.
- **callout_card_style**: Rounded rectangle cards with soft shadow and accent border.
- **background_reasoning**: Use realistic interior surfaces and room contexts; avoid plain gradient backgrounds.
- **selling_angle_priorities**: Blackout effectiveness > room aesthetics > thermal/noise comfort > easy installation > wash care.
- **allowed_callout_content**: [selling_benefits, durability, materials_as_benefit, age_suitability]
- **forbidden_callout_content**: [pricing, competitor_comparisons, unverified_claims, obvious_features]


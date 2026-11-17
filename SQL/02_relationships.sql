
-- =========================================
-- 02_RELATIONSHIPS.SQL
-- Add foreign key relationships
-- =========================================


-- 1. BRAND RELATIONSHIPS

ALTER TABLE brand
ADD CONSTRAINT fk_brand_corporate_group
FOREIGN KEY (group_id)
REFERENCES corporate_group(group_id);

ALTER TABLE brand
ADD CONSTRAINT fk_brand_market_segment
FOREIGN KEY (segment_id)
REFERENCES market_segment(segment_id);


-- 2. PERFUME RELATIONSHIPS

ALTER TABLE perfume
ADD CONSTRAINT fk_perfume_brand
FOREIGN KEY (brand_id)
REFERENCES brand(brand_id);

ALTER TABLE perfume
ADD CONSTRAINT fk_perfume_gender
FOREIGN KEY (gender_id)
REFERENCES gender(gender_id);

ALTER TABLE perfume
ADD CONSTRAINT fk_perfume_concentration
FOREIGN KEY (concentration_id)
REFERENCES concentration(concentration_id);

ALTER TABLE perfume
ADD CONSTRAINT fk_perfume_fragrance_family
FOREIGN KEY (family_id)
REFERENCES fragrance_family(family_id);


-- 3. PERFUME ACCORD RELATIONSHIPS

ALTER TABLE perfume_accord
ADD CONSTRAINT fk_perfume_accord_perfume
FOREIGN KEY (perfume_id)
REFERENCES perfume(perfume_id)
ON DELETE CASCADE;

ALTER TABLE perfume_accord
ADD CONSTRAINT fk_perfume_accord_accord
FOREIGN KEY (accord_id)
REFERENCES accord(accord_id);


-- 4. PERFUME NOTE RELATIONSHIPS

ALTER TABLE perfume_note
ADD CONSTRAINT fk_perfume_note_perfume
FOREIGN KEY (perfume_id)
REFERENCES perfume(perfume_id)
ON DELETE CASCADE;

ALTER TABLE perfume_note
ADD CONSTRAINT fk_perfume_note_note
FOREIGN KEY (note_id)
REFERENCES note(note_id);

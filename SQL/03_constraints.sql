
-- =========================================
-- 03_CONSTRAINTS.SQL
-- Add UNIQUE and CHECK constraints
-- =========================================


-- 1. UNIQUE CONSTRAINTS ON LOOKUP TABLES

ALTER TABLE corporate_group
ADD CONSTRAINT uq_corporate_group_name
UNIQUE (group_name);

ALTER TABLE market_segment
ADD CONSTRAINT uq_market_segment_name
UNIQUE (segment_name);

ALTER TABLE gender
ADD CONSTRAINT uq_gender_name
UNIQUE (gender_name);

ALTER TABLE concentration
ADD CONSTRAINT uq_concentration_name
UNIQUE (concentration_name);

ALTER TABLE fragrance_family
ADD CONSTRAINT uq_fragrance_family_name
UNIQUE (family_name);

ALTER TABLE accord
ADD CONSTRAINT uq_accord_name
UNIQUE (accord_name);

ALTER TABLE note
ADD CONSTRAINT uq_note_name
UNIQUE (note_name);


-- 2. UNIQUE CONSTRAINTS ON BRAND AND PERFUME

ALTER TABLE brand
ADD CONSTRAINT uq_brand_name
UNIQUE (brand_name);

ALTER TABLE perfume
ADD CONSTRAINT uq_perfume_url
UNIQUE (url);


-- 3. PERFUME CHECK CONSTRAINTS

ALTER TABLE perfume
ADD CONSTRAINT chk_rating_value
CHECK (rating_value BETWEEN 1 AND 5);

ALTER TABLE perfume
ADD CONSTRAINT chk_rating_count
CHECK (rating_count >= 0);

ALTER TABLE perfume
ADD CONSTRAINT chk_release_year
CHECK (release_year BETWEEN 1500 AND 2100);


-- 4. PERFUME ACCORD CHECK CONSTRAINTS

ALTER TABLE perfume_accord
ADD CONSTRAINT chk_accord_rank
CHECK (accord_rank >= 1);


-- 5. PERFUME NOTE CHECK CONSTRAINTS

ALTER TABLE perfume_note
ADD CONSTRAINT chk_note_layer
CHECK (note_layer IN ('Top', 'Middle', 'Base'));

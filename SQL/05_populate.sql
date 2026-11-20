
-- =========================================
-- 05_POPULATE.SQL
-- Populate the normalized database
-- Source: stg_perfume
-- =========================================


-- =========================================
-- PART 1: POPULATE LOOKUP TABLES
-- =========================================

-- 1. MARKET SEGMENT
INSERT INTO market_segment (segment_name)
SELECT DISTINCT market_segment
FROM stg_perfume
WHERE market_segment IS NOT NULL
  AND TRIM(market_segment) <> '';


-- 2. CORPORATE GROUP
INSERT INTO corporate_group (group_name)
SELECT DISTINCT corporate_group
FROM stg_perfume
WHERE corporate_group IS NOT NULL
  AND TRIM(corporate_group) <> '';


-- 3. GENDER
INSERT INTO gender (gender_name)
SELECT DISTINCT gender
FROM stg_perfume
WHERE gender IS NOT NULL
  AND TRIM(gender) <> '';


-- 4. CONCENTRATION
INSERT INTO concentration (concentration_name)
SELECT DISTINCT concentration
FROM stg_perfume
WHERE concentration IS NOT NULL
  AND TRIM(concentration) <> '';


-- 5. FRAGRANCE FAMILY
INSERT INTO fragrance_family (family_name)
SELECT DISTINCT fragrance_family
FROM stg_perfume
WHERE fragrance_family IS NOT NULL
  AND TRIM(fragrance_family) <> '';


-- 6. ACCORD
INSERT INTO accord (accord_name)
SELECT DISTINCT TRIM(accord_value)
FROM stg_perfume,
     UNNEST(STRING_TO_ARRAY(main_accords, ';')) AS accord_value
WHERE accord_value IS NOT NULL
  AND TRIM(accord_value) <> '';


-- 7. NOTE
INSERT INTO note (note_name)
SELECT DISTINCT TRIM(note_value)
FROM stg_perfume,
     UNNEST(
         STRING_TO_ARRAY(
             CONCAT_WS(
                 ';',
                 top_notes,
                 middle_notes,
                 base_notes
             ),
             ';'
         )
     ) AS note_value
WHERE note_value IS NOT NULL
  AND TRIM(note_value) <> '';


-- =========================================
-- PART 2: POPULATE BRAND
-- =========================================

INSERT INTO brand (
    brand_name,
    group_id,
    segment_id
)
SELECT DISTINCT
    s.brand,
    cg.group_id,
    ms.segment_id
FROM stg_perfume s
JOIN corporate_group cg
    ON s.corporate_group = cg.group_name
JOIN market_segment ms
    ON s.market_segment = ms.segment_name;



-- =========================================
-- PART 3: POPULATE PERFUME
-- =========================================

INSERT INTO perfume (
    perfume_id,
    name,
    release_year,
    rating_value,
    rating_count,
    url,
    brand_id,
    gender_id,
    concentration_id,
    family_id
)
SELECT
    s.perfume_id,
    s.name,
    s.release_year,
    s.rating_value,
    s.rating_count,
    s.url,
    b.brand_id,
    g.gender_id,
    c.concentration_id,
    ff.family_id

FROM stg_perfume s

JOIN brand b
    ON s.brand = b.brand_name

JOIN gender g
    ON s.gender = g.gender_name

JOIN concentration c
    ON s.concentration = c.concentration_name

JOIN fragrance_family ff
    ON s.fragrance_family = ff.family_name;




-- =========================================
-- PART 4: POPULATE PERFUME_ACCORD
-- =========================================

INSERT INTO perfume_accord (
    perfume_id,
    accord_id,
    accord_rank
)
SELECT DISTINCT ON (p.perfume_id, a.accord_id)
    p.perfume_id,
    a.accord_id,
    x.accord_rank

FROM stg_perfume s

CROSS JOIN LATERAL
    UNNEST(STRING_TO_ARRAY(s.main_accords, ';'))
    WITH ORDINALITY AS x(accord_name, accord_rank)

JOIN perfume p
    ON s.perfume_id = p.perfume_id

JOIN accord a
    ON TRIM(x.accord_name) = a.accord_name

ORDER BY
    p.perfume_id,
    a.accord_id,
    x.accord_rank;



-- =========================================
-- PART 5: POPULATE PERFUME_NOTE
-- =========================================

INSERT INTO perfume_note (
    perfume_id,
    note_id,
    note_layer
)

-- TOP NOTES
SELECT DISTINCT
    s.perfume_id,
    n.note_id,
    'Top'
FROM stg_perfume s
CROSS JOIN LATERAL
    UNNEST(STRING_TO_ARRAY(s.top_notes, ';'))
    AS x(note_name)
JOIN note n
    ON TRIM(x.note_name) = n.note_name
WHERE TRIM(x.note_name) <> ''

UNION

-- MIDDLE NOTES
SELECT DISTINCT
    s.perfume_id,
    n.note_id,
    'Middle'
FROM stg_perfume s
CROSS JOIN LATERAL
    UNNEST(STRING_TO_ARRAY(s.middle_notes, ';'))
    AS x(note_name)
JOIN note n
    ON TRIM(x.note_name) = n.note_name
WHERE TRIM(x.note_name) <> ''

UNION

-- BASE NOTES
SELECT DISTINCT
    s.perfume_id,
    n.note_id,
    'Base'
FROM stg_perfume s
CROSS JOIN LATERAL
    UNNEST(STRING_TO_ARRAY(s.base_notes, ';'))
    AS x(note_name)
JOIN note n
    ON TRIM(x.note_name) = n.note_name
WHERE TRIM(x.note_name) <> '';

-- clean up the staging table --
DROP TABLE stg_perfume;

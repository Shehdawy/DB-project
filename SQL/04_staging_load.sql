
-- =========================================
-- 04_STAGING_LOAD.SQL
-- Create staging table for cleaned CSV data
-- 16 columns from perfume_cleaned.csv
-- =========================================

CREATE UNLOGGED TABLE stg_perfume (

    perfume_id BIGINT,
    name VARCHAR(250),
    brand VARCHAR(150),
    market_segment VARCHAR(100),
    corporate_group VARCHAR(150),
    gender VARCHAR(50),
    concentration VARCHAR(100),
    release_year SMALLINT,
    rating_value NUMERIC(3,2),
    rating_count INTEGER,
    main_accords TEXT,
    top_notes TEXT,
    middle_notes TEXT,
    base_notes TEXT,
    fragrance_family VARCHAR(100),
    url TEXT

);
\copy stg_perfume FROM 'data/perfume_cleaned_.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');

SELECT COUNT(*) FROM stg_perfume;

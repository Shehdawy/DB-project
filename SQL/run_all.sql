\set ON_ERROR_STOP on
\echo 'WARNING: This is a DESTRUCTIVE REBUILD of the project tables. Run only against the intended perfume database.'
\ir 01_tables.sql
\ir 02_relationships.sql
\ir 03_constraints.sql
\ir 04_staging_load.sql
\ir 05_populate.sql
\ir 06_indexes.sql
\ir 07_validation.sql
\ir 08_business_queries.sql
\echo 'Database import, verification and baseline business views completed.'

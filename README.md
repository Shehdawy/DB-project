# Perfume Intelligence & Analytics

### A PostgreSQL Database Management System Project with an Interactive Streamlit Dashboard

A data-driven academic project that transforms a **40,000-record perfume dataset** into a normalized **PostgreSQL relational database**, validates the imported data, and answers analytical questions through SQL views. An optional **Python + Streamlit** dashboard provides a more accessible way to explore the same database.

> **Project focus:** Database design, relational modeling, SQL data processing, integrity, and business queries. The dashboard is an additional visualization and exploration layer—not a replacement for the PostgreSQL implementation.

## Team Members

- **Omar ElShehdawy**
- **Yusuf Mansour**
- **Seif Ali**
- **Mariam Sherif**

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Objectives](#objectives)
3. [Technology Stack](#technology-stack)
4. [Dataset](#dataset)
5. [Database Design](#database-design)
6. [Repository Structure](#repository-structure)
7. [PostgreSQL Setup and Import](#postgresql-setup-and-import)
8. [SQL File Walkthrough](#sql-file-walkthrough)
9. [Data Validation](#data-validation)
10. [Business Queries](#business-queries)
11. [Optional Streamlit Dashboard](#optional-streamlit-dashboard)
12. [Example Queries](#example-queries)
13. [Troubleshooting](#troubleshooting)
14. [Academic Demonstration](#academic-demonstration)
15. [Team](#team)

## Project Overview

Raw perfume data is provided as one CSV file with multi-valued fields for main accords and fragrance notes. The core project imports this source into a staging table, separates it into connected relational entities, creates integrity constraints and indexes, and exposes ten reusable business-analysis views.

The accompanying dashboard uses **live PostgreSQL queries**, not fabricated records, to display searchable perfume information, metrics, charts, ingredient analysis, and brand comparisons. It does **not** contain a perfume recommendation system.

### High-level Data Flow

```text
perfume_cleaned_.csv (40,000 rows / 16 columns)
                  |
                  v
       stg_perfume (staging table)
                  |
                  v
         SQL normalization
                  |
                  v
     PostgreSQL: 11 related tables
                  |
           +------+------+
           |             |
           v             v
   SQL business views   Parameterized SQL queries
     (BQ01–BQ10)        (filters + search)
           |             |
           +------+------+
                  |
                  v
         Streamlit dashboard
          (optional extension)
```

## Objectives

- Model perfume information as an **11-table relational database** based on the provided ERD.
- Preserve perfume IDs and meaningful associations between perfumes, brands, notes, accords, and other dimensions.
- Enforce **primary keys, foreign keys, UNIQUE constraints, and CHECK constraints**.
- Import the actual CSV into PostgreSQL and normalize semicolon-separated data.
- Build SQL indexes to support joins and text search.
- Validate record counts and relationship integrity against the source data.
- Implement **10 business-question views (BQ01–BQ10)**.
- Make database insights approachable through an **optional, single-file Streamlit dashboard**.

## Technology Stack

| Layer | Technology | Role |
| --- | --- | --- |
| Database | PostgreSQL | Relational data storage, constraints, indexes, views |
| Database tools | pgAdmin 4, `psql` | Inspect tables and execute SQL scripts |
| Source data | CSV | Original perfume records |
| Backend | Python 3.11+ | Dashboard and analytics logic |
| Database access | SQLAlchemy + psycopg 3 | Parameterized database queries |
| Data analysis | Pandas + NumPy | Aggregation and tabular processing |
| Dashboard | Streamlit | Single-page interactive interface |
| Visualizations | Plotly | Interactive data charts |
| Search | RapidFuzz + PostgreSQL `pg_trgm` | Typo tolerance and approximate text matching |

## Dataset

Source: [`data/perfume_cleaned_.csv`](data/perfume_cleaned_.csv)

The dataset contains **40,000 perfumes** with **16 original columns**:

| Field | Description |
| --- | --- |
| `Perfume_ID` | Source perfume identifier |
| `Name` | Perfume name |
| `Brand` | Brand name |
| `Market_Segment` | Market segment |
| `Corporate_Group` | Parent company or corporate group |
| `Gender` | Target gender classification |
| `Concentration` | Perfume concentration (e.g., EDP / EDT) |
| `Release_Year` | Release year |
| `Rating_Value` | Recorded average rating |
| `Rating_Count` | Number of rating votes |
| `Main_Accords` | Semicolon-separated accords |
| `Top_Notes` | Semicolon-separated top notes |
| `Middle_Notes` | Semicolon-separated middle notes |
| `Base_Notes` | Semicolon-separated base notes |
| `Fragrance_Family` | Fragrance family classification |
| `URL` | Original record source URL |


### Expected Import Totals

These are **validation targets** based on the supplied source and project specification, not values hardcoded into the dashboard:

| Table / relationship | Expected rows |
| --- | ---: |
| `perfume` | 40,000 |
| `brand` | 1,525 |
| `accord` | 87 |
| `note` | 1,823 |
| `perfume_accord` | 347,456 |
| `perfume_note` | 388,317 |

## Database Design

The relational model contains **11 tables**:

| Type | Tables | Purpose |
| --- | --- | --- |
| Dimensions | `market_segment`, `corporate_group`, `gender`, `concentration`, `fragrance_family` | Classifications and reference values |
| Vocabulary | `accord`, `note` | Unique fragrance attributes |
| Main entities | `brand`, `perfume` | Brand information and perfume records |
| Junction tables | `perfume_accord`, `perfume_note` | Many-to-many relationships |

### Key Relationships

- **Market segment → Brand:** one-to-many.
- **Corporate group → Brand:** one-to-many.
- **Brand → Perfume:** one-to-many.
- **Gender / Concentration / Fragrance family → Perfume:** one-to-many.
- **Perfume ↔ Accord:** many-to-many, via `perfume_accord` with `accord_rank`.
- **Perfume ↔ Note:** many-to-many, via `perfume_note` with `note_layer` (`Top`, `Middle`, or `Base`).

The note junction uses a composite key that includes `note_layer`, so the same note may occur in more than one layer of the same perfume.

For the complete academic model, see [`docs/ER_Tables_and_ERD.pdf`](docs/ER_Tables_and_ERD.pdf). The SQL design and query plan are included in [`docs/sql.pdf`](docs/sql.pdf).

## PostgreSQL Setup and Import

### 1. Requirements

Install PostgreSQL (including the `psql` command-line client), pgAdmin 4, and Python if you also plan to run the dashboard.

The commands below use Windows PowerShell. Run them **from the project root**, the folder containing `database/` and `data/`.

### 2. Create a dedicated PostgreSQL database

**Using pgAdmin:** Connect to your PostgreSQL server, right-click **Databases → Create → Database**, and name it `perfume_demo` for a clean demonstration.

Or run:

```powershell
createdb -h localhost -p 5432 -U postgres perfume_demo
```

If `createdb` / `psql` are not found in PATH, use their full executable paths. For example, on one Windows installation:

```powershell
& "D:\DBMS\bin\createdb.exe" -h localhost -p 5432 -U postgres perfume_demo
```

### 3. Recommended: run the full SQL pipeline

> **Warning: `run_all.sql` rebuilds project tables and removes their existing data.** Use a newly created or disposable database only. **Do not run it on an already populated working database you need to preserve.**

```powershell
& "D:\DBMS\bin\psql.exe" -h localhost -p 5432 -U postgres -d perfume_demo -v ON_ERROR_STOP=1 -f database/run_all.sql
```

A successful pipeline creates and populates the tables, imports the CSV, builds indexes, performs validation, and creates the business views. It prints a completion message when all scripts finish.

### 4. Alternative: execute files one by one

To demonstrate the complete database process to an instructor, execute each file in order:

```powershell
$psql = "D:\DBMS\bin\psql.exe"
$db = "perfume_demo"

& $psql -U postgres -d $db -v ON_ERROR_STOP=1 -f database/01_tables.sql
& $psql -U postgres -d $db -v ON_ERROR_STOP=1 -f database/02_relationships.sql
& $psql -U postgres -d $db -v ON_ERROR_STOP=1 -f database/03_constraints.sql
& $psql -U postgres -d $db -v ON_ERROR_STOP=1 -f database/04_staging_load.sql
& $psql -U postgres -d $db -v ON_ERROR_STOP=1 -f database/05_populate.sql
& $psql -U postgres -d $db -v ON_ERROR_STOP=1 -f database/06_indexes.sql
& $psql -U postgres -d $db -v ON_ERROR_STOP=1 -f database/07_validation.sql
& $psql -U postgres -d $db -v ON_ERROR_STOP=1 -f database/08_business_queries.sql
```

**Why run File 04 with `psql`?** It uses `\copy` to load a file located on the client computer. `\copy` is a `psql` meta-command and does not execute directly in pgAdmin Query Tool.

If you instead use pgAdmin to import the CSV manually, first create `stg_perfume`, then use **Import/Export Data** on that table with CSV format and Header enabled. **Do not import twice** if `04_staging_load.sql` already executed `\copy`.


## SQL File Walkthrough

| File | What it does |
| --- | --- |
| `01_tables.sql` | Creates the seven lookup/vocabulary tables, the `brand` and `perfume` tables, and two junction tables. Defines primary keys. |
| `02_relationships.sql` | Adds foreign keys according to the ERD, including cascade deletion of perfume junction rows when their perfume is deleted. |
| `03_constraints.sql` | Enforces unique lookup names and URLs, valid rating/year/count ranges, valid note layers, and accord rank integrity. |
| `04_staging_load.sql` | Creates a 16-column unlogged staging table and loads the supplied CSV using `\copy`. |
| `05_populate.sql` | Inserts distinct dimension values, brand and perfume rows, and exploded accord/note relationships, then removes staging. |
| `06_indexes.sql` | Creates B-tree and GIN trigram indexes; updates PostgreSQL planner statistics. |
| `07_validation.sql` | Compares actual counts with expected counts and checks for invalid/orphaned relationships. |
| `08_business_queries.sql` | Creates the ten reusable analytics views (`vw_bq01` through `vw_bq10`). |
| `run_all.sql` | Runs all SQL files in the required order. **Destructive rebuild.** |

## Data Validation

The database is designed to verify imported data rather than alter it to match expected figures.

After loading, run the following in pgAdmin Query Tool (connected to the imported database):

```sql
SELECT COUNT(*) AS total_perfumes FROM perfume;
SELECT COUNT(*) AS total_brands FROM brand;
SELECT COUNT(*) AS total_accords FROM accord;
SELECT COUNT(*) AS total_notes FROM note;
SELECT COUNT(*) AS perfume_accord_links FROM perfume_accord;
SELECT COUNT(*) AS perfume_note_links FROM perfume_note;
```

For the full integrity checks, execute [`database/07_validation.sql`](database/07_validation.sql). Check `PASS`/`REVIEW` results and investigate any differences; do not silently force counts.

## Business Queries

The project includes ten predefined analytical views:

| View | Business question |
| --- | --- |
| `vw_bq01` | Which brands have the highest average ratings under a minimum-vote rule? |
| `vw_bq02` | How do market segments compare by perfume count and ratings? |
| `vw_bq03` | How are perfumes distributed across corporate groups? |
| `vw_bq04` | How do gender categories compare in size and rating? |
| `vw_bq05` | How are perfume concentrations distributed? |
| `vw_bq06` | How do releases and ratings vary by release decade? |
| `vw_bq07` | Which accords occur most frequently? |
| `vw_bq08` | Which notes occur most frequently in each layer? |
| `vw_bq09` | How are fragrance families represented and rated? |
| `vw_bq10` | Which perfumes have received the most rating votes? |

Try them directly in pgAdmin:

```sql
SELECT * FROM vw_bq01;
SELECT * FROM vw_bq07;
SELECT * FROM vw_bq08;
```

**Interpretation:** Dataset representation and ratings do not measure real-world perfume sales or market share. Rating trends by release year compare perfumes *released* in those periods; they are not historical ratings observed during those years.

##  Streamlit Dashboard

The dashboard is implemented entirely in **[`app.py`](app.py)** and connects to PostgreSQL using SQLAlchemy and psycopg. It is an additional interactive layer for exploring the database.

### Dashboard Features

- **Overview:** four essential metrics and dynamically calculated insights.
- **Explore perfumes:** unified search and sortable, paginated perfume records.
- **More analysis:** market/brand breakdowns, ingredients, ratings, release trends, brand comparisons, custom charts, quality checks, and export.
- **Search intelligence:** searches across names, brands, market categories, accords, and notes; supported typo correction and Arabic aliases.
- **Dynamic filtering:** all displayed statistics read from SQL queries using the current search/filter conditions.
- **Performance:** server-side pagination, parameterized queries, PostgreSQL indexes, and caching.
- **Exports:** download filtered data as CSV where provided by the interface.

The application uses real database records and does **not** provide perfume recommendations.

### Running the Dashboard (Windows / VS Code)

From the project root:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```


```dotenv
DATABASE_URL=postgresql+psycopg://postgres:YOUR_PASSWORD@localhost:5432/perfume_demo
DB_POOL_SIZE=5
CACHE_TTL_SECONDS=120
```

Start the dashboard:

```powershell
python -m streamlit run app.py
```

Open **http://localhost:8501** in your browser.

## Example Queries

**Find perfumes containing Amber in any note layer:**

```sql
SELECT DISTINCT p.perfume_id, p.name, b.brand_name
FROM perfume p
JOIN brand b ON p.brand_id = b.brand_id
JOIN perfume_note pn ON pn.perfume_id = p.perfume_id
JOIN note n ON n.note_id = pn.note_id
WHERE n.note_name ILIKE '%amber%'
ORDER BY p.name;
```

**Count perfumes in each market segment:**

```sql
SELECT ms.segment_name, COUNT(*) AS perfume_count
FROM perfume p
JOIN brand b ON p.brand_id = b.brand_id
JOIN market_segment ms ON b.segment_id = ms.segment_id
GROUP BY ms.segment_name
ORDER BY perfume_count DESC;
```

**Top-ranked accords by number of distinct perfumes:**

```sql
SELECT a.accord_name, COUNT(DISTINCT pa.perfume_id) AS perfume_count
FROM perfume_accord pa
JOIN accord a ON a.accord_id = pa.accord_id
GROUP BY a.accord_name
ORDER BY perfume_count DESC
LIMIT 15;
```

## Team

| Member |
| --- |
| Omar ElShehdawy |
| Yusuf Mansour |
| Seif Ali |
| Mariam Sherif |

---

"""Perfume Intelligence Dashboard — single-file Streamlit / PostgreSQL application.

The database and the source CSV (not synthetic Python data) are the only data sources.
Run: streamlit run app.py
"""
from __future__ import annotations

import json
import math
import os
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv
from rapidfuzz import fuzz, process
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

load_dotenv()
st.set_page_config(page_title="Perfume Intelligence Dashboard", page_icon="🧴", layout="wide", initial_sidebar_state="expanded")

# ────────────────────────────── Design system ──────────────────────────────
IVORY = "#F8F6F1"
INK = "#262724"
GOLD = "#AB8953"
MUTED = "#73736C"
PALETTE = ["#B29161", "#314C49", "#A9B5A3", "#866A70", "#D2A66F", "#718A9D", "#C2A6A1", "#778868"]

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Playfair+Display:wght@500;600;700&display=swap');
html,body,[class*="css"], [data-testid="stApp"] {font-family:'DM Sans',sans-serif;}
[data-testid="stAppViewContainer"] {background: #F8F6F1;}
[data-testid="stSidebar"] {background:#F1EEE7;border-right:1px solid #DFD9CC;}
[data-testid="stHeader"] {background:rgba(248,246,241,.85);}
.block-container {padding-top:1.25rem;padding-bottom:3rem;max-width:1660px;}
h1,h2,h3 {letter-spacing:-.035em;color:#262724;}
h1 {font-family:'Playfair Display',Georgia,serif !important;}
h2,h3 {font-weight:700;}
.hero {border:1px solid #E6E0D4;background:linear-gradient(118deg,#fffefa 0%,#F0E8D9 90%);border-radius:24px;padding:26px 34px;margin:0 0 18px;box-shadow:0 7px 24px rgba(54,47,29,.045);}
.hero .eyebrow {font-size:.72rem;letter-spacing:.22em;color:#A08458;font-weight:800;}
.hero h1 {font-family:'Playfair Display',Georgia,serif;font-size:clamp(1.7rem,3.8vw,3.15rem);font-weight:600;margin:8px 0 10px;line-height:1.2;}
.hero p {color:#68665F;margin:0;max-width:780px;line-height:1.6;}
[data-testid="stMetric"] {background:#FFFFFF;border:1px solid #EAE5DB;border-radius:17px;padding:18px 18px 13px;box-shadow:0 7px 20px rgba(45,42,34,.035);min-height:116px;}
[data-testid="stMetricLabel"] {color:#77766F;font-size:.8rem;}
[data-testid="stMetricValue"] {font-weight:700;color:#292E2A;font-size:1.56rem;}
[data-testid="stVerticalBlockBorderWrapper"] {border-radius:14px;}
[data-testid="stExpander"] {background:#FFFDF9;border:1px solid #E9E2D8;border-radius:12px;}
[data-baseweb="tab-list"] {gap:10px;}
button[data-baseweb="tab"] {border-radius:10px 10px 0 0;}
[data-testid="stSidebar"] .stButton button {width:100%;}
.stButton button[kind="primary"],.stDownloadButton button[kind="primary"]{background:#314C49;border-color:#314C49;color:white;}
.card-heading {font-size:.75rem;text-transform:uppercase;letter-spacing:.17em;color:#A18455;font-weight:700;}
.small-muted{color:#77736B;font-size:.87rem;}
.section-note{padding:10px 16px;background:#FCFAF5;border-left:3px solid #A98D5E;border-radius:5px;color:#6A645B;margin:10px 0;}
[data-testid="stPlotlyChart"] {background:#fff;border:1px solid #EEE9DF;border-radius:15px;padding:10px;}
</style>
"""

# ─────────────────────────── Database and caching ─────────────────────────
@st.cache_resource(show_spinner=False)
def get_database_connection() -> Engine:
    """One pooled PostgreSQL/psycopg engine reused by all dashboard queries."""
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is missing. Create a .env file using .env.example.")
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return create_engine(url, pool_pre_ping=True, pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
                         max_overflow=5, pool_recycle=1800, connect_args={"connect_timeout": 5})


def get_database_status() -> tuple[bool, str]:
    """Fail gracefully for missing/uninitialized databases."""
    try:
        with get_database_connection().connect() as conn:
            conn.execute(text("SELECT COUNT(*) FROM perfume")).scalar_one()
        return True, "Connected · PostgreSQL"
    except Exception as exc:
        return False, str(exc).split("\n")[0][:260]


@st.cache_data(ttl=120, max_entries=400, show_spinner=False)
def _cached_query(sql: str, params_json: str) -> pd.DataFrame:
    """Cache exact parameterized SQL + parameter values; never cache global unfiltered results for filtered inputs."""
    with get_database_connection().connect() as conn:
        return pd.read_sql_query(text(sql), conn, params=json.loads(params_json))


def run_query(sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
    return _cached_query(sql, json.dumps(params or {}, sort_keys=True, default=str))


@st.cache_data(ttl=120, show_spinner=False)
def get_filter_options() -> dict[str, Any]:
    """Values are from PostgreSQL dimension tables, not a Python approximation of the CSV."""
    options: dict[str, Any] = {}
    names = {
        "brand": ("brand", "brand_name"),
        "segment": ("market_segment", "segment_name"),
        "group": ("corporate_group", "group_name"),
        "gender": ("gender", "gender_name"),
        "concentration": ("concentration", "concentration_name"),
        "family": ("fragrance_family", "family_name"),
        "accord": ("accord", "accord_name"),
        "note": ("note", "note_name"),
    }
    for key, (table, column) in names.items():
        # Both identifiers are fixed developer-owned literals; never interpolated from user inputs.
        options[key] = run_query(f"SELECT {column} FROM {table} ORDER BY {column}")[column].tolist()
    r = run_query("SELECT MIN(release_year) AS min_year, MAX(release_year) AS max_year, COUNT(*) AS records FROM perfume").iloc[0]
    options["year_min"], options["year_max"], options["records"] = int(r.min_year), int(r.max_year), int(r.records)
    return options


# ───────────────────────────── Search intelligence ─────────────────────────
ARABIC_ALIASES = {
    "عنبر": "amber", "العنبر": "amber", "فانيليا": "vanilla", "الفانيليا": "vanilla",
    "عود": "oud", "العود": "oud", "مسك": "musk", "المسك": "musk", "نيش": "niche",
    "ديزاينر": "designer", "خشبي": "woody", "خشبيه": "woody", "حمضيات": "citrus",
    "برغموت": "bergamot", "برتقال": "orange", "زهري": "floral", "للجنسين": "unisex",
}
KNOWN_TYPOS = {"ambr":"amber", "vanila":"vanilla", "berggamot":"bergamot",
               "diorr":"dior", "nish":"niche", "desginer":"designer", "vannila":"vanilla"}
FILTER_FIELDS = ("brand", "segment", "group", "gender", "concentration", "family", "accord", "top", "middle", "base", "exclude_accord", "exclude_note")
SORT_COLUMNS = {
    "Most relevant": "relevance DESC, p.rating_count DESC, p.perfume_id",
    "Most votes": "p.rating_count DESC, p.perfume_id",
    "Highest rating": "p.rating_value DESC, p.rating_count DESC, p.perfume_id",
    "Newest release": "p.release_year DESC, p.perfume_id",
    "Oldest release": "p.release_year ASC, p.perfume_id",
    "Name A–Z": "p.name ASC, p.perfume_id",
    "Brand A–Z": "b.brand_name ASC, p.name ASC, p.perfume_id",
}


def _ar_norm(value: str) -> str:
    value = re.sub(r"[\u064b-\u065f\u0670\u0640]", "", value)
    return value.translate(str.maketrans({"أ":"ا", "إ":"ا", "آ":"ا", "ٱ":"ا", "ى":"ي", "ة":"ه"}))


def normalize_search_query(query: str) -> str:
    """Normalize Arabic variants, unicode, accents, punctuation, aliases, and whitespace."""
    s = unicodedata.normalize("NFKC", str(query)).casefold()
    s = _ar_norm(s)
    for original, replacement in sorted(ARABIC_ALIASES.items(), key=lambda p:-len(p[0])):
        s = re.sub(r"(?<!\w)" + re.escape(_ar_norm(original)) + r"(?!\w)", replacement, s)
    s = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))
    s = re.sub(r"[^\w\s/-]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _lexicon(options: dict[str, Any]) -> dict[str, tuple[str, str]]:
    """Construct a vocabulary entirely from real dimension values, plus safe conceptual aliases."""
    lex: dict[str, tuple[str, str]] = {}
    for key in ("note", "accord", "family", "brand", "concentration", "gender", "segment", "group"):
        category = "ingredient" if key in ("note", "accord") else key
        for canonical in options[key]:
            normalized = normalize_search_query(canonical)
            if normalized and (len(normalized)>=3 or key == "concentration"):
                # Preserve ingredient semantics on single words shared by families and notes.
                if normalized not in lex or category == "ingredient":
                    lex[normalized] = (category, canonical)
    for alias, exact in {
        "niche":"Niche / Indie", "indie":"Niche / Indie", "designer":"Designer / Prestige",
        "prestige":"Designer / Prestige", "mass market":"Mass Market", "middle eastern":"Middle Eastern",
    }.items():
        if exact in options["segment"]:
            lex[alias] = ("segment", exact)
    return lex


def parse_search_intent(query: str, options: dict[str, Any], fuzzy_threshold:int=84) -> list[dict[str, str]]:
    """Longest-exact-phrase first, then typo-correct unknown tokens (no unrelated brand guessing)."""
    normalized = normalize_search_query(query)
    if not normalized:
        return []
    lex = _lexicon(options)
    # Exact matches for full multi-word perfume titles shouldn't be destroyed by recognizing a component brand.
    # We still retain unrecognized tokens for free-text name matching below.
    typo_corrections: dict[str,str] = {}
    for wrong, right in KNOWN_TYPOS.items():
        if re.search(r"\b"+re.escape(wrong)+r"\b", normalized):
            typo_corrections[right] = wrong
            normalized = re.sub(r"\b"+re.escape(wrong)+r"\b", right, normalized)
    words = normalized.split()
    found: list[dict[str, str]] = []
    i = 0
    vocab_words = {k:len(k.split()) for k in lex}
    max_phrase = min(5, max(vocab_words.values(), default=1))
    while i < len(words):
        hit = None
        n = 0
        for size in range(min(max_phrase, len(words)-i), 0, -1):
            phrase = " ".join(words[i:i+size])
            if phrase in lex:
                hit, n = lex[phrase], size
                break
        if hit:
            category, canonical = hit
            corrected = typo_corrections.get(" ".join(words[i:i+n]))
            label = f"{('Ingredient' if category=='ingredient' else category.replace('_',' ').title())}: {canonical}"
            if corrected:
                label += f" · corrected '{corrected}'"
            found.append({"kind":category, "value":canonical,"label":label,
                          "source":"fuzzy" if corrected else "exact"})
            i += n
            continue
        term = words[i]
        # Only typo-correct self-contained terms; phrases with common short words remain free text.
        candidate = None
        if len(term) >= 4:
            one_words = [v for v in lex if " " not in v and len(v)>2]
            best = process.extractOne(term, one_words, scorer=fuzz.ratio, score_cutoff=fuzzy_threshold)
            if best:
                candidate = (lex[best[0]], best[0])
        if candidate:
            (category, canonical), corrected = candidate
            found.append({"kind":category, "value":canonical,
                          "label":f"{('Ingredient' if category=='ingredient' else category.title())}: {canonical} · corrected '{term}'",
                          "source":"fuzzy"})
        else:
            found.append({"kind":"free", "value":term, "label":f"Text: {term}", "source":"free"})
        i += 1
    # Repeated classified tokens should not duplicate conditions or affect counts.
    return list({(x["kind"], x["value"]): x for x in found}.values())


def fuzzy_search(query: str, options: dict[str, Any], fuzzy_threshold:int=84) -> list[dict[str, str]]:
    """Reusable spelling-aware vocabulary lookup for the search UI."""
    return [x for x in parse_search_intent(query, options, fuzzy_threshold) if x["source"] == "fuzzy"]


def default_filter_values(options: dict[str, Any]) -> dict[str, Any]:
    return {**{key:[] for key in FILTER_FIELDS}, "year":(options["year_min"], options["year_max"]),
            "min_rating":1.0, "min_votes":0, "match_mode":"ANY"}


def reset_filters() -> None:
    """Callback fires before widgets instantiate; safely reset every global filter and search term."""
    for k in list(st.session_state):
        if k.startswith(("f_", "s_")) or k in ("global_search", "search_active", "_last_search", "explorer_page", "results_page", "ingredient_selected", "more_ingredient_info"):
            del st.session_state[k]
    st.session_state.pop("filters", None)


def ensure_pending_drilldown() -> None:
    """Apply chart interactions at the start of the next rerun (before sidebar widgets render)."""
    if "pending_drilldown" in st.session_state:
        category, names = st.session_state.pop("pending_drilldown")
        # Map original Plotly selections into the simplified sidebar controls.
        if category in {"brand", "family", "group", "concentration"}:
            st.session_state["s_" + category] = names
        elif category in {"segment", "gender"} and names:
            st.session_state["s_" + category] = names[0]
        else:
            st.session_state["f_" + category] = names
        st.session_state["explorer_page"] = 1
        st.session_state["results_page"] = 1


def render_global_filters(options: dict[str, Any]) -> dict[str, Any]:
    st.sidebar.markdown("<div class='card-heading'>REFINE YOUR COLLECTION</div>", unsafe_allow_html=True)
    st.sidebar.button("↺  Clear all filters", on_click=reset_filters)
    with st.sidebar.expander("Identity & classification", expanded=True):
        st.multiselect("Market segment", options["segment"], key="f_segment", placeholder="All segments")
        st.multiselect("Brand", options["brand"], key="f_brand", placeholder="All brands")
        st.multiselect("Corporate group", options["group"], key="f_group")
        st.multiselect("Gender", options["gender"], key="f_gender")
        st.multiselect("Concentration", options["concentration"], key="f_concentration")
        st.multiselect("Fragrance family", options["family"], key="f_family")
    with st.sidebar.expander("Ingredients & composition", expanded=False):
        st.multiselect("Main accords", options["accord"], key="f_accord")
        for key, title in (("top","Top notes"),("middle","Middle notes"),("base","Base notes")):
            st.multiselect(title, options["note"], key="f_"+key)
        st.radio("Within a selected ingredient layer", ["ANY","ALL"], key="f_match_mode", horizontal=True,
                 help="ANY: one of the chosen items. ALL: every chosen item must be present; different filter types still combine with AND.")
        st.multiselect("Exclude accords", options["accord"], key="f_exclude_accord")
        st.multiselect("Exclude notes (any layer)", options["note"], key="f_exclude_note")
    with st.sidebar.expander("Year & rating thresholds", expanded=False):
        st.slider("Release years", min_value=options["year_min"], max_value=options["year_max"],
                  value=(options["year_min"],options["year_max"]), key="f_year")
        st.slider("Minimum rating", min_value=1.0,max_value=5.0,step=0.05, value=1.0,key="f_min_rating")
        st.number_input("Minimum number of votes",min_value=0,max_value=500000,step=10,value=0,key="f_min_votes")
    with st.sidebar.expander("Search settings", expanded=False):
        st.slider("Minimum fuzzy similarity",min_value=70,max_value=95,value=84,key="f_fuzzy_threshold",
                  help="Recognize likely typos only when their RapidFuzz similarity reaches this value. Exact phrases are always preferred.")
        st.caption("Arabic aliases and PostgreSQL trigram search are always enabled.")
    defaults = default_filter_values(options)
    filt = {k:st.session_state.get("f_"+k, defaults[k]) for k in defaults}
    filt["fuzzy_threshold"] = st.session_state.get("f_fuzzy_threshold",84)
    return filt


def render_dashboard_header() -> str:
    st.markdown("""<div class='hero'><span class='eyebrow'>THE FRAGRANCE DATA OBSERVATORY</span>
    <h1>Perfume Intelligence Dashboard</h1>
    <p>Explore, search, and analyze 40,000 fragrances through intelligent discovery and interactive analytics.</p></div>""", unsafe_allow_html=True)
    st.markdown("<span class='card-heading'>INTELLIGENT UNIVERSAL SEARCH</span>",unsafe_allow_html=True)
    return st.text_input("Search brands, perfumes, notes, accords, categories…", key="global_search",
                         placeholder="Try: Unisex Woody Niche EDP · Amber · ديزاينر · diorr",label_visibility="collapsed")


def render_search_interpretation(query: str, options: dict[str, Any], fuzzy_threshold:int=84) -> list[dict[str,str]]:
    all_specs = parse_search_intent(query, options, fuzzy_threshold)
    keys = [s["label"] for s in all_specs]
    # A different search query resets the selected conditions; users can deselect chips independently.
    if st.session_state.get("_last_search") != (query,fuzzy_threshold):
        st.session_state["_last_search"] = (query,fuzzy_threshold)
        st.session_state["search_active"] = keys
        st.session_state["results_page"] = 1
        st.session_state["explorer_page"] = 1
    if not all_specs:
        return []
    selected = st.multiselect("Interpreted conditions · remove unwanted terms", keys, key="search_active",
                              help="All selected conditions combine with AND. Remove a detected term to exclude it from the search.")
    active = [s for s in all_specs if s["label"] in selected]
    corrections = fuzzy_search(query, options, fuzzy_threshold)
    if corrections:
        st.caption("Spelling corrections: " + ", ".join(s["label"] for s in corrections))
    return active


@dataclass
class FilterQuery:
    cte: str
    params: dict[str, Any]
    relevance: str


def _item_exists(table: str, idtable: str, labeltable: str, field: str, condition: str) -> str:
    return (f"EXISTS (SELECT 1 FROM {table} rel JOIN {idtable} item ON item.{field}_id=rel.{field}_id "
            f"WHERE rel.perfume_id=p.perfume_id AND {condition})")


def build_filtered_query(filters: dict[str, Any]) -> FilterQuery:
    """Single authoritative filtered-ID CTE shared by KPIs, plots, tables and exports.

    All values are bound SQL parameters. SQL fragments come only from fixed internal whitelists.
    EXISTS predicates avoid multiplying perfume rows through M:N joins.
    """
    wheres: list[str] = []
    params: dict[str, Any] = {}
    equality = {"brand":"b.brand_name", "segment":"ms.segment_name", "group":"cg.group_name",
                "gender":"g.gender_name", "concentration":"c.concentration_name", "family":"ff.family_name"}
    for key, column in equality.items():
        values = filters.get(key, [])
        if values:
            params[key] = list(values)
            wheres.append(f"{column} = ANY(:{key})")
    for key, table, itemtable, field, name, condition in (
        ("accord", "perfume_accord", "accord", "accord", "accord_name", ""),
        ("top", "perfume_note", "note", "note", "note_name", "Top"),
        ("middle", "perfume_note", "note", "note", "note_name", "Middle"),
        ("base", "perfume_note", "note", "note", "note_name", "Base"),
    ):
        values = filters.get(key, [])
        if not values:
            continue
        layer_where = "" if not condition else f" AND rel.note_layer='{condition}'"
        if filters.get("match_mode","ANY") == "ALL":
            for i, value in enumerate(values):
                param_key = f"{key}_{i}"
                params[param_key] = value
                wheres.append(_item_exists(table, itemtable, "item", field,
                              f"item.{name}=:{param_key}{layer_where}"))
        else:
            params[key] = list(values)
            wheres.append(_item_exists(table, itemtable, "item", field,
                          f"item.{name}=ANY(:{key}){layer_where}"))
    if filters.get("exclude_accord"):
        params["exclude_accord"] = list(filters["exclude_accord"])
        wheres.append("NOT EXISTS (SELECT 1 FROM perfume_accord pa JOIN accord a USING(accord_id) "
                      "WHERE pa.perfume_id=p.perfume_id AND a.accord_name=ANY(:exclude_accord))")
    if filters.get("exclude_note"):
        params["exclude_note"] = list(filters["exclude_note"])
        wheres.append("NOT EXISTS (SELECT 1 FROM perfume_note pn JOIN note n USING(note_id) "
                      "WHERE pn.perfume_id=p.perfume_id AND n.note_name=ANY(:exclude_note))")
    year = filters.get("year")
    if year:
        params.update(year_min=int(year[0]),year_max=int(year[1]))
        wheres.append("p.release_year BETWEEN :year_min AND :year_max")
    params["rating_floor"] = float(filters.get("min_rating",1.0))
    params["votes_floor"] = int(filters.get("min_votes",0))
    wheres += ["p.rating_value>=:rating_floor", "p.rating_count>=:votes_floor"]

    scores: list[str] = []
    for i, spec in enumerate(filters.get("search_specs", [])):
        kind, value = spec["kind"], spec["value"]
        key = f"search_{i}"
        if kind in equality:
            params[key] = value
            wheres.append(f"{equality[kind]}=:{key}")
            scores.append("45")
        elif kind == "ingredient":
            params[key] = f"%{value.casefold()}%"
            match_accord = "EXISTS(SELECT 1 FROM perfume_accord pa JOIN accord a USING(accord_id) WHERE pa.perfume_id=p.perfume_id AND lower(a.accord_name) LIKE :"+key+")"
            match_note = "EXISTS(SELECT 1 FROM perfume_note pn JOIN note n USING(note_id) WHERE pn.perfume_id=p.perfume_id AND lower(n.note_name) LIKE :"+key+")"
            wheres.append(f"({match_accord} OR {match_note} OR lower(ff.family_name) LIKE :{key})")
            scores.append(f"(CASE WHEN {match_accord} THEN 30 ELSE 0 END + CASE WHEN {match_note} THEN 30 ELSE 0 END)")
        else:
            # Token-level free search also uses pg_trgm word_similarity for misspelled names.
            params[key] = f"%{value.casefold()}%"
            params[key+"_word"] = value
            token_expr = (f"(lower(p.name) LIKE :{key} OR lower(b.brand_name) LIKE :{key} OR cg.group_name ILIKE :{key} "
                f"OR ms.segment_name ILIKE :{key} OR g.gender_name ILIKE :{key} OR c.concentration_name ILIKE :{key} "
                f"OR lower(ff.family_name) LIKE :{key} "
                f"OR word_similarity(:{key}_word, lower(p.name)) >= 0.68 "
                f"OR EXISTS(SELECT 1 FROM perfume_accord pa JOIN accord a USING(accord_id) WHERE pa.perfume_id=p.perfume_id AND lower(a.accord_name) LIKE :{key}) "
                f"OR EXISTS(SELECT 1 FROM perfume_note pn JOIN note n USING(note_id) WHERE pn.perfume_id=p.perfume_id AND lower(n.note_name) LIKE :{key}))")
            wheres.append(token_expr)
            scores.append(f"CASE WHEN lower(p.name)=:{key}_word THEN 100 WHEN lower(p.name) LIKE :{key} THEN 35 ELSE 8 END")
    cte = ("WITH filtered AS (SELECT p.perfume_id FROM perfume p "
           "JOIN brand b ON b.brand_id=p.brand_id "
           "JOIN market_segment ms ON ms.segment_id=b.segment_id "
           "JOIN corporate_group cg ON cg.group_id=b.group_id "
           "JOIN gender g ON g.gender_id=p.gender_id "
           "JOIN concentration c ON c.concentration_id=p.concentration_id "
           "JOIN fragrance_family ff ON ff.family_id=p.family_id "
           "WHERE " + (" AND ".join(wheres) if wheres else "TRUE") + ")")
    return FilterQuery(cte, params, " + ".join(scores) if scores else "0")


def filtered_df(spec: FilterQuery, suffix: str, extra: dict[str,Any] | None = None) -> pd.DataFrame:
    return run_query(spec.cte + " " + suffix, {**spec.params, **(extra or {})})


def get_filtered_perfume_ids(filters: dict[str,Any]) -> pd.DataFrame:
    """Use only for checks/export (never fetch all IDs on every rerun)."""
    spec = build_filtered_query(filters)
    return filtered_df(spec,"SELECT perfume_id FROM filtered")


def search_perfumes(query: str, filters: dict[str,Any], page: int=1, page_size: int=25,
                    sort: str="Most relevant") -> pd.DataFrame:
    """Search a paged catalog using the same shared filter population as every KPI."""
    _ = query  # Query parsing is supplied via the centralized filters['search_specs'].
    return get_catalog_page(build_filtered_query(filters), page, page_size, sort)


def get_dashboard_kpis(filters: dict[str,Any]) -> pd.Series:
    spec = build_filtered_query(filters)
    sql = """SELECT COUNT(*) AS perfume_count, COUNT(DISTINCT p.brand_id) AS brand_count,
           COUNT(DISTINCT p.family_id) AS family_count, COUNT(DISTINCT b.segment_id) AS segment_count,
           ROUND(AVG(p.rating_value),3) AS avg_rating, COALESCE(SUM(p.rating_count),0) AS total_votes,
           (SELECT COUNT(DISTINCT pn.note_id) FROM perfume_note pn JOIN filtered f2 ON f2.perfume_id=pn.perfume_id) AS note_count,
           (SELECT COUNT(DISTINCT pa.accord_id) FROM perfume_accord pa JOIN filtered f2 ON f2.perfume_id=pa.perfume_id) AS accord_count
           FROM filtered f JOIN perfume p USING(perfume_id) JOIN brand b ON b.brand_id=p.brand_id"""
    return filtered_df(spec, sql).iloc[0]


# ────────────────────────── Reusable analytics SQL ────────────────────────
DIMENSIONS = {
    "Market segment": ("ms.segment_name","market_segment ms ON ms.segment_id=b.segment_id"),
    "Brand": ("b.brand_name", ""),
    "Corporate group": ("cg.group_name","corporate_group cg ON cg.group_id=b.group_id"),
    "Gender": ("g.gender_name","gender g ON g.gender_id=p.gender_id"),
    "Concentration": ("c.concentration_name","concentration c ON c.concentration_id=p.concentration_id"),
    "Fragrance family": ("ff.family_name","fragrance_family ff ON ff.family_id=p.family_id"),
    "Release year": ("p.release_year", ""),
}
METRICS = {
    "Perfume count":"COUNT(*)::bigint",
    "Unique brand count":"COUNT(DISTINCT p.brand_id)::bigint",
    "Average rating":"ROUND(AVG(p.rating_value),3)",
    "Vote-weighted rating":"ROUND(SUM(p.rating_value*p.rating_count)/NULLIF(SUM(p.rating_count),0),3)",
    "Total rating votes":"SUM(p.rating_count)::bigint",
}
BASE_JOIN = "FROM filtered f JOIN perfume p ON p.perfume_id=f.perfume_id JOIN brand b ON b.brand_id=p.brand_id"


def get_group_analytics(filters: dict[str,Any], dimension: str, metric: str="Perfume count",
                        top_n: int=30, descending: bool=True, min_votes: int=0) -> pd.DataFrame:
    """Whitelisted dimension/metric query; values remain bound, preventing SQL injection."""
    if dimension not in DIMENSIONS or metric not in METRICS:
        raise ValueError("Unknown analytical dimension/metric")
    column, join = DIMENSIONS[dimension]
    extra_join = " JOIN " + join if join else ""
    condition = " HAVING SUM(p.rating_count)>=:group_votes" if min_votes else ""
    direction = "DESC" if descending else "ASC"
    return filtered_df(build_filtered_query(filters),
        f"SELECT {column} AS category, {METRICS[metric]} AS value, COUNT(*)::bigint AS perfume_count, "
        f"SUM(p.rating_count)::bigint AS votes, ROUND(AVG(p.rating_value),3) AS avg_rating "
        f"{BASE_JOIN}{extra_join} GROUP BY {column}{condition} ORDER BY value {direction} NULLS LAST, category LIMIT :top_n",
        {"top_n":int(top_n),"group_votes":int(min_votes)})


def get_market_segment_analytics(filters:dict[str,Any]) -> pd.DataFrame:
    return get_group_analytics(filters,"Market segment")


def get_brand_analytics(filters:dict[str,Any], limit:int=20, min_votes:int=0) -> pd.DataFrame:
    return get_group_analytics(filters,"Brand",top_n=limit,min_votes=min_votes)


def get_accord_analytics(filters:dict[str,Any], top_n:int=20) -> pd.DataFrame:
    spec = build_filtered_query(filters)
    return filtered_df(spec,"""SELECT a.accord_name AS category,COUNT(DISTINCT pa.perfume_id)::bigint AS perfume_count
        FROM filtered f JOIN perfume_accord pa ON f.perfume_id=pa.perfume_id
        JOIN accord a ON a.accord_id=pa.accord_id GROUP BY a.accord_id,a.accord_name
        ORDER BY perfume_count DESC,category LIMIT :top_n""",{"top_n":int(top_n)})


def get_note_analytics(filters:dict[str,Any], layer:str="Top", top_n:int=20) -> pd.DataFrame:
    if layer not in ("Top","Middle","Base"):
        raise ValueError("Unknown note layer")
    spec = build_filtered_query(filters)
    return filtered_df(spec,"""SELECT n.note_name AS category,COUNT(DISTINCT pn.perfume_id)::bigint AS perfume_count
        FROM filtered f JOIN perfume_note pn ON f.perfume_id=pn.perfume_id
        JOIN note n ON n.note_id=pn.note_id WHERE pn.note_layer=:layer
        GROUP BY n.note_id,n.note_name ORDER BY perfume_count DESC,category LIMIT :top_n""",
        {"layer":layer,"top_n":int(top_n)})


def get_rating_analytics(filters:dict[str,Any], minimum_votes:int=0) -> pd.DataFrame:
    """Perfume-level data suitable for histogram/scatter; only fetched on the Ratings tab."""
    spec = build_filtered_query(filters)
    return filtered_df(spec,"""SELECT p.perfume_id,p.name,b.brand_name,ms.segment_name,p.release_year,
        p.rating_value::float AS rating_value,p.rating_count
        FROM filtered f JOIN perfume p USING(perfume_id) JOIN brand b ON b.brand_id=p.brand_id
        JOIN market_segment ms ON ms.segment_id=b.segment_id WHERE p.rating_count>=:min_plot_votes""",
        {"min_plot_votes":int(minimum_votes)})


def _matching_label_sql(spec: FilterQuery, filters:dict[str,Any]) -> tuple[str,dict[str,Any]]:
    ingredients = [s["value"] for s in filters.get("search_specs",[]) if s["kind"]=="ingredient"]
    if not ingredients:
        return "''::text AS matched_in", {}
    strings = []
    params = {}
    for i, ing in enumerate(ingredients):
        k = f"match_label_{i}"
        params[k] = f"%{ing.casefold()}%"
        cases = []
        for layer in ("Top","Middle","Base"):
            cases.append(f"CASE WHEN EXISTS(SELECT 1 FROM perfume_note pn JOIN note n USING(note_id) "
                         f"WHERE pn.perfume_id=page.perfume_id AND pn.note_layer='{layer}' AND lower(n.note_name) LIKE :{k}) "
                         f"THEN '{layer} Notes' END")
        cases.append(f"CASE WHEN EXISTS(SELECT 1 FROM perfume_accord pa JOIN accord a USING(accord_id) "
                     f"WHERE pa.perfume_id=page.perfume_id AND lower(a.accord_name) LIKE :{k}) THEN 'Main Accords' END")
        cases.append(f"CASE WHEN lower(page.fragrance_family) LIKE :{k} THEN 'Fragrance Family' END")
        params[k+"_title"] = ing
        strings.append(f"CONCAT(CAST(:{k}_title AS TEXT), ': ', CONCAT_WS(' · ', {', '.join(cases)}))")
    return "CONCAT_WS('; ', " + ", ".join(strings) + ") AS matched_in", params


def get_catalog_page(spec:FilterQuery, page:int=1, page_size:int=25,
                     sort:str="Most relevant", filters:dict[str,Any]|None=None) -> pd.DataFrame:
    """Server-side LIMIT/OFFSET; aggregate notes/accords only for the current page."""
    order = SORT_COLUMNS.get(sort,SORT_COLUMNS["Most relevant"])
    window_order = order.replace("relevance DESC", f"({spec.relevance}) DESC")
    label_expr, label_params = _matching_label_sql(spec, filters or {})
    extra = {"limit":int(page_size),"offset":(int(page)-1)*int(page_size),**label_params}
    sql = f"""{spec.cte}, page AS (
      SELECT p.perfume_id,p.name,b.brand_name,ms.segment_name AS market_segment,
        cg.group_name AS corporate_group,g.gender_name AS gender,c.concentration_name AS concentration,
        ff.family_name AS fragrance_family,p.release_year,p.rating_value::float AS rating,
        p.rating_count,p.url, ({spec.relevance}) AS relevance,
        ROW_NUMBER() OVER (ORDER BY {window_order}) AS display_order
      FROM filtered f JOIN perfume p ON p.perfume_id=f.perfume_id
      JOIN brand b ON b.brand_id=p.brand_id JOIN market_segment ms ON ms.segment_id=b.segment_id
      JOIN corporate_group cg ON cg.group_id=b.group_id JOIN gender g ON g.gender_id=p.gender_id
      JOIN concentration c ON c.concentration_id=p.concentration_id
      JOIN fragrance_family ff ON ff.family_id=p.family_id
      ORDER BY {order} LIMIT :limit OFFSET :offset
    )
    SELECT page.perfume_id,page.name,page.brand_name,page.market_segment,page.corporate_group,
      page.gender,page.concentration,page.release_year,page.rating,page.rating_count,
      page.fragrance_family,
      (SELECT string_agg(a.accord_name,'; ' ORDER BY pa.accord_rank)
       FROM perfume_accord pa JOIN accord a USING(accord_id) WHERE pa.perfume_id=page.perfume_id) AS main_accords,
      (SELECT string_agg(n.note_name,'; ' ORDER BY n.note_name)
       FROM perfume_note pn JOIN note n USING(note_id)
       WHERE pn.perfume_id=page.perfume_id AND pn.note_layer='Top') AS top_notes,
      (SELECT string_agg(n.note_name,'; ' ORDER BY n.note_name)
       FROM perfume_note pn JOIN note n USING(note_id)
       WHERE pn.perfume_id=page.perfume_id AND pn.note_layer='Middle') AS middle_notes,
      (SELECT string_agg(n.note_name,'; ' ORDER BY n.note_name)
       FROM perfume_note pn JOIN note n USING(note_id)
       WHERE pn.perfume_id=page.perfume_id AND pn.note_layer='Base') AS base_notes,
      {label_expr},page.url
    FROM page ORDER BY page.display_order"""
    return run_query(sql,{**spec.params,**extra})


def get_catalog_count(spec:FilterQuery) -> int:
    return int(filtered_df(spec,"SELECT COUNT(*) AS n FROM filtered").iloc[0]["n"])

# ─────────────────────────── Charts & interactions ────────────────────────
def polish(fig:go.Figure, height:int=390, legend:bool=False) -> go.Figure:
    """Shared typography, margin, colors, and SVG/image-export Plotly controls."""
    fig.update_layout(template="plotly_white",font=dict(family="DM Sans, Arial",size=12,color=INK),
                      margin=dict(l=16,r=20,t=42,b=26),height=height,paper_bgcolor="#FFFFFF",
                      plot_bgcolor="#FFFFFF",colorway=PALETTE,showlegend=legend,
                      hoverlabel=dict(bgcolor="#FFFFFF",font_size=12))
    fig.update_xaxes(showgrid=True,gridcolor="#F0EDE6",zeroline=False)
    fig.update_yaxes(showgrid=False,zeroline=False)
    return fig


def show_plot(fig:go.Figure, key:str|None=None, selectable:bool=False):
    return st.plotly_chart(fig, width="stretch", key=key,
         on_select="rerun" if selectable else "ignore",
         selection_mode=("points", "box") if selectable else ("points",),
         config={"displayModeBar":True,"toImageButtonOptions":{"format":"png","scale":2}})


def queue_drilldown(field:str, names:list[str]) -> None:
    st.session_state["pending_drilldown"] = (field,names)


def bar_chart(df:pd.DataFrame, category:str, value:str, title:str, key:str,
              drill_field:str|None=None, max_height:int=530) -> None:
    if df.empty:
        st.info("No matching records for this chart. Try adjusting your search or filters.")
        return
    d = df.copy()
    d[value] = pd.to_numeric(d[value],errors="coerce")
    d[category] = d[category].astype(str)
    d = d.sort_values(value,ascending=True)
    fig = px.bar(d,x=value,y=category,orientation="h",color_discrete_sequence=[GOLD],
                 hover_data={value:':,.0f',category:True})
    fig.update_traces(marker_line_width=0,hovertemplate="%{y}<br><b>%{x:,.0f}</b><extra></extra>")
    fig.update_layout(title=dict(text=title,font=dict(size=16)),
                      yaxis=dict(categoryorder="array",categoryarray=d[category].tolist()),
                      xaxis_title=None,yaxis_title=None)
    event = show_plot(polish(fig,height=min(max_height,max(290,80+len(d)*26))),key,drill_field is not None)
    if drill_field and event is not None:
        pts = event.selection.points
        categories = sorted({str(pt.get("y")) for pt in pts if pt.get("y") is not None})
        if categories:
            st.button(f"Apply {len(categories)} selected {drill_field} value(s) as global filter",
                      key=f"apply_{key}",on_click=queue_drilldown,args=(drill_field,categories))


def donut_chart(df:pd.DataFrame, category:str, value:str, title:str, key:str) -> None:
    if df.empty:
        st.info("No results for this visualization.")
        return
    fig = px.pie(df,names=category,values=value,hole=.62,color_discrete_sequence=PALETTE)
    fig.update_traces(textposition="inside",textinfo="percent",hovertemplate="%{label}: %{value:,} (%{percent})<extra></extra>")
    fig.update_layout(title=dict(text=title,font=dict(size=16)),legend=dict(orientation="h",y=-.11))
    show_plot(polish(fig,385,True),key)


def explain_population(filters:dict[str,Any]) -> None:
    active = sum(len(filters.get(k,[])) for k in FILTER_FIELDS)
    active += len(filters.get("search_specs",[]))
    if active:
        st.caption(f"Live PostgreSQL analysis · {active} active search/filter terms · all chart counts use the matching population.")
    else:
        st.caption("Live PostgreSQL analysis · full imported dataset · counts describe catalog coverage, not sales or market share.")


def render_kpi_cards(filters:dict[str,Any]) -> None:
    k = get_dashboard_kpis(filters)
    items = [
        ("Matching perfumes",k.perfume_count,"🧴"),("Unique brands",k.brand_count,"✦"),
        ("Unique notes",k.note_count,"◈"),("Unique accords",k.accord_count,"◇"),
        ("Average rating",float(k.avg_rating) if pd.notna(k.avg_rating) else np.nan,"★"),
        ("Total rating votes",k.total_votes,"▤"),
        ("Fragrance families",k.family_count,"♧"),("Market segments",k.segment_count,"▥"),
    ]
    st.markdown("<div class='card-heading'>LIVE PORTFOLIO PULSE</div>",unsafe_allow_html=True)
    for row_items in (items[:4],items[4:]):
        cols=st.columns(4)
        for col,(label,val,_icon) in zip(cols,row_items):
            with col:
                if label=="Average rating":
                    st.metric(label,f"{float(val):.2f} / 5" if pd.notna(val) else "—")
                else:
                    st.metric(label,f"{int(val):,}")
    explain_population(filters)
    if not int(k.perfume_count):
        st.warning("No perfumes match the current search and filters. Remove a search condition or clear filters.")


def render_result_table(filters:dict[str,Any], prefix:str, show_header:bool=True) -> None:
    """Backend pagination, sortable query, rows selection, details and selected-record export."""
    spec=build_filtered_query(filters)
    total=get_catalog_count(spec)
    if show_header:
        st.subheader("Perfume catalog")
    st.caption(f"{total:,} matching perfumes · database-backed pages · select rows to export or inspect")
    if total==0:
        st.info("Nothing matches these conditions. Check the interpreted query, lower the rating threshold, or clear filters.")
        return
    controls=st.columns([2.0,1,1])
    with controls[0]:
        sort=st.selectbox("Sort records",list(SORT_COLUMNS.keys()),key=prefix+"_sort")
    with controls[1]:
        page_size=st.selectbox("Rows per page",[10,25,50,100],index=1,key=prefix+"_size")
    max_page=max(1,math.ceil(total/page_size))
    page_key=prefix+"_page"
    if st.session_state.get(page_key,1)>max_page:
        st.session_state[page_key]=1
    with controls[2]:
        page=int(st.number_input("Page",min_value=1,max_value=max_page,value=1,step=1,key=page_key))
    page_df=get_catalog_page(spec,page,page_size,sort,filters)
    if page_df.empty:
        st.info("This page is empty. Choose an earlier page.")
        return
    shown=page_df.drop(columns=["corporate_group","matched_in"] if not filters.get("search_specs")
                           else ["corporate_group"])
    event=st.dataframe(shown,hide_index=True,width="stretch",height=min(610,75+len(shown)*36),
        key=prefix+"_selected",on_select="rerun",selection_mode="multi-row",
        column_config={"url":st.column_config.LinkColumn("Source URL",display_text="Open source"),
                       "rating":st.column_config.NumberColumn("Rating",format="%.2f"),
                       "rating_count":st.column_config.NumberColumn("Votes",format="%d")})
    chosen=[i for i in event.selection.rows if 0<=i<len(page_df)]
    selected_df=page_df.iloc[chosen]
    c1,c2=st.columns([2,2])
    with c1:
        st.download_button("↓ Export current page (CSV)",data=page_df.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"perfumes_{prefix}_page_{page}.csv",mime="text/csv",key=prefix+"_page_export")
    with c2:
        st.download_button(f"↓ Export selected ({len(selected_df)})",data=selected_df.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"perfumes_{prefix}_selected.csv",mime="text/csv",
                           disabled=selected_df.empty,key=prefix+"_selected_export")
    ids=selected_df.perfume_id.astype(int).tolist() if len(selected_df) else page_df.perfume_id.astype(int).tolist()
    with st.expander("Inspect a perfume record",expanded=bool(chosen)):
        id_=st.selectbox("Perfume ID",ids,format_func=lambda pid: f"#{pid} — {page_df.loc[page_df.perfume_id==pid,'name'].iloc[0]}",
                         key=prefix+"_details")
        record=page_df.loc[page_df.perfume_id==id_].iloc[0]
        st.markdown(f"**{record['name']}** · {record['brand_name']} · {record['market_segment']}")
        cols=st.columns(4)
        for col,label,val in zip(cols,["Release year","Rating","Votes","Concentration"],
                                 [record.release_year,record.rating,record.rating_count,record.concentration]):
            col.metric(label,str(val))
        st.write({"Fragrance family":record.fragrance_family,"Gender":record.gender,"Corporate group":record.corporate_group,
                  "Main accords":record.main_accords,"Top notes":record.top_notes,"Middle notes":record.middle_notes,
                  "Base notes":record.base_notes,"Matched in":record.matched_in})
        if isinstance(record.url,str) and re.match(r"^https?://",record.url):
            st.link_button("View original record",record.url)


def render_search_section(filters:dict[str,Any]) -> None:
    st.markdown("## Advanced search & results")
    st.markdown("<div class='section-note'>Queries across perfume names, manufacturers, categories, all accord/notes layers, and Arabic aliases. Matching terms combine with AND; ingredient matches combine note and accord locations with OR.</div>",unsafe_allow_html=True)
    render_result_table(filters,"results",show_header=False)


def get_release_breakdown(filters:dict[str,Any], granularity:str="Year") -> pd.DataFrame:
    col="p.release_year" if granularity=="Year" else "(p.release_year/10)*10"
    return filtered_df(build_filtered_query(filters),
        f"SELECT {col} AS period,COUNT(*)::bigint AS perfume_count,ROUND(AVG(p.rating_value),3) AS avg_rating, "
        f"SUM(p.rating_count)::bigint AS votes {BASE_JOIN} GROUP BY {col} ORDER BY period")


def get_family_segment_heatmap(filters:dict[str,Any]) -> pd.DataFrame:
    return filtered_df(build_filtered_query(filters),"""
        SELECT ff.family_name,ms.segment_name,COUNT(*)::bigint AS perfume_count FROM filtered f
        JOIN perfume p USING(perfume_id) JOIN brand b ON b.brand_id=p.brand_id
        JOIN fragrance_family ff ON ff.family_id=p.family_id
        JOIN market_segment ms ON ms.segment_id=b.segment_id
        GROUP BY ff.family_name,ms.segment_name ORDER BY perfume_count DESC""")


def get_brand_segment_data(filters:dict[str,Any]) -> pd.DataFrame:
    return filtered_df(build_filtered_query(filters),"""
        SELECT ms.segment_name,b.brand_name,COUNT(*)::bigint AS perfume_count
        FROM filtered f JOIN perfume p USING(perfume_id) JOIN brand b ON b.brand_id=p.brand_id
        JOIN market_segment ms ON ms.segment_id=b.segment_id
        GROUP BY ms.segment_name,b.brand_name ORDER BY perfume_count DESC LIMIT 300""")


def get_cooccurrence(filters:dict[str,Any], kind:str="Note", n:int=20) -> pd.DataFrame:
    """Count DISTINCT perfume IDs per pair. Same note across different layers counts once."""
    spec=build_filtered_query(filters)
    if kind=="Note":
        relation="perfume_note"; dim="note"; idcol="note_id"; namecol="note_name"
    elif kind=="Accord":
        relation="perfume_accord"; dim="accord"; idcol="accord_id"; namecol="accord_name"
    else:
        raise ValueError("Unsupported co-occurrence kind")
    return filtered_df(spec,f"""WITH eligible AS (
        SELECT DISTINCT rel.perfume_id, rel.{idcol} AS entity_id
        FROM filtered f JOIN {relation} rel ON rel.perfume_id=f.perfume_id
    ), pairs AS (
        SELECT l.entity_id AS id1,r.entity_id AS id2,COUNT(*)::bigint AS perfume_count
        FROM eligible l JOIN eligible r ON l.perfume_id=r.perfume_id AND l.entity_id<r.entity_id
        GROUP BY l.entity_id,r.entity_id ORDER BY perfume_count DESC LIMIT :n
    ) SELECT a.{namecol} AS item_a,b.{namecol} AS item_b,pairs.perfume_count
       FROM pairs JOIN {dim} a ON a.{idcol}=pairs.id1 JOIN {dim} b ON b.{idcol}=pairs.id2
       ORDER BY perfume_count DESC""",{"n":int(n)})


def render_overview_section(filters:dict[str,Any]) -> None:
    st.markdown("## Portfolio overview")
    a,b=st.columns([1.05,1])
    with a:
        segments=get_group_analytics(filters,"Market segment")
        donut_chart(segments,"category","value","Market-segment distribution","overview_segments")
    with b:
        brands=get_brand_analytics(filters,12)
        bar_chart(brands,"category","value","Largest brand catalogs","overview_brands","brand")
    x,y=st.columns(2)
    with x:
        families=get_group_analytics(filters,"Fragrance family",top_n=12)
        bar_chart(families,"category","value","Leading fragrance families","overview_families","family")
    with y:
        accords=get_accord_analytics(filters,12)
        bar_chart(accords,"category","perfume_count","Most frequent accords","overview_accords","accord")
    render_insights_panel(filters)


def render_analytics_section(filters:dict[str,Any]) -> None:
    st.markdown("## Interactive analytics")
    tabs=st.tabs(["Market & ownership", "Ratings & release history", "Ingredients & families", "Cross-dimensional"],
                 on_change="rerun",key="analytics_tabs")
    if tabs[0].open:
        with tabs[0]:
            a,b=st.columns(2)
            with a:
                segment=get_group_analytics(filters,"Market segment")
                bar_chart(segment,"category","value","Perfumes by market segment","analytic_segment","segment")
                gender=get_group_analytics(filters,"Gender")
                donut_chart(gender,"category","value","Gender categories","analytic_gender")
                group=get_group_analytics(filters,"Corporate group",top_n=16)
                bar_chart(group,"category","value","Corporate-group representation","analytic_corporate","group")
            with b:
                brands=get_brand_analytics(filters,15)
                bar_chart(brands,"category","value","Brands by catalog size","analytic_brands","brand")
                conc=get_group_analytics(filters,"Concentration")
                donut_chart(conc,"category","value","Concentration distribution","analytic_concentration")
                st.markdown("#### Brand ratings with vote floor")
                threshold=st.number_input("Minimum combined brand votes",min_value=0,value=100,step=100,key="analytic_brand_votes")
                rated=get_group_analytics(filters,"Brand","Average rating",15,min_votes=int(threshold))
                bar_chart(rated,"category","value","Top brands by average rating","analytic_brandrating")
                st.caption("Vote floor uses the sum of rating counts across each brand's filtered perfumes.")
    if tabs[1].open:
        with tabs[1]:
            a,b=st.columns(2)
            with a:
                per_year=get_release_breakdown(filters,"Year")
                if not per_year.empty:
                    fig=px.area(per_year,x="period",y="perfume_count",color_discrete_sequence=["#314C49"],
                                title="Release-year distribution")
                    show_plot(polish(fig),"year_area")
                dec=get_release_breakdown(filters,"Decade")
                if not dec.empty:
                    fig=px.bar(dec,x="period",y="perfume_count",color_discrete_sequence=[GOLD],title="Perfumes by release decade")
                    show_plot(polish(fig),"release_decades")
            with b:
                votes=st.number_input("Minimum votes for rating plots",min_value=0,max_value=500000,value=100,step=50,key="rating_plot_floor")
                ratings=get_rating_analytics(filters,int(votes))
                if not ratings.empty:
                    fig=px.histogram(ratings,x="rating_value",nbins=35, color_discrete_sequence=[GOLD],
                                     title="Rating distribution · eligible perfumes")
                    show_plot(polish(fig),"rating_hist")
                    st.caption(f"{len(ratings):,} perfumes · mean {ratings.rating_value.mean():.2f} · standard deviation {ratings.rating_value.std(ddof=1):.2f}")
                    sample=ratings.sort_values("rating_count",ascending=False).head(3000).copy()
                    fig=px.scatter(sample,x="rating_count",y="rating_value",color="segment_name",log_x=True,
                                   hover_name="name",hover_data=["brand_name","release_year"],
                                   opacity=.68,color_discrete_sequence=PALETTE,
                                   title="Rating versus rating-count · top 3,000 by votes")
                    show_plot(polish(fig,445,True),"rating_scatter")
                    st.caption("Scatter uses up to 3,000 highest-vote filtered records for rendering speed; averages and histograms use all eligible records.")
                else:
                    st.info("No perfumes meet the rating-count threshold.")
            trend_granularity=st.radio("Rating trend time grouping",["Year","Decade"],horizontal=True,key="rating_trend_group")
            trend=get_release_breakdown(filters,trend_granularity)
            if not trend.empty:
                fig=px.line(trend,x="period",y="avg_rating",markers=True,
                            title=f"Average rating by perfume release {trend_granularity.lower()}",
                            color_discrete_sequence=["#314C49"])
                show_plot(polish(fig),"rating_trends_time")
                st.caption("Ratings of perfumes *released in each period*, not historical ratings recorded during that period.")
    if tabs[2].open:
        with tabs[2]:
            a,b=st.columns(2)
            with a:
                family=get_group_analytics(filters,"Fragrance family",top_n=20)
                bar_chart(family,"category","value","Top fragrance families","analytic_families","family")
            with b:
                n=st.slider("Top N accords",5,30,15,key="analytic_accord_n")
                accords=get_accord_analytics(filters,n)
                bar_chart(accords,"category","perfume_count","Frequent main accords","analytic_accords","accord")
            layer=st.radio("Note layer",["Top","Middle","Base"],horizontal=True,key="analytic_layer")
            n=st.slider("Top N notes",5,40,20,key="analytic_note_n")
            notes=get_note_analytics(filters,layer,n)
            bar_chart(notes,"category","perfume_count",f"Most frequent {layer.lower()} notes","analytic_notes")
            st.markdown("#### Ingredient co-occurrence")
            kind=st.radio("Relationship type",["Note","Accord"],horizontal=True,key="analytic_pair_kind")
            if st.button("Calculate common ingredient pairs",key="compute_cooccurrence"):
                st.session_state["cooc_ready"]=(kind,json.dumps(filters,sort_keys=True,default=str))
            if st.session_state.get("cooc_ready")== (kind,json.dumps(filters,sort_keys=True,default=str)):
                pairs=get_cooccurrence(filters,kind)
                if not pairs.empty:
                    pairs["pair"]=pairs.item_a+" + "+pairs.item_b
                    bar_chart(pairs,"pair","perfume_count",f"Common {kind.lower()} pairs","cooccurrence_chart")
                    st.dataframe(pairs[["item_a","item_b","perfume_count"]],hide_index=True,width="stretch")
    if tabs[3].open:
        with tabs[3]:
            hm=get_family_segment_heatmap(filters)
            if not hm.empty:
                matrix=hm.pivot(index="family_name",columns="segment_name",values="perfume_count").fillna(0)
                fig=px.imshow(matrix,labels=dict(x="Market segment",y="Fragrance family",color="Perfumes"),
                    color_continuous_scale=[[0,"#FFFDF7"],[.45,"#C7B28E"],[1,"#314C49"]],aspect="auto",
                    title="Fragrance family × market segment")
                show_plot(polish(fig,height=750),"family_segment_heatmap")
            st.markdown("#### Brand × segment catalog size")
            brand_seg=get_brand_segment_data(filters)
            if not brand_seg.empty:
                leading=brand_seg.groupby("brand_name").perfume_count.sum().nlargest(20).index
                top=brand_seg[brand_seg.brand_name.isin(leading)]
                fig=px.bar(top,x="brand_name",y="perfume_count",color="segment_name",barmode="stack",
                           color_discrete_sequence=PALETTE,title="Top 20 brands — stacked by segment")
                fig.update_layout(xaxis_tickangle=-40)
                show_plot(polish(fig,500,True),"brand_segment_compare")
            st.caption("Values represent the distribution within the filtered data, not brand sales or real-world market share.")


def render_insights_panel(filters:dict[str,Any]) -> None:
    st.markdown("### Automatically generated data insights")
    k=get_dashboard_kpis(filters)
    if int(k.perfume_count)==0:
        st.info("Insights appear when matching perfume data exists.")
        return
    seg=get_market_segment_analytics(filters)
    fam=get_group_analytics(filters,"Fragrance family",top_n=1)
    brand=get_brand_analytics(filters,1)
    accord=get_accord_analytics(filters,1)
    gen=get_group_analytics(filters,"Gender")
    decade=get_release_breakdown(filters,"Decade")
    spec=build_filtered_query(filters)
    best=filtered_df(spec,f"""SELECT p.name,b.brand_name,p.rating_value,p.rating_count FROM filtered f
        JOIN perfume p USING(perfume_id) JOIN brand b ON b.brand_id=p.brand_id
        WHERE p.rating_count>=:min_best_votes ORDER BY p.rating_value DESC,p.rating_count DESC,p.perfume_id LIMIT 1""",
        {"min_best_votes":100})
    lines=[]
    if len(fam):
        r=fam.iloc[0];lines.append(f"**Leading family:** {r.category} appears in {int(r.value):,} perfumes ({100*int(r.value)/int(k.perfume_count):.1f}%).")
    if len(accord):
        r=accord.iloc[0];lines.append(f"**Most common accord:** {r.category} occurs in {int(r.perfume_count):,} perfumes.")
    if len(brand):
        r=brand.iloc[0];lines.append(f"**Largest brand catalog:** {r.category} has {int(r.value):,} matching perfumes.")
    if len(seg):
        r=seg.iloc[0];lines.append(f"**Largest segment:** {r.category} contains {int(r.value):,} perfumes ({100*int(r.value)/int(k.perfume_count):.1f}%).")
    unisex=gen.loc[gen.category=="Unisex"]
    if len(unisex):
        r=unisex.iloc[0];lines.append(f"**Unisex mix:** {int(r.value):,} perfumes ({100*int(r.value)/int(k.perfume_count):.1f}%).")
    if len(decade):
        r=decade.loc[decade.perfume_count.idxmax()]; lines.append(f"**Top release decade:** {int(r.period)}s with {int(r.perfume_count):,} releases.")
    if len(best):
        r=best.iloc[0]; lines.append(f"**Highest-rated (≥100 votes):** {r['name']} by {r.brand_name}, {float(r.rating_value):.2f}/5 from {int(r.rating_count):,} votes.")
    st.markdown("\n\n".join("- "+v for v in lines))

# ───────────────────────────── Ingredient intelligence ─────────────────────
def ingredient_condition(param:str="ingredient_like") -> str:
    """One perfume-level ingredient match; many-to-many tables stay behind EXISTS clauses."""
    return f"""(EXISTS(SELECT 1 FROM perfume_note pn JOIN note n USING(note_id)
                     WHERE pn.perfume_id=p.perfume_id AND lower(n.note_name) LIKE :{param})
         OR EXISTS(SELECT 1 FROM perfume_accord pa JOIN accord a USING(accord_id)
                    WHERE pa.perfume_id=p.perfume_id AND lower(a.accord_name) LIKE :{param})
         OR lower(ff.family_name) LIKE :{param})"""


def get_ingredient_population(filters:dict[str,Any], ingredient:str) -> tuple[FilterQuery,dict[str,Any]]:
    spec=build_filtered_query(filters)
    params={**spec.params,"ingredient_like":f"%{ingredient.casefold()}%"}
    # The anchor CTE contains ONLY currently filtered perfumes. No external population leakage.
    query=spec.cte+", matched AS (SELECT p.perfume_id FROM filtered f JOIN perfume p USING(perfume_id) " \
          "JOIN fragrance_family ff ON ff.family_id=p.family_id WHERE "+ingredient_condition()+")"
    return FilterQuery(query, params, "0"),params


def get_ingredient_analytics(filters:dict[str,Any], ingredient:str) -> dict[str,pd.DataFrame]:
    spec,params=get_ingredient_population(filters,ingredient)
    def fetch(suffix:str): return run_query(spec.cte+" "+suffix,params)
    out={"count":fetch("SELECT COUNT(*) AS perfume_count FROM matched")}
    out["locations"]=fetch("""SELECT location,perfume_count FROM (
       SELECT 'Top Notes' AS location, COUNT(DISTINCT pn.perfume_id)::bigint AS perfume_count
       FROM matched m JOIN perfume_note pn USING(perfume_id) JOIN note n USING(note_id)
       WHERE pn.note_layer='Top' AND lower(n.note_name) LIKE :ingredient_like
       UNION ALL SELECT 'Middle Notes',COUNT(DISTINCT pn.perfume_id)::bigint
       FROM matched m JOIN perfume_note pn USING(perfume_id) JOIN note n USING(note_id)
       WHERE pn.note_layer='Middle' AND lower(n.note_name) LIKE :ingredient_like
       UNION ALL SELECT 'Base Notes',COUNT(DISTINCT pn.perfume_id)::bigint
       FROM matched m JOIN perfume_note pn USING(perfume_id) JOIN note n USING(note_id)
       WHERE pn.note_layer='Base' AND lower(n.note_name) LIKE :ingredient_like
       UNION ALL SELECT 'Main Accords',COUNT(DISTINCT pa.perfume_id)::bigint
       FROM matched m JOIN perfume_accord pa USING(perfume_id) JOIN accord a USING(accord_id)
       WHERE lower(a.accord_name) LIKE :ingredient_like
       UNION ALL SELECT 'Fragrance Family',COUNT(*)::bigint
       FROM matched m JOIN perfume p USING(perfume_id) JOIN fragrance_family ff ON ff.family_id=p.family_id
       WHERE lower(ff.family_name) LIKE :ingredient_like
       ) parts ORDER BY CASE location WHEN 'Top Notes' THEN 1 WHEN 'Middle Notes' THEN 2
                    WHEN 'Base Notes' THEN 3 WHEN 'Main Accords' THEN 4 ELSE 5 END""")
    out["families"]=fetch("""SELECT ff.family_name AS category,COUNT(*)::bigint AS perfume_count
        FROM matched m JOIN perfume p USING(perfume_id) JOIN fragrance_family ff USING(family_id)
        GROUP BY ff.family_name ORDER BY perfume_count DESC LIMIT 15""")
    out["brands"]=fetch("""SELECT b.brand_name AS category,COUNT(*)::bigint AS perfume_count
        FROM matched m JOIN perfume p USING(perfume_id) JOIN brand b USING(brand_id)
        GROUP BY b.brand_name ORDER BY perfume_count DESC LIMIT 15""")
    out["segments"]=fetch("""SELECT ms.segment_name AS category,COUNT(*)::bigint AS perfume_count
        FROM matched m JOIN perfume p USING(perfume_id) JOIN brand b USING(brand_id)
        JOIN market_segment ms USING(segment_id) GROUP BY ms.segment_name ORDER BY perfume_count DESC""")
    out["associated_notes"]=fetch("""SELECT n.note_name AS category,COUNT(DISTINCT pn.perfume_id)::bigint AS perfume_count
        FROM matched m JOIN perfume_note pn USING(perfume_id) JOIN note n USING(note_id)
        WHERE lower(n.note_name) NOT LIKE :ingredient_like GROUP BY n.note_name
        ORDER BY perfume_count DESC LIMIT 20""")
    out["associated_accords"]=fetch("""SELECT a.accord_name AS category,COUNT(DISTINCT pa.perfume_id)::bigint AS perfume_count
        FROM matched m JOIN perfume_accord pa USING(perfume_id) JOIN accord a USING(accord_id)
        WHERE lower(a.accord_name) NOT LIKE :ingredient_like GROUP BY a.accord_name
        ORDER BY perfume_count DESC LIMIT 15""")
    return out


def render_ingredient_section(filters:dict[str,Any],options:dict[str,Any]) -> None:
    st.markdown("## Ingredient intelligence")
    st.caption("An ingredient match is a perfume containing a matching note, main accord, or fragrance-family term. Each location is counted separately.")
    ingredients=sorted(set(options["note"])|set(options["accord"]), key=str.casefold)
    default=next((i for i,v in enumerate(ingredients) if v.casefold()=="amber"),0)
    ingredient=st.selectbox("Analyze ingredient",ingredients,index=default,key="ingredient_selected")
    if not ingredient:
        return
    a=get_ingredient_analytics(filters,ingredient)
    n=int(a["count"].iloc[0].perfume_count)
    total=get_catalog_count(build_filtered_query(filters))
    x,y,z=st.columns(3)
    x.metric("Matching perfumes",f"{n:,}")
    y.metric("Share of filtered catalog",f"{100*n/total:.2f}%" if total else "—")
    z.metric("Catalog being analyzed",f"{total:,}")
    if n==0:
        st.warning("This ingredient has no matches within the current global filter context.")
        return
    # Location counts overlap: a perfume may include the same ingredient in several layers.
    st.info("Location counts can overlap: one perfume may appear in more than one ingredient location.")
    l,r=st.columns(2)
    with l:
        bar_chart(a["locations"],"location","perfume_count","Ingredient locations","ingredient_location")
        bar_chart(a["brands"],"category","perfume_count","Brands with ingredient","ingredient_brands","brand")
        bar_chart(a["associated_notes"],"category","perfume_count","Frequently accompanying notes","ingredient_assoc_notes")
    with r:
        donut_chart(a["segments"],"category","perfume_count","Market segments","ingredient_segments")
        bar_chart(a["families"],"category","perfume_count","Associated fragrance families","ingredient_families","family")
        bar_chart(a["associated_accords"],"category","perfume_count","Frequently accompanying accords","ingredient_assoc_accords")
    st.subheader("Perfumes containing this ingredient")
    scoped={**filters, "search_specs":[*filters.get("search_specs",[]),
                      {"kind":"ingredient","value":ingredient,"label":f"Ingredient: {ingredient}","source":"exact"}]}
    render_result_table(scoped,"ingredient_results",show_header=False)


# ───────────────────────────────── Brand intelligence ─────────────────────
def get_brand_comparison(filters:dict[str,Any],brands:list[str]) -> dict[str,pd.DataFrame]:
    spec=build_filtered_query(filters)
    params={**spec.params,"compare_brands":brands}
    scope=spec.cte+", chosen AS (SELECT p.perfume_id,p.brand_id,p.gender_id,p.concentration_id,p.family_id,p.release_year, " \
        "p.rating_value,p.rating_count,b.brand_name FROM filtered f JOIN perfume p USING(perfume_id) " \
        "JOIN brand b USING(brand_id) WHERE b.brand_name=ANY(:compare_brands))"
    def fetch(query):return run_query(scope+" "+query,params)
    out={}
    out["summary"]=fetch("""SELECT brand_name,COUNT(*)::bigint AS perfume_count,
        ROUND(AVG(rating_value),3) AS average_rating,
        ROUND(SUM(rating_value*rating_count)/NULLIF(SUM(rating_count),0),3) AS weighted_rating,
        SUM(rating_count)::bigint AS total_votes
        FROM chosen GROUP BY brand_name ORDER BY perfume_count DESC""")
    for name,col,join in (
        ("family","family_name","fragrance_family f ON f.family_id=x.family_id"),
        ("gender","gender_name","gender f ON f.gender_id=x.gender_id"),
        ("concentration","concentration_name","concentration f ON f.concentration_id=x.concentration_id"),
    ):
        out[name]=fetch(f"""SELECT x.brand_name,f.{col} AS category,COUNT(*)::bigint AS perfume_count
            FROM chosen x JOIN {join} GROUP BY x.brand_name,f.{col} ORDER BY perfume_count DESC""")
    out["accords"]=fetch("""SELECT x.brand_name,a.accord_name AS category,COUNT(DISTINCT pa.perfume_id)::bigint AS perfume_count
        FROM chosen x JOIN perfume_accord pa USING(perfume_id) JOIN accord a USING(accord_id)
        GROUP BY x.brand_name,a.accord_name ORDER BY perfume_count DESC LIMIT 100""")
    out["notes"]=fetch("""SELECT x.brand_name,n.note_name AS category,COUNT(DISTINCT pn.perfume_id)::bigint AS perfume_count
        FROM chosen x JOIN perfume_note pn USING(perfume_id) JOIN note n USING(note_id)
        GROUP BY x.brand_name,n.note_name ORDER BY perfume_count DESC LIMIT 100""")
    out["years"]=fetch("""SELECT brand_name,release_year,COUNT(*)::bigint AS perfume_count
        FROM chosen GROUP BY brand_name,release_year ORDER BY release_year""")
    return out


def render_brand_section(filters:dict[str,Any]) -> None:
    st.markdown("## Brand & market intelligence")
    st.caption("Side-by-side catalog statistics, ratings and product characteristics — no recommendation logic.")
    spec=build_filtered_query(filters)
    options=filtered_df(spec,"""SELECT DISTINCT b.brand_name FROM filtered f JOIN perfume p USING(perfume_id)
                         JOIN brand b USING(brand_id) ORDER BY b.brand_name""").brand_name.tolist()
    if not options:
        st.info("There are no brands in this filtered population.")
        return
    top=get_brand_analytics(filters,2).category.tolist()
    chosen=st.multiselect("Compare one to five brands",options,default=top,key="compare_brands",max_selections=5)
    if not chosen:
        st.info("Select a brand to inspect its catalog composition.")
        return
    data=get_brand_comparison(filters,chosen)
    st.dataframe(data["summary"],hide_index=True,width="stretch",
                 column_config={"average_rating":st.column_config.NumberColumn(format="%.3f"),
                                "weighted_rating":st.column_config.NumberColumn(format="%.3f")})
    a,b=st.columns(2)
    with a:
        for key,title in (("family","Fragrance families"),("gender","Gender distribution")):
            frame=data[key]
            if not frame.empty:
                frame=frame.sort_values("perfume_count",ascending=False).head(35)
                fig=px.bar(frame,x="category",y="perfume_count",color="brand_name",barmode="group",
                            color_discrete_sequence=PALETTE,title=title)
                fig.update_layout(xaxis_tickangle=-35)
                show_plot(polish(fig,420,True),"brand_"+key)
        frame=data["accords"].sort_values("perfume_count",ascending=False).head(30)
        if not frame.empty:
            fig=px.bar(frame,x="category",y="perfume_count",color="brand_name",barmode="group",
                        color_discrete_sequence=PALETTE,title="Most common accords · selected brands")
            fig.update_layout(xaxis_tickangle=-45)
            show_plot(polish(fig,440,True),"brand_accords")
    with b:
        frame=data["years"]
        if not frame.empty:
            fig=px.line(frame,x="release_year",y="perfume_count",color="brand_name",markers=True,
                        title="Release history by year",color_discrete_sequence=PALETTE)
            show_plot(polish(fig,420,True),"brand_years")
        frame=data["concentration"]
        if not frame.empty:
            fig=px.bar(frame,x="category",y="perfume_count",color="brand_name",barmode="group",
                        title="Concentration mix",color_discrete_sequence=PALETTE)
            show_plot(polish(fig,420,True),"brand_concentration")
        frame=data["notes"].sort_values("perfume_count",ascending=False).head(30)
        if not frame.empty:
            fig=px.bar(frame,x="category",y="perfume_count",color="brand_name",barmode="group",
                        title="Most common notes (all layers)",color_discrete_sequence=PALETTE)
            fig.update_layout(xaxis_tickangle=-40)
            show_plot(polish(fig,440,True),"brand_notes")
    st.markdown("### Market segment comparison")
    segment=get_group_analytics(filters,"Market segment")
    if not segment.empty:
        st.dataframe(segment.rename(columns={"category":"Segment","value":"Perfumes","avg_rating":"Average rating","votes":"Rating votes"}),
                     hide_index=True,width="stretch")


# ───────────────────────────── Custom analytics builder ────────────────────
def render_custom_analytics(filters:dict[str,Any]) -> None:
    st.markdown("## Custom analytics studio")
    st.caption("Build database-backed visualizations from validated metrics and dimensions. No raw SQL input is accepted.")
    a,b,c,d=st.columns([1,1,1,1])
    with a:
        dimension=st.selectbox("Group by",list(DIMENSIONS),key="custom_dimension")
    with b:
        metric=st.selectbox("Metric",list(METRICS),key="custom_metric")
    with c:
        viz=st.selectbox("Chart type",["Horizontal bar","Vertical bar","Line","Donut","Table"],key="custom_chart_type")
    with d:
        sort=st.selectbox("Sort",["Largest first","Smallest first"],key="custom_sort")
    x,y=st.columns(2)
    with x:
        top=st.slider("Maximum groups",5,100,25,key="custom_top_n")
    with y:
        floor=st.number_input("Minimum votes per group",0,10000000,0,step=100,key="custom_group_votes")
    frame=get_group_analytics(filters,dimension,metric,top,sort=="Largest first",floor)
    if frame.empty:
        st.info("No groups satisfy these settings.")
        return
    if viz=="Table":
        st.dataframe(frame,hide_index=True,width="stretch")
    else:
        data=frame.copy()
        data["value"]=pd.to_numeric(data.value,errors="coerce")
        if viz=="Horizontal bar":
            fig=px.bar(data.sort_values("value"),x="value",y="category",orientation="h",color_discrete_sequence=[GOLD])
        elif viz=="Vertical bar":
            fig=px.bar(data,x="category",y="value",color_discrete_sequence=[GOLD])
        elif viz=="Line":
            fig=px.line(data,x="category",y="value",markers=True,color_discrete_sequence=["#314C49"])
        else:
            fig=px.pie(data,names="category",values="value",hole=.45,color_discrete_sequence=PALETTE)
        fig.update_layout(title=dict(text=f"{metric} by {dimension}",font=dict(size=17)))
        show_plot(polish(fig,480,viz=="Donut"),"custom_chart")
    st.download_button("↓ Download analytical data",frame.to_csv(index=False).encode("utf-8-sig"),
                       file_name="custom_analytics.csv",mime="text/csv")


# ─────────────────────────────── Quality and export ───────────────────────
EXPECTED_COUNTS = {"Perfumes":40000,"Brands":1525,"Accords":87,"Notes":1823,
                   "Perfume–accord links":347456,"Perfume–note links":388317}


def get_quality_checks() -> tuple[pd.DataFrame,pd.DataFrame]:
    counts=run_query("""SELECT
       (SELECT COUNT(*) FROM perfume) AS "Perfumes", (SELECT COUNT(*) FROM brand) AS "Brands",
       (SELECT COUNT(*) FROM accord) AS "Accords", (SELECT COUNT(*) FROM note) AS "Notes",
       (SELECT COUNT(*) FROM perfume_accord) AS "Perfume–accord links",
       (SELECT COUNT(*) FROM perfume_note) AS "Perfume–note links" """).iloc[0]
    table=pd.DataFrame([{"Entity":name,"Actual":int(counts[name]),"Expected":expected,
                         "Difference":int(counts[name])-expected,
                         "Status":"PASS" if int(counts[name])==expected else "REVIEW"}
                        for name,expected in EXPECTED_COUNTS.items()])
    integrity=run_query("""SELECT
      (SELECT COUNT(*) FROM perfume WHERE name IS NULL OR btrim(name)='' OR url IS NULL OR btrim(url)='') AS missing_required_values,
      (SELECT COUNT(*) FROM perfume WHERE brand_id IS NULL OR gender_id IS NULL OR concentration_id IS NULL OR family_id IS NULL) AS null_perfume_fks,
      (SELECT COUNT(*) FROM brand WHERE segment_id IS NULL OR group_id IS NULL) AS null_brand_fks,
      (SELECT COUNT(*) FROM perfume p WHERE NOT EXISTS (SELECT 1 FROM perfume_accord pa WHERE pa.perfume_id=p.perfume_id)) AS perfumes_without_accord,
      (SELECT COUNT(*) FROM perfume p WHERE NOT EXISTS (SELECT 1 FROM perfume_note pn WHERE pn.perfume_id=p.perfume_id)) AS perfumes_without_note,
      (SELECT COUNT(*) FROM perfume WHERE rating_value NOT BETWEEN 1 AND 5) AS invalid_ratings,
      (SELECT COUNT(*) FROM perfume WHERE release_year NOT BETWEEN 1500 AND 2100) AS invalid_release_years,
      (SELECT COUNT(*) FROM perfume WHERE rating_count < 0) AS invalid_vote_counts,
      (SELECT COUNT(*) FROM (SELECT perfume_id,accord_id FROM perfume_accord GROUP BY 1,2 HAVING COUNT(*)>1) x) AS duplicate_accord_links,
      (SELECT COUNT(*) FROM (SELECT perfume_id,note_id,note_layer FROM perfume_note GROUP BY 1,2,3 HAVING COUNT(*)>1) x) AS duplicate_note_links,
      (SELECT COUNT(*) FROM perfume p LEFT JOIN brand b USING(brand_id) WHERE b.brand_id IS NULL) AS orphan_perfume_brands,
      (SELECT COUNT(*) FROM perfume_note pn LEFT JOIN perfume p USING(perfume_id) LEFT JOIN note n USING(note_id)
         WHERE p.perfume_id IS NULL OR n.note_id IS NULL) AS orphan_note_links,
      (SELECT COUNT(*) FROM perfume_accord pa LEFT JOIN perfume p USING(perfume_id) LEFT JOIN accord a USING(accord_id)
         WHERE p.perfume_id IS NULL OR a.accord_id IS NULL) AS orphan_accord_links""")
    return table,integrity


def get_full_catalog_export(filters:dict[str,Any]) -> bytes:
    """Full selected population, aggregated in PostgreSQL once (not repeatedly per Streamlit rerun)."""
    spec=build_filtered_query(filters)
    sql=spec.cte+""", accords AS (
       SELECT pa.perfume_id,string_agg(a.accord_name,'; ' ORDER BY pa.accord_rank) AS main_accords
       FROM filtered f JOIN perfume_accord pa USING(perfume_id) JOIN accord a USING(accord_id) GROUP BY pa.perfume_id
    ), notes AS (
       SELECT pn.perfume_id,
         string_agg(n.note_name,'; ' ORDER BY n.note_name) FILTER(WHERE pn.note_layer='Top') AS top_notes,
         string_agg(n.note_name,'; ' ORDER BY n.note_name) FILTER(WHERE pn.note_layer='Middle') AS middle_notes,
         string_agg(n.note_name,'; ' ORDER BY n.note_name) FILTER(WHERE pn.note_layer='Base') AS base_notes
       FROM filtered f JOIN perfume_note pn USING(perfume_id) JOIN note n USING(note_id) GROUP BY pn.perfume_id
    ) SELECT p.perfume_id,p.name,b.brand_name,ms.segment_name AS market_segment,cg.group_name AS corporate_group,
       g.gender_name AS gender,c.concentration_name AS concentration,p.release_year,p.rating_value,
       p.rating_count,ff.family_name AS fragrance_family,accords.main_accords,
       notes.top_notes,notes.middle_notes,notes.base_notes,p.url
       FROM filtered f JOIN perfume p USING(perfume_id) JOIN brand b USING(brand_id)
       JOIN market_segment ms ON ms.segment_id=b.segment_id JOIN corporate_group cg ON cg.group_id=b.group_id
       JOIN gender g ON g.gender_id=p.gender_id JOIN concentration c ON c.concentration_id=p.concentration_id
       JOIN fragrance_family ff ON ff.family_id=p.family_id
       LEFT JOIN accords ON accords.perfume_id=p.perfume_id
       LEFT JOIN notes ON notes.perfume_id=p.perfume_id ORDER BY p.perfume_id"""
    return run_query(sql,spec.params).to_csv(index=False).encode("utf-8-sig")


def render_quality_export(filters:dict[str,Any]) -> None:
    st.markdown("## Data integrity & export")
    st.caption("Expected row counts come from the project brief. Actual values always come from the connected PostgreSQL database.")
    c,v=get_quality_checks()
    st.subheader("Imported data versus expected counts")
    st.dataframe(c,hide_index=True,width="stretch",
                 column_config={"Status":st.column_config.TextColumn("Validation status")})
    st.subheader("Relationship and attribute integrity")
    series=v.iloc[0]
    problems=pd.DataFrame({"Check":series.index.tolist(),"Problem count":[int(x) for x in series.tolist()]})
    st.dataframe(problems,hide_index=True,width="stretch")
    if (c.Difference!=0).any() or (problems["Problem count"]!=0).any():
        st.warning("Review discrepancies above. The dashboard never modifies records to force expected counts.")
    else:
        st.success("All specified counts and integrity checks passed.")
    st.divider()
    st.subheader("Filtered collection export")
    spec=build_filtered_query(filters)
    n=get_catalog_count(spec)
    st.caption(f"Export exactly the {n:,} perfumes matching your current global search and filters, including all note layers.")
    signature=json.dumps(filters,sort_keys=True,default=str)
    if st.session_state.get("export_signature")!=signature:
        st.session_state.pop("export_content",None)
    if st.button("Prepare full filtered CSV",type="primary",key="prepare_full_export"):
        with st.spinner("Aggregating filtered records directly in PostgreSQL…"):
            st.session_state["export_content"]=get_full_catalog_export(filters)
            st.session_state["export_signature"]=signature
    if st.session_state.get("export_signature")==signature and "export_content" in st.session_state:
        st.download_button("↓ Download filtered dataset",data=st.session_state["export_content"],
                           file_name="perfume_intelligence_filtered.csv",mime="text/csv",type="primary")
    st.markdown("#### Source views (BQ01–BQ10)")
    with st.expander("Inspect the ten baseline PostgreSQL views"):
        selected=st.selectbox("Business question",[f"BQ{i:02d}" for i in range(1,11)],key="baseline_view_choice")
        # View name is selected from a fixed whitelist, never sourced from arbitrary text.
        view=f"vw_bq{int(selected[2:]):02d}"
        try:
            frame=run_query(f"SELECT * FROM {view} LIMIT 30")
            st.dataframe(frame,hide_index=True,width="stretch")
            st.caption("These are global, unfiltered baseline views. All charts and KPIs use dynamically filtered SQL instead.")
        except Exception as exc:
            st.warning(f"Baseline view is unavailable: {str(exc).splitlines()[0][:200]}")
    with st.expander("SQL performance diagnostics"):
        st.caption("Execute a read-only EXPLAIN ANALYZE on a parameterized filtered aggregate. This can be slow for complex search conditions.")
        if st.button("Inspect current filtered query plan"):
            with get_database_connection().connect() as conn:
                rows=conn.execute(text("EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) "+spec.cte+
                      " SELECT COUNT(*) FROM filtered"),spec.params).scalars().all()
            st.code("\n".join(rows),language="text")


# ─────────────────────────── Startup and self-checks ──────────────────────
def database_self_test() -> list[tuple[str,bool,str]]:
    """Runnable from this SAME file with --self-test; includes direct SQL crosschecks."""
    tests=[]
    def assert_check(name:str, test:bool, detail:str=""):
        tests.append((name,bool(test),detail))
    # No fabricated perfume rows: vocabulary and schema conditions only.
    assert_check("Arabic query normalization",normalize_search_query("العنبر نيش") == "amber niche")
    assert_check("English typo normalization",normalize_search_query("Diorr") == "diorr")
    values={"brand":["Dior"],"segment":["Niche / Indie","Designer / Prestige"],
            "gender":["Unisex"],"concentration":["EDP"],"family":["Amber Floral"],
            "accord":["woody","amber"],"note":["amber","vanilla","bergamot"],"group":[]}
    specs=parse_search_intent("Unisex Woody Niche EDP",values)
    assert_check("Four-condition parsing",set((s["kind"],s["value"]) for s in specs)==
                 {("gender","Unisex"),("ingredient","woody"),("segment","Niche / Indie"),("concentration","EDP")})
    assert_check("Fuzzy brand recognition",any(s["value"]=="Dior" for s in parse_search_intent("diorr",values)))
    assert_check("Fuzzy note recognition",any(s["value"]=="vanilla" for s in parse_search_intent("vanila",values)))
    assert_check("Arabic alias recognition",any(s["value"]=="amber" for s in parse_search_intent("عنبر",values)))
    standard={**{k:[] for k in FILTER_FIELDS},"year":(1500,2100),"min_rating":1.0,"min_votes":0,"match_mode":"ANY"}
    normal=build_filtered_query(standard)
    assert_check("Parameterized base filter", ":year_min" in normal.cte and "1500" not in normal.cte)
    both={**standard,"base":["amber"],"segment":["Niche / Indie"]}
    mixed=build_filtered_query(both)
    assert_check("AND combination + EXISTS (not join inflation)","rel.note_layer='Base'" in mixed.cte and "ms.segment_name = ANY(:segment)" in mixed.cte)
    try:
        opts=get_filter_options()
        actual=run_query("SELECT COUNT(*) AS n FROM perfume").iloc[0].n
        assert_check("PostgreSQL connection and row count",int(actual)==opts["records"],str(actual))
        expected=run_query("SELECT COUNT(*) AS n FROM perfume p JOIN brand b USING(brand_id) "
                           "JOIN market_segment ms ON ms.segment_id=b.segment_id WHERE ms.segment_name='Niche / Indie'").iloc[0].n
        filters={**default_filter_values(opts),"segment":["Niche / Indie"]}
        assert_check("Direct SQL versus filtered CTE",get_catalog_count(build_filtered_query(filters))==int(expected),str(expected))
        mix={**filters,"base":["amber"]}
        k=get_dashboard_kpis(mix)
        compare=run_query("""SELECT COUNT(*) AS n FROM perfume p JOIN brand b USING(brand_id)
           JOIN market_segment ms ON ms.segment_id=b.segment_id WHERE ms.segment_name='Niche / Indie'
           AND EXISTS(SELECT 1 FROM perfume_note pn JOIN note n USING(note_id)
                      WHERE pn.perfume_id=p.perfume_id AND pn.note_layer='Base' AND n.note_name='amber')""").iloc[0].n
        assert_check("Combined segment and base note",int(k.perfume_count)==int(compare),str(compare))
        page=get_catalog_page(build_filtered_query(filters),1,10,"Most votes",filters)
        assert_check("Server-side pagination",len(page)==10)
        assert_check("Source URLs",page.url.str.startswith("http").all())
        assert_check("Votes sorting",page.rating_count.is_monotonic_decreasing)
        # Search results are tested against independent direct SQL aggregations.
        brand_filters={**default_filter_values(opts),"search_specs":parse_search_intent("diorr",opts)}
        direct_brand=int(run_query("SELECT COUNT(*) AS n FROM perfume p JOIN brand b USING(brand_id) "
                    "WHERE b.brand_name=:brand",{"brand":"Dior"}).iloc[0].n)
        assert_check("Typo search vs direct brand SQL",
                     get_catalog_count(build_filtered_query(brand_filters))==direct_brand,str(direct_brand))
        brand_page=get_catalog_page(build_filtered_query(brand_filters),1,5,"Most votes",brand_filters)
        assert_check("Brand search record identity",not brand_page.empty and (brand_page.brand_name=="Dior").all())
        note_filters={**default_filter_values(opts),"base":["amber"]}
        note_direct=int(run_query("""SELECT COUNT(DISTINCT pn.perfume_id) AS n FROM perfume_note pn
                          JOIN note n USING(note_id) WHERE pn.note_layer='Base' AND n.note_name='amber'""").iloc[0].n)
        assert_check("Base note count vs direct SQL",
                     get_catalog_count(build_filtered_query(note_filters))==note_direct,str(note_direct))
        accord_filters={**default_filter_values(opts),"accord":["woody"]}
        accord_direct=int(run_query("""SELECT COUNT(DISTINCT pa.perfume_id) AS n FROM perfume_accord pa
                        JOIN accord a USING(accord_id) WHERE a.accord_name='woody'""").iloc[0].n)
        assert_check("Main accord count vs direct SQL",
                     get_catalog_count(build_filtered_query(accord_filters))==accord_direct,str(accord_direct))
        full=get_dashboard_kpis(default_filter_values(opts))
        assert_check("Full dataset KPI",int(full.perfume_count)==int(actual))
        assert_check("Dynamic filtering changes KPI",int(k.perfume_count)<=int(expected)<=int(actual))
        assert_check("Release-year grouping matches KPI",
                     int(get_release_breakdown(filters,"Year").perfume_count.sum())==int(expected))
        view_count=run_query("SELECT COUNT(*) AS n FROM pg_views WHERE schemaname=current_schema() "
                             "AND viewname LIKE 'vw_bq__'").iloc[0].n
        assert_check("All BQ01–BQ10 views exist",int(view_count)==10,str(view_count))
        exported=get_full_catalog_export(brand_filters)
        import io
        export_df=pd.read_csv(io.BytesIO(exported))
        assert_check("Filtered full CSV export count",len(export_df)==direct_brand,str(len(export_df)))
        rows,quality=get_quality_checks()
        assert_check("Database baseline integrity",bool((rows.Difference==0).all() and (quality.iloc[0]==0).all()))
        out=get_group_analytics(filters,"Market segment")
        assert_check("Grouped chart count matches KPI",int(out.value.sum())==int(expected))
    except Exception as exc:
        assert_check("Live database self-check",False,str(exc).split("\n")[0][:160])
    return tests


# ─────────────────────────── Simple, analysis-first UX ─────────────────────
# The advanced analytics and database functions above remain available.
# These UI wrappers expose a short, guided path for first-time users.


def set_example_search(term: str) -> None:
    """Set the main search field from one of the beginner-friendly examples."""
    st.session_state["global_search"] = term
    st.session_state["s_page"] = "Explore perfumes"


def render_simple_filters(options: dict[str, Any]) -> dict[str, Any]:
    """Three everyday filters and a collapsed advanced section; all use the core SQL CTE."""
    st.sidebar.markdown("#### Filter the data")
    st.sidebar.caption("Choose only what you need. All charts update together.")
    segments = ["All segments", *options["segment"]]
    genders = ["All genders", *options["gender"]]
    ingredients = ["Any ingredient", *sorted(set(options["note"]) | set(options["accord"]), key=str.casefold)]
    segment = st.sidebar.selectbox("Market segment", segments, key="s_segment")
    gender = st.sidebar.selectbox("Gender", genders, key="s_gender")
    ingredient = st.sidebar.selectbox("Ingredient (optional)", ingredients, key="s_ingredient",
                                      help="Matches notes, accords and fragrance-family names.")
    filters = default_filter_values(options)
    if segment != "All segments":
        filters["segment"] = [segment]
    if gender != "All genders":
        filters["gender"] = [gender]
    if ingredient != "Any ingredient":
        filters["search_specs"] = [{"kind": "ingredient", "value": ingredient,
                                     "label": f"Ingredient: {ingredient}", "source": "exact"}]
    else:
        filters["search_specs"] = []

    with st.sidebar.expander("More filters · optional", expanded=False):
        filters["brand"] = st.multiselect("Brands", options["brand"], key="s_brand")
        filters["concentration"] = st.multiselect("Concentration", options["concentration"], key="s_concentration")
        filters["family"] = st.multiselect("Fragrance family", options["family"], key="s_family")
        filters["group"] = st.multiselect("Corporate group", options["group"], key="s_group")
        filters["year"] = st.slider("Release years", min_value=options["year_min"],
                                    max_value=options["year_max"],
                                    value=(options["year_min"], options["year_max"]), key="s_year")
        filters["min_rating"] = st.slider("Minimum rating", 1.0, 5.0, 1.0, 0.1, key="s_min_rating")
        filters["min_votes"] = st.number_input("Minimum rating votes", min_value=0, value=0,
                                               step=25, key="s_min_votes")
        layer = st.selectbox("Find notes in layer", ["Any layer", "Top", "Middle", "Base"],
                              key="s_layer")
        notes = st.multiselect("Specific notes", options["note"], key="s_layer_notes")
        if layer != "Any layer":
            filters[layer.lower()] = notes
        elif notes:
            # One ingredient condition per selected note, all must match if selected here.
            filters["search_specs"].extend({"kind": "ingredient", "value": note,
                                             "label": f"Ingredient: {note}", "source": "exact"}
                                            for note in notes)
        filters["accord"] = st.multiselect("Specific accords", options["accord"], key="s_accord")
        filters["match_mode"] = st.radio("Multiple accords/notes in a selected layer", ["ANY", "ALL"],
                                          horizontal=True, key="s_match_mode")
        st.caption("Notes selected in 'Any layer' require all entered notes; choose a specific layer for ANY/ALL options.")

    st.sidebar.button("↺ Clear search and filters", use_container_width=True,
                      on_click=reset_filters)
    return filters


def render_simple_header() -> str:
    st.markdown("""<div class='hero'><span class='eyebrow'>FRAGRANCE DATA EXPLORER</span>
        <h1>Perfume Intelligence</h1>
        <p>Find a fragrance, explore ingredients, and understand the data in a few clicks.</p></div>""",
        unsafe_allow_html=True)
    st.markdown("**What would you like to explore?**")
    value = st.text_input("Search perfumes, brands, notes or categories", key="global_search",
                          placeholder="Search Amber, Dior, Niche Amber, or عنبر")
    cols = st.columns([1, 1, 1, 1.6])
    for col, term in zip(cols[:3], ["Amber", "Niche", "Unisex Woody"]):
        with col:
            st.button(f"Try: {term}", on_click=set_example_search, args=(term,),
                      use_container_width=True, key="example_" + term.replace(" ", "_"))
    return value


def render_simple_interpretation(query: str, options: dict[str, Any]) -> list[dict[str, str]]:
    specs = parse_search_intent(query, options)
    fingerprint = (query, 84)
    if st.session_state.get("_last_search") != fingerprint:
        st.session_state["_last_search"] = fingerprint
        st.session_state["search_active"] = [item["label"] for item in specs]
        st.session_state["results_page"] = 1
    if not specs:
        return []
    selected = st.session_state.get("search_active", [])
    st.caption("Search understood as: " + "  •  ".join(selected) if selected else
               "All search conditions removed. Your other filters still apply.")
    with st.expander("Change or remove interpreted search terms", expanded=False):
        selected = st.multiselect("Use these conditions", [item["label"] for item in specs],
                                  key="search_active")
        st.caption("Select only the conditions you want. All selected conditions must match.")
    return [item for item in specs if item["label"] in selected]


def render_simple_kpis(filters: dict[str, Any], total_records: int) -> int:
    k = get_dashboard_kpis(filters)
    count = int(k.perfume_count)
    st.markdown("### At a glance")
    cols = st.columns(4)
    cols[0].metric("Perfumes found", f"{count:,}")
    cols[1].metric("Brands", f"{int(k.brand_count):,}")
    cols[2].metric("Average rating", f"{float(k.avg_rating):.2f} / 5" if pd.notna(k.avg_rating) else "—")
    cols[3].metric("Total rating votes", f"{int(k.total_votes):,}")
    pct = (100 * count / total_records) if total_records else 0.0
    st.caption(f"These results include {pct:.1f}% of the imported catalog. Metrics reflect your current search and filters, not sales or market share.")
    if count == 0:
        st.warning("No matching perfumes. Remove a search condition or click 'Clear search and filters'.")
    return count


def render_simple_insights(filters: dict[str, Any], population: int) -> None:
    """Show three plain-language, data-derived findings before charts."""
    segment = get_group_analytics(filters, "Market segment", top_n=1)
    accord = get_accord_analytics(filters, top_n=1)
    brand = get_brand_analytics(filters, limit=1)
    st.markdown("### Three key findings")
    cols = st.columns(3)
    rows = [
        (segment, "Largest segment", "value"),
        (accord, "Most common accord", "perfume_count"),
        (brand, "Largest brand catalog", "value"),
    ]
    for col, (df, title, metric) in zip(cols, rows):
        with col:
            with st.container(border=True):
                st.caption(title)
                if len(df):
                    record = df.iloc[0]
                    st.markdown("**" + str(record.category) + "**")
                    n = int(record[metric])
                    st.write(f"{n:,} perfumes · {100*n/population:.1f}% of current results")
                else:
                    st.write("No data")


def go_to_analysis_topic(topic: str) -> None:
    """Navigate to an analysis question using the same single-page Streamlit app."""
    st.session_state["s_page"] = "More analysis"
    st.session_state["simple_topic"] = topic


def render_simple_overview(filters: dict[str, Any], population: int) -> None:
    if not population:
        return
    st.markdown("**Choose what you want to understand**")
    a, b, c = st.columns(3)
    for col, label, topic in (
        (a, "Which brands dominate?", "Market & brands"),
        (b, "What ingredients are common?", "Ingredients"),
        (c, "How do ratings change?", "Ratings & releases"),
    ):
        with col:
            st.button(label, key="question_" + topic.replace(" ", "_"),
                      on_click=go_to_analysis_topic, args=(topic,), use_container_width=True)
    render_simple_insights(filters, population)
    st.markdown("### The big picture")
    left, right = st.columns(2)
    with left:
        groups = get_group_analytics(filters, "Market segment")
        donut_chart(groups, "category", "value", "Perfumes by market segment", "simple_segment")
    with right:
        accord = get_accord_analytics(filters, 12)
        bar_chart(accord, "category", "perfume_count", "Most frequently listed accords", "simple_accord")
    st.markdown("### How fragrance releases have changed")
    history = get_release_breakdown(filters, "Decade")
    if len(history):
        fig = px.bar(history, x="period", y="perfume_count", color_discrete_sequence=[GOLD],
                     title="Number of perfumes by release decade")
        fig.update_layout(xaxis_title="Release decade", yaxis_title="Perfume records")
        show_plot(polish(fig, 350), "simple_history")
    st.caption("Counts describe this dataset only; the chart does not measure global perfume sales.")


def render_simple_market(filters: dict[str, Any]) -> None:
    st.markdown("### Market and brand analysis")
    st.caption("Explore which groups occupy more of the imported catalog—not sales share.")
    a, b = st.columns(2)
    with a:
        segment = get_group_analytics(filters, "Market segment")
        bar_chart(segment, "category", "value", "Perfumes by market segment", "simple_market_seg", "segment")
        gender = get_group_analytics(filters, "Gender")
        donut_chart(gender, "category", "value", "Gender categories", "simple_market_gender")
    with b:
        brands = get_brand_analytics(filters, 15)
        bar_chart(brands, "category", "value", "Largest brand catalogs", "simple_market_brand", "brand")
        fam = get_group_analytics(filters, "Fragrance family", top_n=10)
        bar_chart(fam, "category", "value", "Most represented fragrance families", "simple_market_family", "family")


def render_simple_ingredients(filters: dict[str, Any], options: dict[str, Any]) -> None:
    st.markdown("### Ingredient analysis")
    st.caption("See which accords and notes are most common in the current selection.")
    a, b = st.columns(2)
    with a:
        accord = get_accord_analytics(filters, 15)
        bar_chart(accord, "category", "perfume_count", "Most common accords", "simple_ing_accord")
    with b:
        layer = st.radio("Note position", ["Top", "Middle", "Base"], horizontal=True, key="simple_notes_layer")
        notes = get_note_analytics(filters, layer, 15)
        bar_chart(notes, "category", "perfume_count", f"Common {layer.lower()} notes", "simple_ing_layer")
    with st.expander("Analyze one ingredient in detail", expanded=False):
        render_ingredient_section(filters, options)


def render_simple_ratings(filters: dict[str, Any]) -> None:
    st.markdown("### Ratings and release history")
    st.caption("Choose a minimum number of votes to avoid overemphasizing perfumes with few ratings.")
    floor = st.select_slider("Minimum rating votes per perfume", options=[0, 10, 50, 100, 500, 1000],
                             value=100, key="simple_votes_floor")
    ratings = get_rating_analytics(filters, floor)
    year = get_release_breakdown(filters, "Year")
    a, b = st.columns(2)
    with a:
        if len(ratings):
            fig = px.histogram(ratings, x="rating_value", nbins=28, color_discrete_sequence=[GOLD],
                               title="Rating distribution")
            show_plot(polish(fig, 360), "simple_rating_distribution")
            st.caption(f"{len(ratings):,} perfumes meet the {floor:,}-vote threshold.")
        else:
            st.info("No perfumes meet this vote threshold.")
    with b:
        if len(year):
            fig = px.line(year, x="period", y="perfume_count", markers=True,
                          color_discrete_sequence=["#314C49"], title="Perfume releases by year")
            show_plot(polish(fig, 360), "simple_releases")
    decade = get_release_breakdown(filters, "Decade")
    if len(decade):
        fig = px.line(decade, x="period", y="avg_rating", markers=True,
                      color_discrete_sequence=["#314C49"], title="Average rating by release decade")
        show_plot(polish(fig, 340), "simple_rating_by_decade")
        st.caption("The average is calculated from current ratings of perfumes released in each decade, not historical reviews collected then.")


def render_simple_deep_analysis(filters: dict[str, Any], options: dict[str, Any]) -> None:
    st.markdown("## Choose an analysis")
    topic = st.radio("Analysis topic", ["Market & brands", "Ingredients", "Ratings & releases",
                                        "Compare brands", "Build a chart", "Data checks & export"],
                     horizontal=True, key="simple_topic")
    if topic == "Market & brands":
        render_simple_market(filters)
    elif topic == "Ingredients":
        render_simple_ingredients(filters, options)
    elif topic == "Ratings & releases":
        render_simple_ratings(filters)
    elif topic == "Compare brands":
        render_brand_section(filters)
    elif topic == "Build a chart":
        render_custom_analytics(filters)
    else:
        render_quality_export(filters)


def main() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    ensure_pending_drilldown()
    with st.sidebar:
        st.markdown("### ◈ PERFUME INTELLIGENCE")
        st.caption("Easy analysis · PostgreSQL data")
        st.divider()
        page = st.radio("Where do you want to go?", ["Overview", "Explore perfumes", "More analysis"],
                        key="s_page")
        st.divider()
        connected, status = get_database_status()
        if connected:
            st.success("● Database connected")
        else:
            st.error("● Database disconnected")
            st.caption(status)
    if not connected:
        st.error("The app cannot reach the PostgreSQL database. Your imported data is not changed.")
        st.markdown("Create a **`.env`** file beside `app.py` containing your real PostgreSQL database URL.")
        st.code("DATABASE_URL=postgresql+psycopg://postgres:YOUR_PASSWORD@localhost:5432/Perfume", language="text")
        st.caption("The database name is case-sensitive if it was created with quoted mixed case. Do not run the SQL rebuild just to fix a connection URL.")
        return
    try:
        options = get_filter_options()
        filters = render_simple_filters(options)
        with st.sidebar:
            st.caption(f"{options['records']:,} imported records • {len(options['brand']):,} brands")
            if st.button("↻ Refresh data", use_container_width=True):
                _cached_query.clear()
                get_filter_options.clear()
                st.rerun()
        query = render_simple_header()
        parsed = render_simple_interpretation(query, options)
        filters["search_specs"] = [*filters.get("search_specs", []), *parsed]
        st.session_state["filters"] = filters
        population = render_simple_kpis(filters, int(options["records"]))
        if page == "Overview":
            render_simple_overview(filters, population)
        elif page == "Explore perfumes":
            st.markdown("## Perfumes matching your search")
            st.caption("Browse individual perfumes, inspect notes, open source links, and export rows.")
            render_result_table(filters, "results", show_header=False)
        else:
            if population:
                render_simple_deep_analysis(filters, options)
        st.divider()
        st.caption("All figures are calculated from your PostgreSQL data. No generated perfume records or recommendations.")
    except Exception as exc:
        st.error("Unable to load the requested analysis. Check your connection and selected filters.")
        st.exception(exc)


if __name__ == "__main__":
    import sys
    if "--self-test" in sys.argv:
        tests=database_self_test()
        for name,passed,detail in tests:
            print(("PASS" if passed else "FAIL")+": "+name+(" · "+detail if detail else ""))
        sys.exit(0 if all(passed for _,passed,_ in tests) else 1)
    main()

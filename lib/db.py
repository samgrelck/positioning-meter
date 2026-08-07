"""SQLite schema and connection helper for positioning meter.

Single DB at data/positioning.db. WAL mode, integer FKs disabled (we use
ticker strings as natural keys). Tables organized by data domain.
"""
import sqlite3
from pathlib import Path
from .config import load, project_path


SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

-- ============================================================
-- RAW DATA TABLES (one row per ticker per observation date)
-- ============================================================

CREATE TABLE IF NOT EXISTS prices (
    ticker     TEXT NOT NULL,
    date       TEXT NOT NULL,
    open       REAL,
    high       REAL,
    low        REAL,
    close      REAL,
    adj_close  REAL,
    volume     INTEGER,
    PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS short_interest (
    ticker        TEXT NOT NULL,
    settlement_date TEXT NOT NULL,
    short_interest INTEGER,
    avg_daily_volume INTEGER,
    days_to_cover REAL,
    pct_float     REAL,
    PRIMARY KEY (ticker, settlement_date)
);

-- True bi-monthly SI from NASDAQ API (level, not flow). Distinct from
-- short_interest table which is FINRA daily Reg SHO short volume proxy.
CREATE TABLE IF NOT EXISTS short_interest_true (
    ticker        TEXT NOT NULL,
    settlement_date TEXT NOT NULL,
    short_interest INTEGER,
    avg_daily_share_volume INTEGER,
    days_to_cover REAL,
    PRIMARY KEY (ticker, settlement_date)
);

-- PK must contain ONLY columns the provider actually populates. openinsider
-- leaves filer_cik and direct_indirect NULL on every row, and SQLite treats
-- NULLs in a PK as distinct — so a PK containing filer_cik never matched, and
-- `INSERT OR REPLACE` in setup/05_ingest_insider.py appended a full duplicate
-- copy of the table on every daily run (2.7M rows for 77k transactions before
-- this was caught). Keep NULLable columns OUT of this key.
-- See tools/fix_insider_dupes.py for the migration.
CREATE TABLE IF NOT EXISTS insider_form4 (
    accession      TEXT NOT NULL,
    ticker         TEXT NOT NULL,
    filer_cik      TEXT,
    filer_name     TEXT NOT NULL,
    relationship   TEXT,
    transaction_date TEXT NOT NULL,
    transaction_code TEXT NOT NULL,
    shares         REAL NOT NULL,
    price_per_share REAL NOT NULL,
    value_usd      REAL,
    direct_indirect TEXT,
    PRIMARY KEY (accession, ticker, transaction_date, transaction_code,
                 shares, price_per_share, filer_name)
);
CREATE INDEX IF NOT EXISTS idx_insider_ticker_date ON insider_form4(ticker, transaction_date);

CREATE TABLE IF NOT EXISTS holdings_13f (
    accession    TEXT NOT NULL,
    filer_cik    TEXT NOT NULL,
    filer_name   TEXT,
    period_end   TEXT NOT NULL,
    ticker       TEXT NOT NULL,
    shares       INTEGER,
    value_usd    REAL,
    PRIMARY KEY (accession, ticker)
);
CREATE INDEX IF NOT EXISTS idx_13f_ticker_period ON holdings_13f(ticker, period_end);
CREATE INDEX IF NOT EXISTS idx_13f_filer_period ON holdings_13f(filer_cik, period_end);

CREATE TABLE IF NOT EXISTS hedge_funds (
    cik         TEXT PRIMARY KEY,
    name        TEXT,
    is_hedge_fund INTEGER,
    aum_usd     REAL,
    last_updated TEXT
);

CREATE TABLE IF NOT EXISTS etf_aum (
    etf_ticker  TEXT NOT NULL,
    date        TEXT NOT NULL,
    shares_outstanding REAL,
    nav         REAL,
    aum_usd     REAL,
    daily_flow_estimate REAL,  -- Δ(shares_out) × NAV when shares_out available, else null
    PRIMARY KEY (etf_ticker, date)
);

CREATE TABLE IF NOT EXISTS etf_holdings (
    etf_ticker  TEXT NOT NULL,
    date        TEXT NOT NULL,
    ticker      TEXT NOT NULL,
    weight_pct  REAL,
    shares      INTEGER,
    PRIMARY KEY (etf_ticker, date, ticker)
);

CREATE TABLE IF NOT EXISTS options_daily (
    ticker          TEXT NOT NULL,
    date            TEXT NOT NULL,
    iv_30d          REAL,
    iv_3m           REAL,
    iv_term_slope   REAL,
    skew_25d        REAL,
    pc_volume_ratio REAL,
    pc_oi_ratio     REAL,
    options_volume  INTEGER,
    avg_options_volume_20d INTEGER,
    PRIMARY KEY (ticker, date)
);

-- Fundamental snapshot pulled from yfinance — sparse, daily best-effort.
CREATE TABLE IF NOT EXISTS valuation_daily (
    ticker     TEXT NOT NULL,
    date       TEXT NOT NULL,
    ntm_eps    REAL,
    ntm_pe     REAL,
    ev         REAL,
    sales_ttm  REAL,
    ev_sales   REAL,
    PRIMARY KEY (ticker, date)
);

-- Per-quarter raw fundamentals from yfinance (income + balance sheet).
-- Used to derive valuation_daily at signal-compute time, point-in-time
-- aware via filing_date_est.
CREATE TABLE IF NOT EXISTS fundamentals_q (
    ticker            TEXT NOT NULL,
    period_end        TEXT NOT NULL,
    fiscal_period     TEXT NOT NULL,  -- Q1|Q2|Q3|Q4|FY|TTM
    fiscal_year       TEXT,
    filing_date_est   TEXT,
    diluted_eps_q     REAL,
    total_revenue_q   REAL,
    total_debt        REAL,
    cash_and_short_term REAL,
    shares_out        REAL,
    PRIMARY KEY (ticker, period_end, fiscal_period)
);
CREATE INDEX IF NOT EXISTS idx_fund_q_filing ON fundamentals_q(ticker, filing_date_est);

-- Free float + shares outstanding snapshot (yfinance). Float moves slowly, so a
-- periodic snapshot is sufficient; the latest row per ticker is used as the
-- divisor for float-turnover (a long/retail-crowding proxy).
CREATE TABLE IF NOT EXISTS share_float (
    ticker        TEXT NOT NULL,
    asof_date     TEXT NOT NULL,
    float_shares  REAL,
    shares_out    REAL,
    -- V1.22: fraction of shares held by institutions, all 13F filers (yfinance
    -- heldPercentInstitutions). Distinct from the inst_own_pct overlay, which is
    -- our 40-fund curated hedge-fund list only. Snapshot, forward-only — it
    -- backs the dashboard's "well-held" ownership guard, never the composite.
    inst_held_pct REAL,
    PRIMARY KEY (ticker, asof_date)
);

-- Daily decile "book" log for LIVE forward-performance tracking. Each refresh
-- appends the bottom-decile (candidate longs) and top-decile (candidate shorts)
-- by temperature; realized forward returns are computed later from prices, so
-- this accumulates genuine out-of-sample evidence over time.
CREATE TABLE IF NOT EXISTS book_log (
    date        TEXT NOT NULL,
    ticker      TEXT NOT NULL,
    side        TEXT NOT NULL,   -- 'long' (washed-out) | 'short' (crowded)
    temperature REAL,
    source      TEXT NOT NULL DEFAULT 'live',  -- 'live' = genuine out-of-sample (logged forward); 'backfill' = in-sample history
    PRIMARY KEY (date, ticker)
);

-- ============================================================
-- COMPUTED SIGNAL TABLES (one row per ticker per date per signal)
-- ============================================================

CREATE TABLE IF NOT EXISTS signals_daily (
    ticker      TEXT NOT NULL,
    date        TEXT NOT NULL,
    signal_name TEXT NOT NULL,
    bucket      TEXT NOT NULL,    -- positioning|options|flows|valuation|technical
    raw_value   REAL,
    pct_self    REAL,             -- 0..100 vs own trailing history
    pct_peer    REAL,             -- 0..100 vs cluster peers same date
    PRIMARY KEY (ticker, date, signal_name)
);
CREATE INDEX IF NOT EXISTS idx_signals_date_bucket ON signals_daily(date, bucket);

CREATE TABLE IF NOT EXISTS composite_daily (
    ticker          TEXT NOT NULL,
    date            TEXT NOT NULL,
    temperature     REAL,         -- 0..100
    score_positioning REAL,
    score_options   REAL,
    score_flows     REAL,
    score_valuation REAL,
    score_technical REAL,
    conviction      REAL,         -- 0..100, higher = buckets more aligned (low std)
    anomaly_count   INTEGER,      -- # signals where this ticker is 90th+ %ile vs cluster
    flag_late_signal INTEGER,
    flag_washout    INTEGER,
    flag_divergence INTEGER,
    flag_earnings_soon INTEGER,
    -- V1.18: self-vs-own-history. Percentile (0..100) + z (std-devs) of today's
    -- score vs the SAME name's own trailing 1y (252d) / 6mo (126d) distribution.
    -- High pct/z = hot for itself; low = cold for itself. Surfaces structurally
    -- cool names (semis) that are unusual relative to their own norm.
    temp_selfpct_1y REAL,
    temp_selfpct_6m REAL,
    temp_selfz_1y   REAL,
    pos_selfpct_1y  REAL,
    pos_selfpct_6m  REAL,
    pos_selfz_1y    REAL,
    tech_selfpct_1y REAL,
    tech_selfpct_6m REAL,
    tech_selfz_1y   REAL,
    opt_selfpct_1y  REAL,
    opt_selfpct_6m  REAL,
    opt_selfz_1y    REAL,
    -- V1.20: EX-TECHNICAL self-history. Same idea as temp_selfpct_*, but scored
    -- off a composite built from the positioning + options buckets ONLY (their
    -- config weights, renormalized) — i.e. the self-history read with all
    -- price/momentum-derived signal stripped out.
    extech_selfpct_1y REAL,
    extech_selfpct_6m REAL,
    extech_selfz_1y   REAL,
    PRIMARY KEY (ticker, date)
);
CREATE INDEX IF NOT EXISTS idx_composite_date_temp ON composite_daily(date, temperature);

-- ============================================================
-- LIVE OVERLAYS (not in composite — context only)
-- ============================================================

-- Daily snapshot of consensus EPS estimates from yfinance.
-- Forward-only history (we accumulate from today onward).
CREATE TABLE IF NOT EXISTS estimates_daily (
    ticker             TEXT NOT NULL,
    date               TEXT NOT NULL,
    forward_eps        REAL,
    trailing_eps       REAL,
    target_mean_price  REAL,
    target_high_price  REAL,
    target_low_price   REAL,
    target_dispersion  REAL,
    num_analyst_opinions INTEGER,
    recommendation_key TEXT,    -- 'buy' | 'hold' | 'sell' etc.
    recommendation_mean REAL,   -- 1=Strong Buy ... 5=Sell
    PRIMARY KEY (ticker, date)
);

-- Per-ticker analyst rating actions (upgrades/downgrades) from yfinance.
CREATE TABLE IF NOT EXISTS analyst_actions (
    ticker     TEXT NOT NULL,
    action_date TEXT NOT NULL,
    firm       TEXT,
    from_grade TEXT,
    to_grade   TEXT,
    action     TEXT,
    PRIMARY KEY (ticker, action_date, firm)
);

-- Per-ticker upcoming earnings date.
CREATE TABLE IF NOT EXISTS earnings_calendar (
    ticker         TEXT PRIMARY KEY,
    next_earnings_date TEXT,
    last_updated   TEXT
);

-- Notes/journal per ticker — analyst-authored.
CREATE TABLE IF NOT EXISTS ticker_notes (
    ticker    TEXT PRIMARY KEY,
    note      TEXT,
    updated_at TEXT
);

-- Watchlist — tickers user wants to highlight.
CREATE TABLE IF NOT EXISTS watchlist (
    ticker     TEXT PRIMARY KEY,
    added_at   TEXT,
    label      TEXT
);

-- ============================================================
-- INGESTION BOOKKEEPING
-- ============================================================

CREATE TABLE IF NOT EXISTS ingestion_runs (
    provider    TEXT NOT NULL,
    run_id      TEXT NOT NULL,
    started_at  TEXT,
    finished_at TEXT,
    status      TEXT,             -- ok|partial|failed
    rows_written INTEGER,
    notes       TEXT,
    PRIMARY KEY (provider, run_id)
);
"""


def get_db_path() -> Path:
    cfg = load()
    return project_path(cfg["storage"]["db_path"])


def connect() -> sqlite3.Connection:
    path = get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


# Columns added after the original composite_daily was created. CREATE TABLE
# IF NOT EXISTS won't add columns to a table that already exists, so these are
# applied via ALTER TABLE on existing DBs. (col_name, sql_type).
_ADDED_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "composite_daily": [
        ("temp_selfpct_1y", "REAL"), ("temp_selfpct_6m", "REAL"), ("temp_selfz_1y", "REAL"),
        ("pos_selfpct_1y", "REAL"), ("pos_selfpct_6m", "REAL"), ("pos_selfz_1y", "REAL"),
        ("tech_selfpct_1y", "REAL"), ("tech_selfpct_6m", "REAL"), ("tech_selfz_1y", "REAL"),
        ("opt_selfpct_1y", "REAL"), ("opt_selfpct_6m", "REAL"), ("opt_selfz_1y", "REAL"),
        ("extech_selfpct_1y", "REAL"), ("extech_selfpct_6m", "REAL"), ("extech_selfz_1y", "REAL"),
    ],
    # V1.22 — all-13F-filer institutional ownership, backs the dashboard's
    # ownership guard on the Setup tag.
    "share_float": [("inst_held_pct", "REAL")],
}


def migrate_schema(conn: sqlite3.Connection | None = None) -> list[str]:
    """Idempotently add any missing columns to existing tables. Safe to call
    every run. Returns the list of columns it added (empty if already current)."""
    own = conn is None
    if own:
        conn = connect()
    added = []
    try:
        for table, cols in _ADDED_COLUMNS.items():
            existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            if not existing:
                continue  # table not created yet; SCHEMA will build it current
            for col, sqltype in cols:
                if col not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {sqltype}")
                    added.append(f"{table}.{col}")
        if added:
            conn.commit()
    finally:
        if own:
            conn.close()
    return added


def init_schema() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        migrate_schema(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    init_schema()
    print(f"Schema initialized at {get_db_path()}")

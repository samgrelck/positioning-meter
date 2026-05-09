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

CREATE TABLE IF NOT EXISTS insider_form4 (
    accession      TEXT NOT NULL,
    ticker         TEXT NOT NULL,
    filer_cik      TEXT,
    filer_name     TEXT,
    relationship   TEXT,
    transaction_date TEXT,
    transaction_code TEXT,
    shares         REAL,
    price_per_share REAL,
    value_usd      REAL,
    direct_indirect TEXT,
    PRIMARY KEY (accession, filer_cik, transaction_date, transaction_code, shares)
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


def init_schema() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    init_schema()
    print(f"Schema initialized at {get_db_path()}")

# Positioning Meter — Usage Guide

Everything you need for daily operation, in one place.

---

## The three commands you'll actually use

```bash
# 1. Refresh dashboard from current DB (~1 min, no fresh data)
cd ~/Documents/AI\ workflows/positioning_meter && ./tools/deploy.sh

# 2. Full daily refresh: pull fresh data + recompute + push (~70 min)
cd ~/Documents/AI\ workflows/positioning_meter && ./tools/refresh_data.sh

# 3. Faster refresh — skips Yahoo estimates + options (~16 min)
cd ~/Documents/AI\ workflows/positioning_meter && ./tools/refresh_data.sh fast
```

To just open the dashboard locally (no push, no refresh):

```bash
open ~/Documents/AI\ workflows/positioning_meter/data/dashboard.html
```

After any push, GitHub Pages updates in ~30 seconds at:
**https://samgrelck.github.io/positioning-meter/**

---

## Realistic cadence guidance

You don't need to refresh everything every day. Here's the pragmatic schedule:

| Frequency | Command | Time | What gets refreshed |
|---|---|---|---|
| **Anytime** | `./tools/deploy.sh` | ~1 min | Re-render dashboard + push (no new data) |
| **Daily-ish** | `./tools/refresh_data.sh` | ~70 min | Prices, options, estimates, ETF AUM, insider Form 4 |
| **Daily-fast** | `./tools/refresh_data.sh fast` | ~16 min | Prices, ETF AUM, insider (skips slow Yahoo calls) |
| **Weekly** | Add: short volume + NASDAQ SI (see below) | +25 min | Biweekly settlement data |
| **Quarterly** | Add: 13F + Polygon financials (see below) | +30 min | Quarterly filings |

### Weekly extras (run manually about once a week)

```bash
cd ~/Documents/AI\ workflows/positioning_meter
python3 setup/04_ingest_short_volume.py   # FINRA daily — settles biweekly
python3 setup/15_ingest_options_yahoo.py  # Yahoo options chains — daily snapshot
# Biweekly SI updates (catches new FINRA files):
python3 setup/17_download_finra_si.py     # Download any new biweekly files
python3 setup/18_ingest_finra_si.py       # Parse + ingest (auto-drops pre-June-2021)
./tools/deploy.sh                          # Re-render with new data
```

### Quarterly (after each 13F filing deadline)

13Fs file 45 days after quarter-end. Mark on your calendar:

| Quarter ends | 13Fs filed by | Refresh on/after |
|---|---|---|
| Mar 31 | May 15 | mid-May |
| Jun 30 | Aug 14 | mid-Aug |
| Sep 30 | Nov 14 | mid-Nov |
| Dec 31 | Feb 14 | mid-Feb |

```bash
cd ~/Documents/AI\ workflows/positioning_meter
python3 setup/12_ingest_13f.py             # Fresh quarter's 13Fs
python3 setup/03_ingest_financials.py      # Polygon quarterly financials
./tools/deploy.sh
```

### Annually (~once a year)

| Task | Why | Command |
|---|---|---|
| Re-tune within-bucket signal weights | Backtest history grows; IC estimates improve | `python3 tools/tune_signal_weights.py` |
| Re-grid-search bucket weights | Same | `python3 tools/tune_weights.py` |
| Refresh HF curated list | New funds open, old ones close | `python3 setup/11_build_hf_list.py` |
| Refresh CUSIP→ticker map | SEC publishes new 13F securities list | `python3 setup/10_build_cusip_map.py` |
| Refresh universe | New IPOs added to theme_detector | `python3 setup/01_build_universe.py` |

After any annual retune: `python3 setup/06_compute_signals.py && ./tools/deploy.sh`

### Trigger-based (rare)

- Universe changes in theme_detector → rerun `setup/01_build_universe.py`
- Acquired Polygon Options Advanced subscription → run `setup/16_ingest_options_polygon.py`
- Found alternative pre-June-2021 SI source → would need new ingestion script

### What never needs updating
- `data/sector_groups.json` (hand-curated, edit only if changing taxonomy)
- `data/hf_filers.csv` (edit only when adding/removing HFs)
- `config.yaml` (edit only when retuning manually)
- `lib/`, `providers/` code (edit only when changing methodology)

### Honest take

If you're using this for daily decisions, **`./tools/refresh_data.sh` whenever you want a fresh view** is the right pattern. Don't sweat the weekly/quarterly extras — those signals (13F, short interest level, financials) move slowly. Missing a week of those data updates won't meaningfully change the temperature reads. The 4 quarterly 13F refreshes per year are the most important non-daily updates to actually do on schedule.

---

## What each command actually does

### `./tools/deploy.sh` (~1 min)

1. Recompute signals from current DB state (`setup/06_compute_signals.py`)
2. Re-run backtest (`setup/07_run_backtest.py`)
3. Render dashboard HTML (`setup/08_render_dashboard.py`)
4. Copy to `docs/index.html` for GitHub Pages
5. Commit + push to GitHub
6. GitHub Pages rebuilds the public site (~30 sec)

Does **not** pull any new data. Useful when you want to re-render after manually running an ingestion script, or just to push a fresh timestamp.

### `./tools/refresh_data.sh` (~70 min)

Runs the daily-cadence ingestion scripts in sequence:

1. Polygon prices (~4 min)
2. Yahoo ETF AUM snapshot (~2 min)
3. openinsider Form 4 (~10 min)
4. Yahoo options chains (~18 min) — *skipped in `fast` mode*
5. Yahoo estimates + analyst actions + earnings calendar (~35 min) — *skipped in `fast` mode*

Then calls `deploy.sh` to recompute/render/push.

Modes:
- `./tools/refresh_data.sh` — full refresh (~70 min)
- `./tools/refresh_data.sh fast` — skip slow Yahoo calls (~16 min)
- `./tools/refresh_data.sh nodeploy` — data only, no push

---

## Pandas warnings (you can ignore them)

If you ever see lines like:

```
FutureWarning: The previous implementation of stack is deprecated...
```

These are **warnings, not errors**. The script ran successfully. They're pandas notifying us that a function's default behavior will change in a future version. As of commit `abfd66a` they're silenced — you shouldn't see them anymore. If you do, the script still succeeded; the only fix is to upgrade pandas or update the syntax.

---

## Where everything lives

| File | What it's for |
|---|---|
| `data/dashboard.html` | The dashboard (open this) |
| `docs/index.html` | Copy of dashboard for GitHub Pages |
| `data/positioning.db` | All ingested data (SQLite) |
| `data/FINRA/` | Downloaded FINRA biweekly SI files (~131 files, 2018-05 → present) |
| `data/backtest_report.md` | Latest backtest IC + decile metrics |
| `data/backtest_results.json` | Same data in JSON for tools |
| `data/universe.csv` | 366-name universe with cluster IDs |
| `data/sector_groups.json` | 13 hand-curated TMT sector groups |
| `data/cusip_to_ticker.csv` | CUSIP→ticker mapping for 13F |
| `data/hf_filers.csv` | 40 curated HF filer CIKs |
| `config.yaml` | All tunable parameters (bucket weights, etc.) |
| `SUMMARY.md` | Current build state + decision history |
| `QUESTIONS.md` | Open questions + resolved decisions |
| `DESIGN.md` | Architecture decisions |
| `README.md` | Public project description |
| `USAGE.md` | **This file** |
| `GITHUB_SETUP.md` | One-time GitHub Pages setup |

---

## Editing notes + watchlist

The dashboard has UI for both, persisted to your browser's localStorage.

**To save them back to the database:** click the **💾 Export Notes/Watchlist SQL** button in the controls bar. That downloads a SQL file. Run it once with:

```bash
sqlite3 ~/Documents/AI\ workflows/positioning_meter/data/positioning.db < ~/Downloads/positioning_notes_2026-05-12.sql
```

Then run `./tools/deploy.sh` to re-render with the saved notes.

---

## Editing the watchlist via SQL directly

If you'd rather skip the browser UI:

```bash
sqlite3 ~/Documents/AI\ workflows/positioning_meter/data/positioning.db
> INSERT OR REPLACE INTO watchlist (ticker, label, added_at) VALUES ('NVDA', 'core long', date('now'));
> INSERT OR REPLACE INTO watchlist (ticker, label, added_at) VALUES ('PLTR', 'short watch', date('now'));
> .quit
```

Then `./tools/deploy.sh` to re-render.

---

## Backing up the database

Before any major change, or just for peace of mind:

```bash
cp ~/Documents/AI\ workflows/positioning_meter/data/positioning.db ~/iCloud/positioning_backup_$(date +%F).db
```

The DB has 10y of historical data that would take days to re-ingest. Worth a periodic backup.

---

## Troubleshooting

### Dashboard looks stale

Run `./tools/deploy.sh`. If still stale, prices may be a few days old — run `python3 setup/02_ingest_prices.py` then `./tools/deploy.sh`.

### `database is locked` error

Something else is holding the SQLite file. Common causes:
- A previous Python process didn't exit cleanly: `ps aux | grep python | grep ingest` to find + kill
- The DB browser is open with a write lock

### Yahoo API rate limiting

If `setup/13_ingest_estimates.py` or `setup/15_ingest_options_yahoo.py` is failing on many tickers, Yahoo may be rate-limiting. Wait an hour and retry, or run with smaller batches.

### Polygon API quota

The free Stocks tier has a 5 req/sec rate limit. The ingestion scripts respect this. If you ever upgrade tiers, the same scripts work — they just go faster.

### GitHub Pages not updating

After push, Pages takes ~30 seconds to rebuild. If it's been >2 min and the dashboard is still old:
- Check `https://github.com/samgrelck/positioning-meter/actions` for build errors
- Hard-refresh your browser (Cmd+Shift+R) to bypass cache

---

## Data licensing reminder

**Don't sign Polygon's non-professional declaration.** You don't qualify due to FINRA registration + Truist Wealth employment. Stay on yfinance forward-only for options. See `QUESTIONS.md` and `SUMMARY.md` for the full reasoning.

**Don't export FactSet data to your personal computer.** It violates Truist policy. Use FactSet at work for spot checks only.

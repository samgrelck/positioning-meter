#!/usr/bin/env python3
"""Staleness / failure alert for Positioning Meter.

Checks each data feed's freshness in positioning.db against an expected max age,
plus 13F filer-count completeness (catches the pre-deadline incomplete-ingest
trap) and dashboard render freshness. Emails a one-line-per-issue summary,
reusing the shared theme_detector SMTP creds. Silent when everything is fresh,
so it can run daily via cron without spamming.

Usage:
  python3 tools/staleness_check.py            # email only if problems found
  python3 tools/staleness_check.py --always   # always email (use to test)
"""
import os
import sys
import time
import sqlite3
import smtplib
from datetime import datetime, date
from email.mime.text import MIMEText

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import config  # noqa: E402  — loads shared .env (SMTP creds) + project paths

DB = config.project_path("data/positioning.db")
DASH = config.project_path("data/dashboard.html")
SMTP_SERVER, SMTP_PORT = "smtp.gmail.com", 587

# (label, table, date_column, max_age_days). Thresholds allow for cadence +
# publication lag (e.g. FINRA biweekly SI settles every ~2wks and publishes
# ~8-9 business days later; combined with holiday-shifted settlement dates it
# can legitimately reach ~38-40 days old before fresh data even exists, so the
# threshold is 42d to avoid false alarms during the normal dissemination lag).
FEED_CHECKS = [
    ("Composite (dashboard data)", "composite_daily",     "date",            4),
    ("Prices",                     "prices",              "date",            4),
    ("Estimates",                  "estimates_daily",     "date",            14),
    ("Short volume (FINRA daily)", "short_interest",      "settlement_date", 21),
    ("Short interest (FINRA SI)",  "short_interest_true", "settlement_date", 42),
]


def days_old(d):
    if d is None:
        return None
    try:
        dd = datetime.strptime(str(d)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return (date.today() - dd).days


def collect_issues():
    issues = []
    conn = sqlite3.connect(str(DB))
    c = conn.cursor()

    for label, table, col, max_age in FEED_CHECKS:
        try:
            mx = c.execute(f"SELECT MAX({col}) FROM {table}").fetchone()[0]
        except Exception as e:
            issues.append(f"{label}: query failed ({e})")
            continue
        age = days_old(mx)
        if age is None:
            issues.append(f"{label}: no data")
        elif age > max_age:
            issues.append(f"{label}: {age}d old (last {mx}, expected ≤{max_age}d)")

    # Per-ticker COVERAGE — catches a half-populated ingest that MAX(date) misses.
    # On 2026-06-19 a stalled price pull updated only ~163 of 386 tickers to the
    # latest date, yet MAX(date) was current, so every freshness check above passed
    # while half the universe (incl. AMZN) silently sat 4 days stale. Here we flag
    # when the latest date covers far fewer tickers than recent dates normally do.
    for label, table in [("Prices", "prices"), ("Composite", "composite_daily")]:
        try:
            latest = c.execute(f"SELECT MAX(date) FROM {table}").fetchone()[0]
            if latest is None:
                continue
            latest_n = c.execute(
                f"SELECT COUNT(DISTINCT ticker) FROM {table} WHERE date=?", (latest,)
            ).fetchone()[0]
            # Baseline = max distinct-ticker count over the last ~15 dates (full universe size).
            baseline = c.execute(
                f"""SELECT MAX(cnt) FROM (
                        SELECT COUNT(DISTINCT ticker) AS cnt FROM {table}
                        WHERE date IN (SELECT DISTINCT date FROM {table} ORDER BY date DESC LIMIT 15)
                        GROUP BY date
                    )"""
            ).fetchone()[0] or 0
            if baseline and latest_n < 0.90 * baseline:
                pct = 100 * latest_n / baseline
                issues.append(
                    f"{label} coverage: latest {latest} has only {latest_n}/{baseline} tickers "
                    f"({pct:.0f}% — likely a partial/stalled ingest; re-run setup/02_ingest_prices.py)"
                )
        except Exception as e:
            issues.append(f"{label} coverage: query failed ({e})")

    # 13F completeness — latest quarter should have a full filer set, not just
    # the handful of early filers you get if the ingest ran before the deadline.
    try:
        pe = c.execute("SELECT MAX(period_end) FROM holdings_13f").fetchone()[0]
        nf = c.execute(
            "SELECT COUNT(DISTINCT filer_cik) FROM holdings_13f WHERE period_end=?", (pe,)
        ).fetchone()[0]
        if nf < 10:
            issues.append(
                f"13F holdings: latest quarter {pe} has only {nf} filers "
                "(incomplete — re-run setup/12_ingest_13f.py after the filing deadline)"
            )
    except Exception as e:
        issues.append(f"13F holdings: query failed ({e})")

    conn.close()

    # Dashboard render freshness (data ingested but never published is still a problem)
    try:
        dash_age = (datetime.now() - datetime.fromtimestamp(DASH.stat().st_mtime)).days
        if dash_age > 4:
            issues.append(f"Dashboard render: {dash_age}d old (data/dashboard.html not refreshed)")
    except FileNotFoundError:
        issues.append("Dashboard render: data/dashboard.html missing")

    return issues


def send_email(subject, body, *, retries=3, retry_delay=15):
    user = os.environ.get("SMTP_USERNAME")
    pw = os.environ.get("SMTP_PASSWORD")
    to = os.environ.get("EMAIL_TO")
    if not (user and pw and to):
        print("SMTP creds not set in .env; skipping email.", file=sys.stderr)
        return
    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to
    # The 7:30am check often runs seconds after a scheduled wake, when the
    # network/DNS isn't up yet — that surfaced as an unhandled socket.gaierror
    # ("nodename nor servname provided") that crashed the whole check. Retry a
    # few times for transient network/SMTP errors, with a connect timeout, and
    # on final failure log cleanly instead of dumping a traceback (the issues
    # are still printed to the log above regardless of email success).
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as s:
                s.starttls()
                s.login(user, pw)
                s.send_message(msg)
            print(f"Alert emailed to {to}.")
            return
        except (smtplib.SMTPException, OSError) as e:
            last_err = e
            if attempt < retries:
                print(f"Email attempt {attempt}/{retries} failed ({e}); "
                      f"retrying in {retry_delay}s...", file=sys.stderr)
                time.sleep(retry_delay)
    print(f"Email alert FAILED after {retries} attempts (last error: {last_err}); "
          f"check above for the issue list.", file=sys.stderr)


def main():
    always = "--always" in sys.argv
    issues = collect_issues()
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    if not issues and not always:
        print(f"[{stamp}] All Positioning Meter feeds fresh — no alert sent.")
        return

    if issues:
        subject = f"⚠️ Positioning Meter: {len(issues)} stale/failed feed(s)"
        body = f"Positioning Meter staleness check — {stamp}\n\n" + "\n".join(f"  • {x}" for x in issues)
    else:
        subject = "✅ Positioning Meter: all feeds fresh"
        body = f"Positioning Meter staleness check — {stamp}\n\n  • All feeds fresh."

    print(body)
    send_email(subject, body)


if __name__ == "__main__":
    main()

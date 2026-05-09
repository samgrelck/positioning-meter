"""SEC EDGAR 13F-HR provider.

For each filer CIK:
  1. Fetch submissions index JSON (recent + paginated history files)
  2. Filter for 13F-HR forms
  3. For each filing, fetch the InfoTable XML
  4. Parse holdings (CUSIP, value, shares)

InfoTable XML format (simplified):
    <informationTable>
        <infoTable>
            <nameOfIssuer>NVIDIA CORP</nameOfIssuer>
            <titleOfClass>COM</titleOfClass>
            <cusip>67066G104</cusip>
            <value>123456</value>            <!-- in $1000s -->
            <shrsOrPrnAmt>
                <sshPrnamt>100000</sshPrnamt>
                <sshPrnamtType>SH</sshPrnamtType>
            </shrsOrPrnAmt>
            ...
        </infoTable>
    </informationTable>
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date
from xml.etree import ElementTree as ET

import requests

from lib.config import require_env

logger = logging.getLogger(__name__)


SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE_URL = "https://www.sec.gov/cgi-bin/browse-edgar"


def _headers():
    return {
        "User-Agent": require_env("SEC_EDGAR_USER_AGENT"),
        "Accept-Encoding": "gzip, deflate",
    }


class Edgar13FProvider:
    def __init__(self, rate_limit_sleep: float = 0.15):
        self._sleep = rate_limit_sleep
        self._session = requests.Session()
        self._session.headers.update(_headers())

    def list_filings(self, cik: str) -> list[dict]:
        """Return list of 13F-HR filings for the given filer CIK.

        Each row: {accession, filing_date, period_end, primary_doc, form_type}
        """
        cik_padded = str(int(cik)).zfill(10)
        url = SUBMISSIONS_URL.format(cik=cik_padded)
        try:
            r = self._session.get(url, timeout=20)
            r.raise_for_status()
            d = r.json()
        except Exception as e:
            logger.warning(f"submissions fetch failed for CIK {cik}: {e}")
            return []
        finally:
            time.sleep(self._sleep)

        filings = []
        # Recent submissions (latest 1000 filings)
        recent = d.get("filings", {}).get("recent", {})
        accessions = recent.get("accessionNumber", [])
        forms = recent.get("form", [])
        filing_dates = recent.get("filingDate", [])
        report_dates = recent.get("reportDate", [])
        primary_docs = recent.get("primaryDocument", [])
        for i, form in enumerate(forms):
            if form != "13F-HR":
                continue
            filings.append({
                "accession": accessions[i],
                "filing_date": filing_dates[i],
                "period_end": report_dates[i] if i < len(report_dates) else None,
                "primary_doc": primary_docs[i] if i < len(primary_docs) else None,
                "form_type": form,
            })

        # Older filings paginated
        for ext in d.get("filings", {}).get("files", []):
            ext_url = f"https://data.sec.gov/submissions/{ext['name']}"
            try:
                r2 = self._session.get(ext_url, timeout=20)
                r2.raise_for_status()
                d2 = r2.json()
            except Exception as e:
                logger.warning(f"submissions ext fetch failed: {e}")
                continue
            finally:
                time.sleep(self._sleep)
            accessions = d2.get("accessionNumber", [])
            forms = d2.get("form", [])
            filing_dates = d2.get("filingDate", [])
            report_dates = d2.get("reportDate", [])
            primary_docs = d2.get("primaryDocument", [])
            for i, form in enumerate(forms):
                if form != "13F-HR":
                    continue
                filings.append({
                    "accession": accessions[i],
                    "filing_date": filing_dates[i],
                    "period_end": report_dates[i] if i < len(report_dates) else None,
                    "primary_doc": primary_docs[i] if i < len(primary_docs) else None,
                    "form_type": form,
                })

        return filings

    def fetch_holdings(self, cik: str, accession: str, filing_date: str | None = None) -> list[dict]:
        """Fetch and parse InfoTable for one filing.

        Returns list of holding dicts with keys: cusip, name_of_issuer,
        title_of_class, value_usd, shares.
        """
        # Locate the InfoTable XML. SEC's archive URL pattern:
        # https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_no_dashes}/{accession}-index.htm
        cik_int = str(int(cik))
        acc_clean = accession.replace("-", "")
        index_url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_clean}/"
        try:
            r = self._session.get(index_url + "index.json", timeout=20)
            r.raise_for_status()
            idx = r.json()
        except Exception as e:
            logger.warning(f"index fetch failed for {cik}/{accession}: {e}")
            return []
        finally:
            time.sleep(self._sleep)

        # Find an XML that looks like the InfoTable (often "infotable.xml" or similar)
        items = idx.get("directory", {}).get("item", [])
        infotable_url = None
        for item in items:
            name = item.get("name", "")
            if name.lower().endswith(".xml") and (
                "infotable" in name.lower()
                or "informationtable" in name.lower()
                or re.search(r"primary_doc.*\.xml", name, re.IGNORECASE) is None
            ):
                # Heuristic: prefer files with 'info' in name; otherwise pick
                # any xml that's NOT primary_doc.xml (which is the cover page)
                if "primary_doc" not in name.lower():
                    infotable_url = index_url + name
                    break
        if not infotable_url:
            # Fallback: find any xml that's not primary_doc
            for item in items:
                name = item.get("name", "")
                if name.lower().endswith(".xml") and "primary_doc" not in name.lower():
                    infotable_url = index_url + name
                    break
        if not infotable_url:
            return []

        try:
            r = self._session.get(infotable_url, timeout=30)
            r.raise_for_status()
            xml = r.text
        except Exception as e:
            logger.warning(f"infotable fetch failed for {accession}: {e}")
            return []
        finally:
            time.sleep(self._sleep)

        # SEC changed 13F value units from $thousands to actual $ effective
        # filings on/after 2023-01-03. Use filing date to pick multiplier.
        value_multiplier = 1.0
        if filing_date and filing_date < "2023-01-03":
            value_multiplier = 1000.0
        return self._parse_infotable(xml, value_multiplier)

    @staticmethod
    def _parse_infotable(xml: str, value_multiplier: float = 1.0) -> list[dict]:
        # Strip default namespace if present (makes ElementTree happier)
        xml = re.sub(r'\sxmlns="[^"]+"', "", xml, count=1)
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as e:
            logger.warning(f"InfoTable parse error: {e}")
            return []

        rows = []
        for it in root.findall(".//infoTable"):
            try:
                cusip = (it.findtext("cusip") or "").strip()
                name = (it.findtext("nameOfIssuer") or "").strip()
                cls = (it.findtext("titleOfClass") or "").strip()
                val = it.findtext("value")
                shares_el = it.find(".//sshPrnamt")
                shares_type_el = it.find(".//sshPrnamtType")
                shares = float(shares_el.text) if (shares_el is not None and shares_el.text) else None
                shares_type = shares_type_el.text if shares_type_el is not None else "SH"
                # Skip non-share holdings (PRN = principal amount of debt)
                if shares_type != "SH":
                    continue
                value_usd = float(val) * value_multiplier if val else None
                if not cusip:
                    continue
                rows.append({
                    "cusip": cusip,
                    "name_of_issuer": name,
                    "title_of_class": cls,
                    "shares": shares,
                    "value_usd": value_usd,
                })
            except (ValueError, AttributeError) as e:
                continue
        return rows

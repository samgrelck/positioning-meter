"""Peer-group lookup using theme_detector's curated TMT clusters.

Each ticker maps to one cluster ID. Cross-sectional percentile ranks are
computed within the ticker's cluster on a given date.

Outliers (named explicitly in cluster JSON) and unmapped tickers fall back
to pct_self only — pct_peer returns None for them.
"""
import json
from functools import lru_cache
from .config import load, project_path


@lru_cache(maxsize=1)
def load_clusters() -> dict:
    cfg = load()
    path = project_path(cfg["clusters"]["source_json"])
    with open(path) as f:
        return json.load(f)


@lru_cache(maxsize=1)
def ticker_to_cluster() -> dict[str, str]:
    """Map ticker -> cluster_id, excluding outliers."""
    clusters = load_clusters()
    mapping: dict[str, str] = {}
    for cluster_id, info in clusters.items():
        outliers = set(info.get("outliers", []))
        members = info.get("members") or info.get("tickers") or []
        for t in members:
            if t in outliers:
                continue
            # First cluster wins if a ticker appears in multiple
            mapping.setdefault(t, cluster_id)
    return mapping


def peers_of(ticker: str) -> list[str]:
    """Return list of peer tickers (same cluster, excluding self).

    Returns empty list if ticker is unmapped.
    """
    mapping = ticker_to_cluster()
    cid = mapping.get(ticker)
    if not cid:
        return []
    return [t for t, c in mapping.items() if c == cid and t != ticker]

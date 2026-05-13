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
def ticker_to_clusters() -> dict[str, list[str]]:
    """Map ticker -> list of cluster_ids (a ticker can belong to multiple
    clusters, e.g. AMD is both a CPU and a GPU/AI-semi name)."""
    clusters = load_clusters()
    memberships: dict[str, list[str]] = {}
    for cluster_id, info in clusters.items():
        outliers = set(info.get("outliers", []))
        members = info.get("members") or info.get("tickers") or []
        for t in members:
            if t in outliers:
                continue
            memberships.setdefault(t, []).append(cluster_id)
    return memberships


@lru_cache(maxsize=1)
def ticker_to_cluster() -> dict[str, str]:
    """Map ticker -> single representative cluster (used for dashboard
    drilldown 'cluster mates' display).

    Priority when in multiple clusters:
      1. Curated clusters (curated_*) over auto-generated (cluster_NN)
      2. Within same priority class, larger cluster wins (more peer-specific
         when the curated taxonomy is intentional, e.g. AMD belongs to
         curated_ai_semiconductors which has 13 members vs curated_cpus 4)
    """
    clusters = load_clusters()
    memberships = ticker_to_clusters()

    def cluster_size(cid):
        info = clusters.get(cid, {})
        members = info.get("members") or info.get("tickers") or []
        return len(members)

    def priority(cid):
        is_curated = cid.startswith("curated_")
        # Negative size so min picks LARGER curated cluster
        return (0 if is_curated else 1, -cluster_size(cid))

    mapping: dict[str, str] = {}
    for t, cids in memberships.items():
        mapping[t] = min(cids, key=priority)
    return mapping


@lru_cache(maxsize=1)
def cluster_members() -> dict[str, list[str]]:
    """Map cluster_id -> list of member tickers (excluding outliers)."""
    clusters = load_clusters()
    out: dict[str, list[str]] = {}
    for cluster_id, info in clusters.items():
        outliers = set(info.get("outliers", []))
        members = info.get("members") or info.get("tickers") or []
        out[cluster_id] = [t for t in members if t not in outliers]
    return out


def peer_set(ticker: str) -> set[str]:
    """Union of all cluster members across all clusters this ticker belongs to.
    Used for percentile-peer ranking — gives a richer peer set than a single
    cluster, especially for cross-category names like AMD (CPU + GPU + AI semi).
    """
    cids = ticker_to_clusters().get(ticker, [])
    cmems = cluster_members()
    peers: set[str] = set()
    for cid in cids:
        peers.update(cmems.get(cid, []))
    return peers


def peers_of(ticker: str) -> list[str]:
    """Return list of peer tickers (same cluster, excluding self).

    Returns empty list if ticker is unmapped.
    """
    mapping = ticker_to_cluster()
    cid = mapping.get(ticker)
    if not cid:
        return []
    return [t for t, c in mapping.items() if c == cid and t != ticker]

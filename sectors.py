"""Sector taxonomy for the rollover screen.

REUSES the curated 23-sector taxonomy from `nifty-heatmap-core` (FNO_SECTORS)
rather than inventing a second one that would drift from it.

It is FETCHED at runtime, not vendored. A vendored snapshot is a second copy,
and this project's own history is a catalogue of two-copies-drifting bugs --
including the one that created nifty-heatmap-core in the first place. The cache
is a fallback for no-network, never the primary.

Two adaptations, both deliberate:
  * tickers normalised (board uses Yahoo `ABB.NS`, bhavcopy uses `ABB`)
  * CASH_ONLY names dropped -- no futures, so no rollover

MIN_PEERS exists because a "sector average" over one member IS that member:
the deviation is exactly 0.00, which LOOKS like data. Groups under the floor
get NO sector baseline and are reported as such, never silently averaged.
"""
import ast, ssl, urllib.request
from pathlib import Path

MIN_PEERS = 5
SRC = ("https://raw.githubusercontent.com/sectorchakra/"
       "nifty-heatmap-core/main/nifty_heatmap_core/__init__.py")
_CACHE = Path(__file__).resolve().parent / "data" / "heatmap_core_cache.py"


_MEMO = {}


def _load():
    # memoised: viable_sectors() calls sector_map() per sector per expiry, and
    # without this a 10-window forward test made ~10 network round-trips.
    if "t" in _MEMO:
        return _MEMO["t"]
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
    try:
        req = urllib.request.Request(SRC, headers={"User-Agent": "rollover-screen"})
        txt = urllib.request.urlopen(req, timeout=25, context=ctx).read().decode("utf-8")
        _CACHE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE.write_text(txt)
    except Exception as e:
        if not _CACHE.exists():
            raise RuntimeError(f"taxonomy unavailable and no cache: {e}") from e
        print(f"  [sectors] live fetch failed ({type(e).__name__}); using cache")
    _MEMO["t"] = _extract(_CACHE.read_text())
    return _MEMO["t"]


def _extract(src):
    """Pull FNO_SECTORS / CASH_ONLY out WITHOUT executing the module.

    Executing it would drag in the heatmap's own runtime dependencies (it
    imports `requests` for Yahoo) which we neither need nor should require --
    found when CI failed on ModuleNotFoundError. Parsing the literals keeps us
    immune to whatever that module imports next.
    """
    want = {"FNO_SECTORS", "CASH_ONLY"}
    out = {}
    for node in ast.parse(src).body:
        if not isinstance(node, ast.Assign):
            continue
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id in want:
                v = node.value
                # CASH_ONLY is frozenset({...}) -- unwrap the call, keep the literal
                if isinstance(v, ast.Call) and isinstance(v.func, ast.Name) \
                        and v.func.id in ("frozenset", "set") and v.args:
                    v = v.args[0]
                out[t.id] = ast.literal_eval(v)
    missing = want - set(out)
    if missing:
        raise RuntimeError(f"taxonomy missing {missing} -- upstream shape changed")
    return type("T", (), out)


# NSE symbol changes not yet reflected in nifty-heatmap-core (same ISIN, new ticker).
# The heatmap list is curated upstream; map old -> current NSE symbol here so the F&O
# data (bhavcopy) and NSE's own industry list line up. Remove an entry once upstream changes.
NSE_RENAMES = {
    "ICICIPRULI": "ICICILIFE",   # ICICI Prudential Life -> ICICI Life Insurance, from 2026-10-23 (INE726G01019)
}


def _norm(t):
    t = t[:-3] if t.endswith(".NS") else t
    return NSE_RENAMES.get(t, t)


def sector_map():
    """{symbol: sector} for F&O-tradable names only."""
    m = _load()
    cash = {_norm(s) for s in (getattr(m, "CASH_ONLY", []) or [])}
    return {_norm(t): sec for sec, members in m.FNO_SECTORS.items()
            for t in members if _norm(t) not in cash}


def viable_sectors(symbols):
    """Sectors with >= MIN_PEERS members among `symbols`."""
    sm, n = sector_map(), {}
    for s in symbols:
        if s in sm:
            n[sm[s]] = n.get(sm[s], 0) + 1
    return {k for k, v in n.items() if v >= MIN_PEERS}

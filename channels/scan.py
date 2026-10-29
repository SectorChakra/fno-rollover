#!/usr/bin/env python3
"""Channel watchlist: which stocks are moving inside a price channel right now.

Information only. HR register items 93/93b backtested trading the BREAK of these channels on 2022-26 data, loose and
strict, same-day and 5-day, every slope and direction: 0 of 24 versions made money after costs. The page says so.

Data: NSE's own cash-market bhavcopy on nsearchives.nseindia.com (the archive this repo already reads for F&O), one file
per session, completed sessions only. Prices are as traded (not adjusted), so a split or bonus inside the window shows
up as a gap and usually just fails the width test for that stock until it rolls out.

Universe: NSE rank 1-750 (the 44-EMA board's universe.json, fetched, never copied) plus every F&O stock (sectors.py).

A channel, fitted on the last N completed daily candles:
  line     least-squares line through the closes; the upper / lower lines are that line shifted to the window's highest
           high / lowest low, then extended one session ahead (the levels for the next session, known before it opens)
  STRICT   N 30, >= 3 highs within 10% of the width of the upper line and >= 3 lows within 10% of the lower line,
           width <= 8% of price, and a sloped channel's closes fit the line with R^2 >= 0.6        (item 93b)
  LOOSE    N 20, >= 2 touches per line, width <= 10%; only for stocks that fail STRICT              (item 93)
  slope    FLAT if the line moves less than 0.10% of price a day, else RISING / FALLING
Writes data/channels.json. Run: python channels/scan.py
"""
from __future__ import annotations

import csv, io, json, ssl, sys, urllib.error, urllib.request, zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import certifi
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import sectors                                                     # noqa: E402

CACHE = ROOT / "data" / "bhav_cm"
OUT = ROOT / "data" / "channels.json"
URL = "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{d}_F_0000.csv.zip"
UNIVERSE_URL = "https://raw.githubusercontent.com/abhijeetbishayee-drb/nifty-ema-board/main/data/universe.json"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
CTX = ssl.create_default_context(cafile=certifi.where())   # this interpreter has no usable default CA bundle (see backfill.py)
IST = timezone(timedelta(hours=5, minutes=30))
STRICT = dict(n=30, max_w=0.08, touch=3, r2_min=0.6)
LOOSE = dict(n=20, max_w=0.10, touch=2, r2_min=None)
FLAT = 0.10
SERIES = ("EQ", "BE", "BZ")      # BE/BZ = trade-for-trade; a stock can move between series, EQ wins on a tie


def fetch(d: date):
    """{symbol: (open, high, low, close)} for one session, or None (holiday / not published yet)."""
    tag = d.strftime("%Y%m%d"); cached = CACHE / f"{tag}.json"
    if cached.exists():
        return json.loads(cached.read_text()) or None
    req = urllib.request.Request(URL.format(d=tag), headers={"User-Agent": UA, "Referer": "https://www.nseindia.com/", "Accept": "*/*"})
    try:
        raw = urllib.request.urlopen(req, timeout=30, context=CTX).read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None                # holiday, weekend, or today's file not out yet; never cached, so it is retried
        raise                          # anything else is a real fault
    z = zipfile.ZipFile(io.BytesIO(raw))
    out, rank = {}, {s: i for i, s in enumerate(SERIES)}
    for r in csv.DictReader(io.TextIOWrapper(z.open(z.namelist()[0]))):
        s = r["SctySrs"]
        if s not in rank: continue
        sym = r["TckrSymb"]
        if sym in out and rank[out[sym][4]] <= rank[s]: continue
        out[sym] = (float(r["OpnPric"]), float(r["HghPric"]), float(r["LwPric"]), float(r["ClsPric"]), s)
    out = {k: v[:4] for k, v in out.items()}
    CACHE.mkdir(parents=True, exist_ok=True); cached.write_text(json.dumps(out))
    return out


def sessions(need: int):
    """The last `need` completed sessions, newest last. Today counts only once its file is published."""
    today, got, d = datetime.now(IST).date(), [], datetime.now(IST).date()
    while len(got) < need and (today - d).days < 120:
        if d.weekday() < 5:
            b = fetch(d)
            if b: got.append((d, b))
        d -= timedelta(days=1)
    if len(got) < need:
        raise SystemExit(f"only {len(got)} sessions found in 120 days, need {need}")
    return got[::-1]


def fit(bars, n, max_w, touch, r2_min):
    w = bars[-n:]
    C = np.array([b[3] for b in w]); H = np.array([b[1] for b in w]); L = np.array([b[2] for b in w])
    x = np.arange(n); xm = x.mean()
    b_ = ((x - xm) * (C - C.mean())).sum() / ((x - xm) ** 2).sum(); a_ = C.mean() - b_ * xm; line = a_ + b_ * x
    up, lo = (H - line).max(), (L - line).min(); width = up - lo; px = C[-1]
    if width <= 0 or width / px > max_w: return None
    tu, tl = int(((H - line) >= up - 0.1 * width).sum()), int(((L - line) <= lo + 0.1 * width).sum())
    if tu < touch or tl < touch: return None
    slope = 100 * b_ / px
    r2 = 1 - ((C - line) ** 2).sum() / max(((C - C.mean()) ** 2).sum(), 1e-12)
    if r2_min is not None and abs(slope) >= FLAT and r2 < r2_min: return None
    nxt = a_ + b_ * n; upper, lower = nxt + up, nxt + lo
    return dict(days=n, slope_class="FLAT" if abs(slope) < FLAT else ("RISING" if slope > 0 else "FALLING"),
                slope_pct_day=round(slope, 3), close=round(float(px), 2), next_upper=round(float(upper), 2),
                next_lower=round(float(lower), 2), width_pct=round(100 * width / px, 2), touches_upper=tu, touches_lower=tl,
                r2=round(float(r2), 2), position=round(float((px - (line[-1] + lo)) / width), 2),
                dist_upper_pct=round(100 * (upper / px - 1), 2), dist_lower_pct=round(100 * (lower / px - 1), 2))


def universe():
    fno = set(sectors.sector_map())
    req = urllib.request.Request(UNIVERSE_URL, headers={"User-Agent": "fno-rollover-channels"})
    u = json.loads(urllib.request.urlopen(req, timeout=25, context=CTX).read())
    wide = {s if isinstance(s, str) else (s.get("symbol") or s.get("sym") or s.get("s")) for s in u.get("stocks", [])}
    return fno, {s for s in wide if s} | fno


def main():
    days = sessions(STRICT["n"])
    fno, uni = universe()
    out, short = [], 0
    for sym in sorted(uni):
        bars = [b[sym] for _, b in days if sym in b]
        if len(bars) < LOOSE["n"]: short += 1; continue
        for tier, rule in (("STRICT", STRICT), ("LOOSE", LOOSE)):
            if len(bars) < rule["n"]: continue
            rec = fit(bars, **rule)
            if rec:
                out.append(dict(symbol=sym, tier=tier, fno=sym in fno, since=days[-rule["n"]][0].isoformat(), **rec)); break
    out.sort(key=lambda r: (r["tier"] != "STRICT", r["slope_class"], r["symbol"]))
    doc = dict(as_of=days[-1][0].isoformat(), generated=datetime.now(IST).isoformat(timespec="minutes"),
               scanned=len(uni), fno_count=len(fno), too_little_history=short, source="NSE CM bhavcopy (nsearchives)",
               rules=dict(strict=STRICT, loose=LOOSE, flat_pct_day=FLAT), channels=out)
    OUT.write_text(json.dumps(doc, indent=1))
    print(f"{doc['as_of']}: {len(out)} channels ({sum(r['tier'] == 'STRICT' for r in out)} strict) "
          f"from {len(uni)} stocks; {short} with too little history")


if __name__ == "__main__":
    main()

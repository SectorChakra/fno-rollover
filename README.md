# F&O rollover screen

Screens the NSE stock-futures universe (210 names) for positioning that agrees
or disagrees with price.

## The three steps

1. **MOM gain** — price momentum
2. **Rollover** — were positions carried into the next series
3. **Cost gain/decline** — did carrying them get more or less expensive

A name that rose, rolled above its norm, *and* at rising cost has longs paying
up to stay. One that rose while rollover collapsed has longs leaving into
strength. The disagreements are the signal; agreement is just trend confirmation.

## The three baselines

Each step is measured against: the **previous month**, the stock's **own
trailing average**, and its **sector average**.

## Data

NSE F&O bhavcopy (`OpnIntrst`, `UndrlygPric`, `ClsPric` per contract per
series). Public, historical, no auth, no broker dependency.

**Rollover formula**, validated to two decimals on 9/9 symbols against an
independently published rollover sheet for 2026-08-25:

    rollover % = (next + far OI) / (near + next + far OI)

`next / (near + next)` is *close* and wrong — it misses by up to 1.0pp
(POWERINDIA 91.35 vs 92.32). It fails quietly, which is worse.

## Why MOM is measured expiry-to-expiry

Deliberate, and checked. Against a published sheet for 2026-08-25, three
candidate windows were compared on six symbols:

| window | closest on |
|---|---|
| expiry -> expiry | **5 of 6** |
| calendar month-end | 1 of 6 |

Neither reproduces the sheet exactly, so the sheet uses something else again
(futures rather than spot, a vendor feed, or hand entry). We are not cloning
it. Expiry-to-expiry is kept because it is both the closer match AND the more
defensible definition: it aligns the price change with exactly the period whose
rollover is being measured.

**Corporate actions ruled out as the cause** (2026-09-26). The two largest
divergences from the sheet, DIXON and SIEMENS, were checked against
`NewBrdLotQty` across 26 bhavcopy files: DIXON's lot is constant at 50 with no
price discontinuity, and SIEMENS' 125 -> 175 lot change in Jan 2026 came with
the price essentially flat (-1.6%), which is NSE's routine lot revision to keep
contract value in band, not a split. A split moves price inversely to lot.
So the screen is not reading split-adjusted prices as real moves.

## Sectors

Reuses `FNO_SECTORS` from
[`nifty-heatmap-core`](https://github.com/sectorchakra/nifty-heatmap-core),
**fetched at runtime, never vendored** — a second copy would drift. Sectors with
fewer than 5 F&O members get no sector baseline: an average over one member is
that member, and the resulting 0.00 deviation looks like data.

## Parity with the heatmap board

`parity_check.py` asserts, re-runnably, that sector plotting here matches
[the heatmap board](https://github.com/sectorchakra/nifty-heatmap-web):
labels, per-name membership, cash-only exclusion, and equal-weighted
aggregation. It runs in CI before every capture, because the taxonomy is
fetched at runtime and a change upstream would otherwise land here silently.

Two divergences are STRUCTURAL and declared in the test itself. An
**undeclared** divergence is what fails:

| | heatmap | here | why |
|---|---|---|---|
| cash-only names | plotted (dashed tile) | excluded | no futures, so no OI/rollover/cost exists |
| small sectors | all 23 plotted | baseline suppressed under 5 F&O members | they display breadth; we score against it, and a deviation from a group of one is 0.00 and reads as data |

## Files

| | |
|---|---|
| `backfill.py` | historical expiries. Expiry dates are **derived** from each bhavcopy's own ladder, never assumed — the Thursday→Tuesday convention change would break a hardcoded rule |
| `update.py` | weekly snapshot, idempotent |
| `sectors.py` | taxonomy adapter |
| `analyse.py` | the screen |

## Channel watchlist (`channels.html`)

A separate page listing the stocks whose recent daily candles sit inside a price channel — a best-fit line through
the closes with upper/lower lines at the window's extreme high/low, extended one session ahead. **Strict**: 30 days,
≥ 3 touches per line, width ≤ 8%, R² ≥ 0.6 for a sloped channel; **loose**: 20 days, ≥ 2 touches, width ≤ 10%.
Universe: NSE rank 1-750 (the 44-EMA board's `universe.json`) plus every F&O stock. Data: NSE's cash-market
bhavcopy (`channels/scan.py` → `data/channels.json`), refreshed by `.github/workflows/channels.yml` every weekday
evening. **Information only** — trading the break of these channels was backtested (HR register items 93/93b) and
lost after costs in all 24 versions.

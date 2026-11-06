"""Parity test: this repo's sector plotting vs the heatmap board's.

Exists because of the 2026-09-06 Android incident -- "at parity" was declared
after a partial port and the user found the gap in testing. The lesson recorded
then was: diff explicitly against a checklist, never infer. So this is a test,
re-runnable, not a one-off eyeball.

Divergences are not automatically failures. Some are STRUCTURAL and justified.
They must be DECLARED here, so an undeclared one is what fails.
"""
import csv, glob, json, statistics as st, sys
from pathlib import Path
import sectors as ours
import nse_industry

# Module-level so test_parity_negative.py can point check [5] at a mutated copy.
SHEET = Path(__file__).resolve().parent / "sheet_data.json"

# Our sectors that intentionally cut across NSE's industries. The VALUE is the
# full set of NSE industries a sector is allowed to contain -- not a blanket
# exemption. A new industry appearing inside a declared sector still FAILS,
# which is what keeps the declaration from becoming a licence.
DECLARED_NSE = {
    "Defence":        {"Capital Goods", "Chemicals"},
    # "Services" is here for DELHIVERY (moved into New Age Stocks 2026-10-07).
    # NSE files it under Services with the ports and airports, which is right
    # about what it does and wrong about what it trades like; the board groups
    # it with the loss-making listed-since-2021 platform names it moves with.
    # A deliberate divergence, declared rather than silently allowed.
    "New Age Stocks": {"Consumer Services", "Financial Services", "Services"},
}

DECLARED = {
    "cash_only": "heatmap PLOTS cash-only names (dashed tile); we exclude them — "
                 "they have no futures, so no OI/rollover/cost exists to screen",
    "fin_split": "NSE has ONE 'Financial Services' industry; the board splits it three "
                 "ways into Banks / NBFCs / Financial Services. A per-sector purity test "
                 "cannot see this (each of the three is internally pure), so it is recorded "
                 "here rather than left to look like agreement",
    "min_peers": f"heatmap plots ALL 23 sectors; we suppress the sector BASELINE "
                 f"below {ours.MIN_PEERS} F&O members — a deviation from a group "
                 f"of one is 0.00 and reads as data. Different use of the same "
                 f"aggregate: they display breadth, we score against it",
}

def heatmap_core():
    """Same parse-don't-execute path sectors.py uses -- the heatmap module
    imports `requests`, which we must not require just to read two dicts."""
    ours.sector_map()                      # refreshes the cache
    from pathlib import Path
    return ours._extract(
        (Path(__file__).resolve().parent / "data" / "heatmap_core_cache.py").read_text())

def main():
    hm = heatmap_core()
    norm = ours._norm                      # strips .NS AND applies sectors.NSE_RENAMES (same view as ours)
    hm_sec = {norm(t): s for s, v in hm.FNO_SECTORS.items() for t in v}
    cash = {norm(t) for t in (getattr(hm, "CASH_ONLY", []) or [])}
    mine = ours.sector_map()
    fails, skipped = [], []

    # 1. sector LABELS identical
    if set(hm.FNO_SECTORS) != set(v for v in mine.values()) | {
            s for s, v in hm.FNO_SECTORS.items() if all(norm(t) in cash for t in v)}:
        extra = set(mine.values()) - set(hm.FNO_SECTORS)
        if extra:
            fails.append(f"sector labels we invented: {extra}")
    print(f"[1] sector labels      : ours {len(set(mine.values()))} ⊆ heatmap {len(hm.FNO_SECTORS)}"
          f"  {'OK' if not (set(mine.values()) - set(hm.FNO_SECTORS)) else 'FAIL'}")

    # 2. every F&O name we map lands in the SAME sector as the board
    bad = {s: (mine[s], hm_sec.get(s)) for s in mine if s in hm_sec and mine[s] != hm_sec[s]}
    if bad: fails.append(f"membership disagrees: {bad}")
    print(f"[2] membership         : {len(mine)} names, {len(bad)} disagree  "
          f"{'OK' if not bad else 'FAIL'}")

    # 3. names we map that the board does not know at all. sector_map() derives
    # our map FROM FNO_SECTORS, so this is structurally impossible -- which is
    # exactly why it must fail rather than print REVIEW: if it ever fires, the
    # derivation in sectors.py has broken, and an advisory line would let that
    # through the weekly gate unnoticed.
    unknown = sorted(set(mine) - set(hm_sec))
    if unknown: fails.append(f"names we map that the board does not know: {unknown}")
    print(f"[3] names not on board : {unknown if unknown else 'none'}  "
          f"{'OK' if not unknown else 'FAIL'}")

    # 4. cash-only exclusion is total (declared divergence, but must be clean)
    leaked = sorted(set(mine) & cash)
    if leaked: fails.append(f"cash-only leaked into our map: {leaked}")
    print(f"[4] cash-only excluded : {len(cash)} on board, {len(leaked)} leaked  "
          f"{'OK' if not leaked else 'FAIL'}")

    # 5. aggregation method matches: equal-weighted mean over members with data.
    # This used to grep the source for the string "st.mean", which is not a test
    # of anything -- it passed on a comment and broke the moment the averaging
    # moved file (2026-09-27, when analyse.py stopped duplicating screen.py).
    # Now it checks the PUBLISHED sector aggregate against an independently
    # recomputed equal-weighted mean, which an OI- or cap-weighted change fails.
    worst, checked = 0.0, 0
    try:
        doc = json.loads(SHEET.read_text())
    except FileNotFoundError:
        doc = None
    if doc is None:
        print("[5] equal-weighted mean: SKIP — sheet_data.json not built yet")
    else:
        for sec in doc["sectors"]:
            rolls = [r["rollover"] for r in sec["rows"] if r.get("rollover") is not None]
            costs = [r["rollover_cost"] for r in sec["rows"] if r.get("rollover_cost") is not None]
            if not rolls or not costs:
                continue
            worst = max(worst, abs(st.mean(rolls) - sec["avgRoll"]),
                        abs(st.mean(costs) - sec["avgCost"]))
            checked += 1
        ew = worst <= 0.005                     # published values are rounded to 2-3dp
        print(f"[5] equal-weighted mean: {'OK — matches build_sectors' if ew else 'FAIL'}"
              f"  ({checked} sectors, worst deviation {worst:.4f})")
        if not ew:
            fails.append(f"sector aggregate is not an equal-weighted mean "
                         f"(worst deviation {worst:.4f})")

    # 6. THE ONLY INDEPENDENT CHECK. [1]-[4] compare our map against the board it
    # was derived from, so they pass by construction. NSE publishes its own
    # industry classification with no causal link to the heatmap, so a
    # disagreement here is real information rather than a tautology.
    nse = nse_industry.industry_map()
    if not nse:
        skipped.append("[6] NSE industry cross-check — source unreachable and no cache")
        print("[6] NSE industry      : SKIP — NSE unreachable and no cache")
    else:
        gaps = sorted(s for s in mine if s not in nse)
        if gaps:
            fails.append(f"F&O names absent from NSE's own list (renamed/delisted?): {gaps}")
        spread = {}
        for sym, sec in mine.items():
            if sym in nse:
                spread.setdefault(sec, {}).setdefault(nse[sym], []).append(sym)
        offenders = []
        for sec, inds in sorted(spread.items()):
            allowed = DECLARED_NSE.get(sec)
            if allowed is not None:
                extra = set(inds) - allowed
                if extra:
                    offenders += [f"{s} ({sec} declared, but NSE says {i})"
                                  for i in sorted(extra) for s in sorted(inds[i])]
                continue
            if len(inds) > 1:
                main = max(inds, key=lambda i: len(inds[i]))
                offenders += [f"{s} ({sec} is otherwise all {main}, but NSE says {i})"
                              for i in sorted(inds) if i != main for s in sorted(inds[i])]
        if offenders:
            fails.append("sector contradicts NSE's own industry: " + "; ".join(offenders))
        pure = sum(1 for sec, inds in spread.items()
                   if len(inds) == 1 and sec not in DECLARED_NSE)
        print(f"[6] NSE industry      : {len(mine) - len(gaps)}/{len(mine)} names matched, "
              f"{pure}/{len(spread)} sectors pure, {len(DECLARED_NSE)} declared cross-cuts, "
              f"{len(offenders)} contradictions  "
              f"{'OK' if not (gaps or offenders) else 'FAIL'}")

    print("\nDECLARED structural divergences (intentional):")
    for k, v in DECLARED.items():
        print(f"  * {k}: {v}")

    if skipped:
        print("\nNOT RUN (absence of a result is not a pass):")
        for k in skipped:
            print(f"  ? {k}")
    tail = f" ({len(skipped)} check not run)" if skipped else ""
    print("\n" + (f"PARITY OK{tail}" if not fails
                  else "PARITY FAILED:\n  " + "\n  ".join(fails)))
    return 1 if fails else 0

if __name__ == "__main__":
    sys.exit(main())

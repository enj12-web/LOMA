#!/usr/bin/env python3
"""Fetch ESPN PGA leaderboard, compute team standings, write standings.json.

Scoring rule: best 4 of 6 made-cut scores per team. If <4 made cut, team is DQ'd.
A player is "made cut" if they have linescores for all tournament rounds.
"""
import json
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/golf/pga/scoreboard"
ROOT = Path(__file__).parent

# Per-major cut rule ("low N and ties"). Fallback when picks.json omits cut_low_n
# — a missing field must NOT silently default to the wrong major's cut.
CUT_LOW_N_BY_EVENT = {
    "masters tournament": 50,
    "pga championship": 70,
    "u.s. open": 60,
    "the open": 70,
}


def normalize(name: str) -> str:
    # Strip accents (Åberg -> Aberg, Niemann unchanged, García -> Garcia)
    s = unicodedata.normalize("NFKD", name)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"[.\'`\"]", "", s)
    s = re.sub(r"[-_/]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def fetch_scoreboard():
    req = urllib.request.Request(ESPN_URL, headers={"User-Agent": "golf-pool/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def parse_score(s):
    if s is None:
        return None
    s = str(s).strip()
    if s in ("E", "0", ""):
        return 0
    try:
        return int(s.replace("+", ""))
    except ValueError:
        return None


def find_event(data, target_name):
    target = normalize(target_name)
    for ev in data.get("events", []):
        if normalize(ev.get("name", "")) == target:
            return ev
        if normalize(ev.get("shortName", "")) == target:
            return ev
    return None


def thirty_six_hole_total(competitor):
    """Sum of round 1 + round 2 to-par for a competitor, or None if either round
    is missing (WD/DQ players never complete 36 holes). Used to determine the cut."""
    by_period = {ls.get("period"): ls for ls in (competitor.get("linescores") or [])}
    r1 = parse_score(by_period.get(1, {}).get("displayValue"))
    r2 = parse_score(by_period.get(2, {}).get("displayValue"))
    if r1 is None or r2 is None:
        return None
    return r1 + r2


def compute_cut_line(competitors, cut_low_n):
    """Cut line = the 36-hole to-par of the cut_low_n-th best player ('low N and
    ties'). Everyone whose 36-hole total is <= this made the cut. Returns None if
    the field is too small to have a cut."""
    totals = sorted(
        t for t in (thirty_six_hole_total(c) for c in competitors) if t is not None
    )
    if not totals:
        return None
    if len(totals) >= cut_low_n:
        return totals[cut_low_n - 1]
    return totals[-1]


def parse_leaderboard(event, tournament_rounds, cut_low_n=60):
    competition = event["competitions"][0]
    status_state = competition.get("status", {}).get("type", {}).get("state", "")
    status_detail = competition.get("status", {}).get("type", {}).get("detail", "")
    competitors = competition.get("competitors", [])
    # Current round number (1-4). The 36-hole cut is applied AFTER round 2, so the
    # cut only exists once we're in round 3+. Before that, everyone in the field is
    # still alive. ESPN exposes NO per-player cut flag on this endpoint (a made-cut
    # leader and a missed-cut player are byte-identical), so we determine the cut
    # ourselves from 36-hole scores using the 'low N and ties' rule.
    current_round = competition.get("status", {}).get("period") or 1
    cut_applied = current_round >= 3
    cut_line = compute_cut_line(competitors, cut_low_n) if cut_applied else None
    players_by_name = {}
    for c in competitors:
        name = c.get("athlete", {}).get("displayName", "")
        if not name:
            continue
        linescores = c.get("linescores", []) or []
        score = parse_score(c.get("score"))
        if cut_applied:
            # Post-cut: made the cut iff 36-hole total is at/under the cut line.
            # WD/DQ players (no complete 36) return None and are treated as cut.
            t36 = thirty_six_hole_total(c)
            made_cut = (
                cut_line is not None and t36 is not None and t36 <= cut_line
            )
        else:
            # Rounds 1-2: no cut yet — anyone with a score is still in.
            made_cut = score is not None
        # Count rounds played (non-zero/non-null values)
        rounds_played = sum(
            1 for ls in linescores
            if ls.get("value") not in (None, 0, 0.0)
        )
        players_by_name[normalize(name)] = {
            "name": name,
            "score": score,
            "made_cut": made_cut,
            "rounds_played": rounds_played,
            "position": c.get("order"),
        }
    return {
        "event_name": event.get("name"),
        "event_id": event.get("id"),
        "status_state": status_state,
        "status_detail": status_detail,
        "current_round": current_round,
        "cut_line": cut_line,
        "players": players_by_name,
        "competitor_count": len(competitors),
    }


def compute_standings(picks, leaderboard):
    teams_out = []
    not_found = set()
    for team_name, player_names in picks["teams"].items():
        rows = []
        for pname in player_names:
            key = normalize(pname)
            p = leaderboard["players"].get(key)
            if not p:
                not_found.add(pname)
                rows.append({
                    "name": pname,
                    "score": None,
                    "made_cut": False,
                    "rounds_played": 0,
                    "position": None,
                    "counts": False,
                    "not_found": True,
                })
            else:
                rows.append({**p, "counts": False, "not_found": False})

        eligible = [r for r in rows if r["made_cut"] and r["score"] is not None]
        eligible_sorted = sorted(eligible, key=lambda r: r["score"])
        counting = eligible_sorted[:4]
        for r in counting:
            r["counts"] = True

        if len(counting) < 4:
            total = None
            status = "DQ"
        else:
            total = sum(r["score"] for r in counting)
            status = "active"

        teams_out.append({
            "team": team_name,
            "total": total,
            "status": status,
            "players": rows,
        })

    # Sort: active teams by total ascending, DQ at bottom
    teams_out.sort(
        key=lambda t: (
            1 if t["status"] == "DQ" else 0,
            t["total"] if t["total"] is not None else 0,
        )
    )
    # Add rank
    rank = 1
    for t in teams_out:
        if t["status"] == "active":
            t["rank"] = rank
            rank += 1
        else:
            t["rank"] = None

    return {
        "pool_name": picks.get("pool_name", "Major Pool"),
        "event_name": leaderboard["event_name"],
        "event_status": leaderboard["status_detail"] or leaderboard["status_state"],
        "competitor_count": leaderboard["competitor_count"],
        "current_round": leaderboard.get("current_round"),
        "cut_line": leaderboard.get("cut_line"),
        "teams": teams_out,
        "not_found_players": sorted(not_found),
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def empty_standings(picks, reason, event_name=None):
    return {
        "pool_name": picks.get("pool_name", "Major Pool"),
        "event_name": event_name or picks.get("active_event_name", "—"),
        "event_status": reason,
        "teams": [],
        "not_found_players": [],
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def main():
    picks = json.loads((ROOT / "picks.json").read_text())
    target_event = picks.get("active_event_name")
    rounds = picks.get("tournament_rounds", 4)
    # Prefer the explicit picks.json value; otherwise infer from the event name
    # (defaults to 70, the most common major cut) rather than a blind constant.
    cut_low_n = picks.get("cut_low_n") or CUT_LOW_N_BY_EVENT.get(
        normalize(target_event or ""), 70)

    try:
        data = fetch_scoreboard()
    except Exception as e:
        print(f"ESPN fetch failed: {e}", file=sys.stderr)
        standings = empty_standings(picks, f"Data fetch failed: {e}")
        (ROOT / "standings.json").write_text(json.dumps(standings, indent=2))
        sys.exit(1)

    event = find_event(data, target_event)
    if not event:
        available = [e.get("name") for e in data.get("events", [])]
        print(f"Target event '{target_event}' not found in current scoreboard. Available: {available}", file=sys.stderr)
        standings = empty_standings(
            picks,
            f"Waiting for {target_event} — current PGA event: {available[0] if available else 'none'}",
        )
        (ROOT / "standings.json").write_text(json.dumps(standings, indent=2))
        return

    leaderboard = parse_leaderboard(event, rounds, cut_low_n)
    standings = compute_standings(picks, leaderboard)
    (ROOT / "standings.json").write_text(json.dumps(standings, indent=2))
    print(f"Wrote standings.json — event: {standings['event_name']}, teams: {len(standings['teams'])}, "
          f"round: {leaderboard['current_round']}, cut_line: {leaderboard['cut_line']}")
    if standings["not_found_players"]:
        print(f"WARNING — players not matched in ESPN leaderboard: {standings['not_found_players']}", file=sys.stderr)


if __name__ == "__main__":
    main()

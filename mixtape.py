"""Mixtape: pack a plain-text track list onto tape or playlist sides.

Input format (one item per line; blank lines and lines starting with # are ignored):

    side A 24:00
    Night Drive (Edit) | 3:41 | The Lanterns

A "side" line declares a capacity (m:ss or h:mm:ss). Every other line is a track
written as "Title | duration | Artist". Tracks are packed onto sides in the order
the sides are declared, using an exact best-fill subset-sum search per side.
"""

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class Track:
    line: int
    title: str
    artist: str
    seconds: int


@dataclass(frozen=True)
class Side:
    name: str
    capacity: int
    line: int


@dataclass
class Tape:
    tracks: list
    sides: list
    errors: list


@dataclass
class SideResult:
    side: Side
    chosen: list  # tracks packed onto this side, in file order
    tracks: list  # the same tracks in play order
    total: int
    seed: int | None

    @property
    def slack(self):
        return self.side.capacity - self.total


@dataclass
class Plan:
    sides: list
    leftover: list
    problems: list


def fmt_time(seconds):
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def parse_duration(text):
    """Return seconds for m:ss or h:mm:ss. Raises ValueError with a readable message."""
    clean = text.strip()
    parts = clean.split(":")
    if len(parts) not in (2, 3) or not all(p.isascii() and p.isdigit() for p in parts):
        raise ValueError(f"bad duration '{clean}', use m:ss or h:mm:ss")
    nums = [int(p) for p in parts]
    hours = nums[0] if len(nums) == 3 else 0
    minutes, seconds = nums[-2], nums[-1]
    if (len(nums) == 3 and minutes > 59) or seconds > 59:
        raise ValueError(f"minutes and seconds must be under 60 in '{clean}'")
    total = hours * 3600 + minutes * 60 + seconds
    if total == 0:
        raise ValueError("duration must be more than zero")
    return total


def parse_tape(text):
    tracks, sides, errors = [], [], []
    side_lines = {}
    track_lines = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "|" not in line and line.split()[0].lower() == "side":
            parts = line.split()
            if len(parts) != 3:
                errors.append((lineno, "side line needs a name and a capacity, e.g. 'side A 24:00'"))
                continue
            name = parts[1]
            try:
                capacity = parse_duration(parts[2])
            except ValueError as exc:
                errors.append((lineno, str(exc)))
                continue
            if name in side_lines:
                errors.append((lineno, f"side '{name}' already defined on line {side_lines[name]}"))
                continue
            side_lines[name] = lineno
            sides.append(Side(name, capacity, lineno))
            continue
        fields = [f.strip() for f in line.split("|")]
        if len(fields) != 3:
            errors.append((lineno, "track line needs 'Title | m:ss | Artist'"))
            continue
        title, duration, artist = fields
        if not title or not artist:
            errors.append((lineno, "title and artist cannot be empty"))
            continue
        try:
            seconds = parse_duration(duration)
        except ValueError as exc:
            errors.append((lineno, str(exc)))
            continue
        key = (title.casefold(), artist.casefold())
        if key in track_lines:
            errors.append((lineno, f"duplicate of line {track_lines[key]}: '{title}' by {artist}"))
            continue
        track_lines[key] = lineno
        tracks.append(Track(lineno, title, artist, seconds))
    return Tape(tracks, sides, errors)


def lint(tape):
    """Return sorted (line, message) problems. Line 0 means the whole file."""
    problems = list(tape.errors)
    if not tape.sides:
        problems.append((0, "no sides defined; add lines like 'side A 24:00'"))
    if not tape.tracks:
        problems.append((0, "no tracks found"))
    if tape.sides and tape.tracks:
        largest = max(s.capacity for s in tape.sides)
        for t in tape.tracks:
            if t.seconds > largest:
                problems.append((t.line, f"'{t.title}' ({fmt_time(t.seconds)}) is longer than the largest side ({fmt_time(largest)})"))
    return sorted(problems, key=lambda p: p[0])


def pack_side(seconds_list, capacity):
    """Exact best fill: return (indexes chosen in ascending order, total seconds).

    Each reachable sum remembers the item that first reached it, so the chain of
    parents always uses strictly earlier items and no track is taken twice.
    """
    reach = {0: None}
    for i, secs in enumerate(seconds_list):
        for total in list(reach):
            new_total = total + secs
            if new_total <= capacity and new_total not in reach:
                reach[new_total] = (i, total)
    best = max(reach)
    chosen = []
    total = best
    while reach[total] is not None:
        index, previous = reach[total]
        chosen.append(index)
        total = previous
    chosen.reverse()
    return chosen, best


def plan_sides(tape):
    remaining = list(tape.tracks)
    packed = []
    for side in tape.sides:
        picks, _ = pack_side([t.seconds for t in remaining], side.capacity)
        taken = set(picks)
        chosen = [remaining[i] for i in picks]
        remaining = [t for i, t in enumerate(remaining) if i not in taken]
        packed.append((side, chosen))
    return packed, remaining


def _avoid_repeats(pool):
    result = []
    pool = list(pool)
    while pool:
        last = result[-1].artist.casefold() if result else None
        pick = next((i for i, t in enumerate(pool) if t.artist.casefold() != last), None)
        if pick is None:
            return None
        result.append(pool.pop(pick))
    return result


def order_tracks(tracks, seed, attempts=200):
    """Seeded shuffle with no two neighbouring tracks by the same artist.

    Returns (ordered, seed_used), or (None, None) when no order was found.
    """
    if not tracks:
        return [], seed
    counts = Counter(t.artist.casefold() for t in tracks)
    if max(counts.values()) > (len(tracks) + 1) // 2:
        return None, None
    for k in range(attempts):
        pool = list(tracks)
        random.Random(seed + k).shuffle(pool)
        ordered = _avoid_repeats(pool)
        if ordered is not None:
            return ordered, seed + k
    return None, None


def build_plan(tape, seed=1):
    packed, leftover = plan_sides(tape)
    sides, problems = [], []
    for side, chosen in packed:
        ordered, used = order_tracks(chosen, seed)
        if ordered is None:
            problems.append(f"side {side.name}: cannot order tracks without back-to-back artists")
            ordered = chosen
        total = sum(t.seconds for t in chosen)
        sides.append(SideResult(side, chosen, ordered, total, used))
    return Plan(sides, leftover, problems)


def balance_warnings(plan, max_share):
    warnings = []
    for result in plan.sides:
        if result.total == 0:
            continue
        per_artist = defaultdict(int)
        for t in result.chosen:
            per_artist[t.artist] += t.seconds
        for artist, secs in sorted(per_artist.items()):
            share = secs / result.total
            if share > max_share:
                warnings.append(
                    f"side {result.side.name}: {artist} fills {share:.0%} of the side (limit {max_share:.0%})"
                )
    return warnings


def cue_rows(tracks, gap):
    """Return (number, start seconds, track) with a silent gap between tracks."""
    rows = []
    start = 0
    for number, track in enumerate(tracks, start=1):
        rows.append((number, start, track))
        start += track.seconds + gap
    return rows


def stats_summary(tape):
    seconds = [t.seconds for t in tape.tracks]
    per_artist = defaultdict(lambda: [0, 0])
    for t in tape.tracks:
        per_artist[t.artist][0] += 1
        per_artist[t.artist][1] += t.seconds
    total = sum(seconds)
    shortest = min(tape.tracks, key=lambda t: t.seconds)
    longest = max(tape.tracks, key=lambda t: t.seconds)
    return {
        "tracks": len(tape.tracks),
        "total_seconds": total,
        "average_seconds": total // len(tape.tracks),
        "shortest": shortest,
        "longest": longest,
        "artists": per_artist,
    }


def _label(track):
    return f"{track.artist} - {track.title}"


def _report(path, problems):
    for line, message in problems:
        where = f"{path}:{line}" if line else path
        print(f"{where}: {message}")


def cmd_check(args, tape, plan):
    print(f"OK: {len(tape.tracks)} tracks, {len(tape.sides)} sides")
    return 0


def cmd_stats(args, tape, plan):
    s = stats_summary(tape)
    print(f"Tracks: {s['tracks']}")
    print(f"Total runtime: {fmt_time(s['total_seconds'])}")
    print(f"Average: {fmt_time(s['average_seconds'])}")
    print(f"Shortest: {fmt_time(s['shortest'].seconds)} ({_label(s['shortest'])})")
    print(f"Longest: {fmt_time(s['longest'].seconds)} ({_label(s['longest'])})")
    print(f"Artists: {len(s['artists'])}")
    print("Per artist:")
    ranked = sorted(s["artists"].items(), key=lambda item: (-item[1][1], item[0].casefold()))
    for artist, (count, secs) in ranked:
        print(f"  {artist}  {count} track(s)  {fmt_time(secs)}")
    return 0


def cmd_pack(args, tape, plan):
    if args.json:
        data = {
            "sides": [
                {
                    "name": r.side.name,
                    "capacity": r.side.capacity,
                    "used": r.total,
                    "slack": r.slack,
                    "tracks": [{"title": t.title, "artist": t.artist, "seconds": t.seconds} for t in r.chosen],
                }
                for r in plan.sides
            ],
            "leftover": [{"title": t.title, "artist": t.artist, "seconds": t.seconds} for t in plan.leftover],
            "problems": plan.problems + balance_warnings(plan, args.max_share),
        }
        print(json.dumps(data, indent=2))
        return 0
    for r in plan.sides:
        print(f"Side {r.side.name}  capacity {fmt_time(r.side.capacity)}  used {fmt_time(r.total)}  slack {fmt_time(r.slack)}")
        for t in r.chosen:
            print(f"   {_label(t)} ({fmt_time(t.seconds)})")
    if plan.leftover:
        print(f"Leftover ({len(plan.leftover)}):")
        for t in plan.leftover:
            print(f"   {_label(t)} ({fmt_time(t.seconds)})")
    else:
        print("Leftover: none")
    for warning in balance_warnings(plan, args.max_share):
        print(f"warning: {warning}")
    return 0


def cmd_order(args, tape, plan):
    for r in plan.sides:
        if r.seed is None:
            print(f"Side {r.side.name}: no order found")
            continue
        print(f"Side {r.side.name}  seed {r.seed}")
        for number, t in enumerate(r.tracks, start=1):
            print(f"  {number:>2}. {_label(t)} ({fmt_time(t.seconds)})")
    for problem in plan.problems:
        print(f"error: {problem}")
    return 1 if plan.problems else 0


def cmd_cue(args, tape, plan):
    for r in _selected(args, plan):
        print(f"Side {r.side.name}  capacity {fmt_time(r.side.capacity)}  used {fmt_time(r.total)}")
        rows = cue_rows(r.tracks, args.gap)
        for number, start, t in rows:
            print(f"{number:>3}  {fmt_time(start):>7}  {_label(t)}  [{fmt_time(t.seconds)}]")
        if rows:
            _, last_start, last_track = rows[-1]
            print(f"     side ends at {fmt_time(last_start + last_track.seconds)}")
    return 0


def cmd_m3u(args, tape, plan):
    if not args.side:
        print("mixtape: m3u needs --side NAME", file=sys.stderr)
        return 2
    lines = ["#EXTM3U"]
    for r in _selected(args, plan):
        for t in r.tracks:
            try:
                path = args.template.format(
                    artist=t.artist.replace("/", "-"), title=t.title.replace("/", "-")
                )
            except (KeyError, IndexError, ValueError) as exc:
                print(f"mixtape: bad --template ({exc})", file=sys.stderr)
                return 2
            lines.append(f"#EXTINF:{t.seconds},{_label(t)}")
            lines.append(path)
    print("\n".join(lines))
    return 0


def gate_problems(plan, max_slack, max_share):
    problems = list(plan.problems)
    for r in plan.sides:
        if r.slack > max_slack:
            problems.append(f"side {r.side.name} has {fmt_time(r.slack)} slack (limit {fmt_time(max_slack)})")
    if plan.leftover:
        problems.append(f"{len(plan.leftover)} track(s) not placed on any side")
    problems.extend(balance_warnings(plan, max_share))
    return problems


def cmd_gate(args, tape, plan):
    problems = gate_problems(plan, args.max_slack, args.max_share)
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}")
        return 1
    print("PASS: every side fits, nothing is left over, and no artist dominates a side")
    return 0


def _selected(args, plan):
    if not args.side:
        return plan.sides
    chosen = [r for r in plan.sides if r.side.name == args.side]
    if not chosen:
        names = ", ".join(r.side.name for r in plan.sides)
        print(f"mixtape: no side named '{args.side}' (defined: {names})", file=sys.stderr)
        raise SystemExit(2)
    return chosen


COMMANDS = {
    "check": cmd_check,
    "stats": cmd_stats,
    "pack": cmd_pack,
    "order": cmd_order,
    "cue": cmd_cue,
    "m3u": cmd_m3u,
    "gate": cmd_gate,
}


def build_parser():
    parser = argparse.ArgumentParser(
        prog="mixtape",
        description="Pack a plain-text track list onto tape or playlist sides, offline.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    help_text = {
        "check": "lint the track list with line-numbered errors",
        "stats": "runtime, averages, extremes and per-artist totals",
        "pack": "best-fill packing of tracks onto each side",
        "order": "seeded play order with no back-to-back artists",
        "cue": "cue sheet with start times and gaps",
        "m3u": "M3U playlist for one side",
        "gate": "CI gate on slack, leftovers and artist balance",
    }
    for name in COMMANDS:
        sp = sub.add_parser(name, help=help_text[name])
        sp.add_argument("tape", help="plain-text track list")
        sp.add_argument("--seed", type=int, default=1, help="ordering seed (default 1)")
        sp.add_argument("--max-share", type=float, default=0.5,
                        help="largest share of one side one artist may fill (default 0.5)")
        if name == "pack":
            sp.add_argument("--json", action="store_true", help="print the plan as JSON")
        if name == "cue":
            sp.add_argument("--side", help="only this side")
            sp.add_argument("--gap", type=int, default=2, help="silent gap in seconds between tracks (default 2)")
        if name == "m3u":
            sp.add_argument("--side", help="side to export (required)")
            sp.add_argument("--template", default="{artist} - {title}.mp3",
                            help="file path template with {artist} and {title}")
        if name == "gate":
            sp.add_argument("--max-slack", type=int, default=60,
                            help="largest unused seconds allowed per side (default 60)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if not 0 < args.max_share <= 1:
        print("mixtape: --max-share must be above 0 and at most 1", file=sys.stderr)
        return 2
    try:
        with open(args.tape, encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        print(f"mixtape: cannot read {args.tape}: {exc}", file=sys.stderr)
        return 2
    tape = parse_tape(text)
    problems = lint(tape)
    if problems:
        _report(args.tape, problems)
        return 1
    plan = build_plan(tape, seed=args.seed)
    return COMMANDS[args.command](args, tape, plan)


if __name__ == "__main__":
    sys.exit(main())

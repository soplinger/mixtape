# Mixtape

**Fill every side of the tape, with no two songs by the same band back to back.**

Mixtape is an offline command-line planner for cassette sides and playlist sides. Describe your tracks in one plain-text file, and it packs them onto each side with an exact best fill, orders each side with a seeded shuffle, and prints cue sheets, M3U playlists and a CI gate. It uses only the Python standard library, makes no network calls and keeps no state beyond the file you give it.

## Features

- **Plain-text track list.** One track per line as `Title | m:ss | Artist`, sides declared as `side A 24:00`, with `#` comments and blank lines allowed.
- **Line-numbered lint.** Every problem is reported as `file:line: message`: malformed durations, bad side lines, duplicate tracks (case-insensitive), empty fields and tracks longer than the largest side.
- **Lint exit codes.** `check` prints `OK` and exits 0 for a clean file, or lists the problems and exits 1. A missing or unreadable file exits 2.
- **Library stats.** Total runtime, average, shortest and longest track, artist count and time per artist.
- **Exact best-fill packing.** Each side gets the subset of remaining tracks that fills it as close to capacity as possible (a subset-sum search, not a greedy guess).
- **Slack and leftovers.** `pack` shows used time, slack per side and any tracks that did not fit.
- **Artist balance warnings.** Flags any artist who fills more than a set share of a side (default 50%).
- **Seeded ordering with no repeats.** `order` shuffles each side from a seed and never puts two tracks by the same artist next to each other. It reports when no valid order exists, such as one artist owning more than half the tracks.
- **Cue sheets.** `cue` gives each track a start time within its side, with a configurable silent gap (default 2 seconds) and the side's end time.
- **M3U export.** `m3u` writes a playlist with `#EXTINF` lines for one side, using a file-path template such as `{artist} - {title}.mp3`.
- **JSON plan.** `pack --json` prints the full plan for scripts and other tools.
- **CI gate.** `gate` fails when a side has more unused time than allowed, when tracks are left over, or when an artist dominates a side.

## Quick start

The sample tape is in `examples/road-trip.txt`: three 24-minute sides and 20 tracks.

```sh
python3 mixtape.py check examples/road-trip.txt
```

Expected output:

```
OK: 20 tracks, 3 sides
```

Then try the other commands:

```sh
python3 mixtape.py pack examples/road-trip.txt
python3 mixtape.py order examples/road-trip.txt --seed 7
python3 mixtape.py cue examples/road-trip.txt --side A --gap 3
python3 mixtape.py m3u examples/road-trip.txt --side B > side-b.m3u
python3 mixtape.py gate examples/road-trip.txt --max-slack 120
```

A tape file looks like this:

```
# Road-trip mix: three 24-minute sides
side A 24:00
side B 24:00

Night Drive (Edit) | 3:41 | The Lanterns
Paper Harbour | 4:12 | Mira Vance
```

## How to run

Requires Python 3.10 or newer. There are no dependencies to install.

```sh
python3 mixtape.py <command> <tape-file> [options]
```

| Command | What it does |
| --- | --- |
| `check` | Lint the file and report errors with line numbers |
| `stats` | Runtime totals and per-artist breakdown |
| `pack` | Best-fill packing per side (`--json` for machine-readable output) |
| `order` | Seeded play order per side, with no back-to-back artists |
| `cue` | Cue sheet with start times (`--side`, `--gap`) |
| `m3u` | M3U playlist for one side (`--side` required, `--template`) |
| `gate` | CI gate (`--max-slack` in seconds, `--max-share` as a fraction) |

Options shared by most commands: `--seed` (default 1) and `--max-share` (default 0.5). Exit codes: 0 means success, 1 means problems were found, 2 means a usage or file error.

## How to test

Install pytest if you do not already have it, then run the suite from the project root:

```sh
python3 -m pytest -q
```

The tests live in `tests/test_mixtape.py` and cover duration parsing, line-numbered parse and lint errors, the packing algorithm (including the no-reuse guarantee), artist ordering, cue times, balance warnings, leftover tracks, and the `check`, `gate`, `pack --json` and `m3u` commands through `main()`.

## Project layout

```
mixtape.py                 the planner and CLI (standard library only)
conftest.py                puts the project root on the import path for pytest
tests/test_mixtape.py      unit and command-level tests
examples/road-trip.txt     sample tape file
```

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mixtape import (  # noqa: E402
    Track,
    balance_warnings,
    build_plan,
    cue_rows,
    fmt_time,
    lint,
    main,
    order_tracks,
    pack_side,
    parse_duration,
    parse_tape,
    stats_summary,
)


def test_fmt_time_formats_minutes_and_hours():
    assert fmt_time(0) == "0:00"
    assert fmt_time(65) == "1:05"
    assert fmt_time(3725) == "1:02:05"


def test_parse_duration_accepts_minutes_and_hours():
    assert parse_duration("3:41") == 221
    assert parse_duration("1:02:05") == 3725


@pytest.mark.parametrize("text", ["0:60", "1:75", "1:60:00", "00:00", "abc", "3", "1:-2"])
def test_parse_duration_rejects_bad_values(text):
    with pytest.raises(ValueError):
        parse_duration(text)


def test_parse_tape_reports_track_errors_with_line_numbers():
    text = "side A 24:00\nSong | 3:00 | X\nBad line\nsong | 3:00 | x\n"
    tape = parse_tape(text)
    assert [line for line, _ in tape.errors] == [3, 4]
    assert "line 2" in tape.errors[1][1]
    assert [t.title for t in tape.tracks] == ["Song"]


def test_parse_tape_reports_side_errors_and_ignores_comments():
    text = "# comment\n\nside A 24:00\nside A 20:00\nside B nope\n"
    tape = parse_tape(text)
    assert [line for line, _ in tape.errors] == [4, 5]
    assert [s.name for s in tape.sides] == ["A"]


def test_lint_flags_empty_file_at_file_level():
    problems = lint(parse_tape(""))
    assert [line for line, _ in problems] == [0, 0]


def test_lint_flags_track_longer_than_every_side():
    problems = lint(parse_tape("side A 5:00\nLong | 6:00 | X\n"))
    assert len(problems) == 1
    assert problems[0][0] == 2
    assert "longer than the largest side" in problems[0][1]


def test_pack_side_finds_exact_best_fill():
    chosen, total = pack_side([600, 500, 400], 1000)
    assert total == 1000
    assert chosen == [0, 2]


def test_pack_side_never_uses_a_track_twice():
    chosen, total = pack_side([300], 1000)
    assert chosen == [0]
    assert total == 300


def test_pack_side_handles_no_tracks():
    assert pack_side([], 600) == ([], 0)


def test_order_tracks_keeps_artists_apart():
    tracks = [
        Track(1, "a", "X", 60),
        Track(2, "b", "X", 60),
        Track(3, "c", "Y", 60),
        Track(4, "d", "Y", 60),
    ]
    ordered, _ = order_tracks(tracks, seed=7)
    artists = [t.artist for t in ordered]
    assert len(ordered) == 4
    assert all(a != b for a, b in zip(artists, artists[1:]))


def test_order_tracks_is_impossible_when_one_artist_dominates():
    tracks = [Track(i, f"t{i}", "X", 60) for i in range(1, 4)] + [Track(4, "z", "Y", 60)]
    assert order_tracks(tracks, seed=1) == (None, None)


def test_order_tracks_is_repeatable_for_a_seed():
    tracks = [Track(i, f"t{i}", f"Artist {i % 3}", 60 + i) for i in range(1, 9)]
    first, _ = order_tracks(tracks, seed=42)
    second, _ = order_tracks(tracks, seed=42)
    assert [t.title for t in first] == [t.title for t in second]


def test_cue_rows_insert_gap_between_tracks():
    tracks = [Track(1, "a", "x", 180), Track(2, "b", "y", 120)]
    rows = cue_rows(tracks, gap=2)
    assert [start for _, start, _ in rows] == [0, 182]


def test_balance_warnings_flag_artist_filling_most_of_a_side():
    tape = parse_tape("side A 10:00\nOne | 6:00 | X\nTwo | 3:00 | X\nThree | 1:00 | Y\n")
    warnings = balance_warnings(build_plan(tape), max_share=0.5)
    assert len(warnings) == 1
    assert "X fills 90%" in warnings[0]


def test_build_plan_leaves_unplaced_tracks_over():
    tape = parse_tape("side A 1:00\nLong | 0:50 | X\nLonger | 0:40 | Y\n")
    plan = build_plan(tape)
    assert [t.title for t in plan.leftover] == ["Longer"]
    assert plan.sides[0].total == 50


def test_stats_summary_totals_per_artist():
    tape = parse_tape("side A 10:00\nOne | 1:00 | X\nTwo | 2:00 | X\nThree | 3:00 | Y\n")
    summary = stats_summary(tape)
    assert summary["tracks"] == 3
    assert summary["total_seconds"] == 360
    assert summary["artists"]["X"] == [2, 180]


def test_check_command_exit_codes(tmp_path, capsys):
    good = tmp_path / "good.txt"
    good.write_text("side A 10:00\nOne | 1:00 | X\n", encoding="utf-8")
    bad = tmp_path / "bad.txt"
    bad.write_text("side A 10:00\nOne | 1:00\n", encoding="utf-8")
    assert main(["check", str(good)]) == 0
    assert "OK: 1 tracks, 1 sides" in capsys.readouterr().out
    assert main(["check", str(bad)]) == 1
    assert f"{bad}:2:" in capsys.readouterr().out
    assert main(["check", str(tmp_path / "missing.txt")]) == 2


def test_gate_fails_when_a_side_has_too_much_slack(tmp_path, capsys):
    path = tmp_path / "slack.txt"
    path.write_text("side A 10:00\nOne | 1:00 | X\n", encoding="utf-8")
    assert main(["gate", str(path)]) == 1
    assert "slack" in capsys.readouterr().out
    assert main(["gate", str(path), "--max-slack", "600", "--max-share", "1"]) == 0


def test_pack_json_output(tmp_path, capsys):
    path = tmp_path / "pack.txt"
    path.write_text("side A 10:00\nOne | 1:00 | X\nTwo | 2:00 | Y\n", encoding="utf-8")
    assert main(["pack", str(path), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["sides"][0]["used"] == 180
    assert data["sides"][0]["slack"] == 420
    assert data["leftover"] == []


def test_m3u_export_needs_side_and_writes_extinf(tmp_path, capsys):
    path = tmp_path / "m3u.txt"
    path.write_text("side A 10:00\nOne | 1:00 | X\n", encoding="utf-8")
    assert main(["m3u", str(path)]) == 2
    assert main(["m3u", str(path), "--side", "A"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("#EXTM3U")
    assert "#EXTINF:60,X - One" in out
    assert "X - One.mp3" in out

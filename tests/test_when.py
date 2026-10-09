"""Saying when: the form a model fills, and the sentence a person accepts.

The bias these tests encode: WHAT A PERSON ACCEPTED IS WHAT THE CLOCK
DOES. The sentence and the times come from one parse, so every case
here checks the times themselves -- in the person's own zone, across a
daylight-saving change -- not only that a form was accepted. The second
bias is the floor: no form, however it is written, runs more often than
every five minutes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from samay.when import WhenError, describe, parse, parse_text

NY = ZoneInfo("America/New_York")


def local(*args) -> datetime:
    return datetime(*args, tzinfo=NY)


def times(form, start, count=4, anchor=None, tz="America/New_York"):
    when = parse(form, tz)
    return [t.astimezone(NY) for t in when.upcoming(start, count, anchor)]


class TestEvery:
    def test_counts_from_the_schedules_start_not_from_now(self):
        made = local(2026, 10, 4, 10, 17)
        got = times({"every": "3h"}, local(2026, 10, 4, 12, 0), 2, anchor=made)
        assert got == [local(2026, 10, 4, 13, 17), local(2026, 10, 4, 16, 17)]

    def test_counts_real_hours_across_a_clock_change(self):
        """Every 3 hours stays three hours apart on the night the clocks
        go back; the wall clock shows the jump."""
        made = local(2026, 10, 31, 23, 0)
        got = times({"every": "3h"}, made, 2, anchor=made)
        assert got[1] - got[0] == timedelta(hours=3)
        # 23:00 EDT + 3h is 01:00 EST: two hours on the wall, three real.
        assert [t.hour for t in got] == [1, 4]

    def test_a_window_repeats_inside_it_on_chosen_days(self):
        got = times({"every": "4h", "between": "09:00-18:00", "days": "mon-fri"},
                    local(2026, 10, 2, 17, 0), 4)       # a Friday afternoon
        assert got == [local(2026, 10, 5, 9, 0), local(2026, 10, 5, 13, 0),
                       local(2026, 10, 5, 17, 0), local(2026, 10, 6, 9, 0)]

    def test_days_without_a_window_skip_the_other_days(self):
        made = local(2026, 10, 2, 22, 0)                 # Friday 22:00
        got = times({"every": "12h", "days": "mon-fri"}, made, 2, anchor=made)
        assert all(t.weekday() < 5 for t in got)
        assert got[0] == local(2026, 10, 5, 10, 0)       # Monday morning

    @pytest.mark.parametrize("text,minutes", [("30m", 30), ("1h30m", 90),
                                              ("2 hours", 120), ("1d", 1440),
                                              ("45 minutes", 45)])
    def test_lengths_are_read_the_ways_people_write_them(self, text, minutes):
        assert parse({"every": text}, "UTC").every == timedelta(minutes=minutes)

    def test_too_often_is_refused_with_the_floor_named(self):
        with pytest.raises(WhenError, match="shortest is every 5 minutes"):
            parse({"every": "2m"}, "UTC")


class TestAt:
    def test_eight_oclock_is_eight_oclock_where_the_person_is(self):
        got = times({"at": "08:00"}, local(2026, 10, 31, 9, 0), 3)
        # Through the end of daylight saving on 1 November: still 08:00.
        assert [(t.day, t.hour) for t in got] == [(1, 8), (2, 8), (3, 8)]

    def test_several_times_on_weekdays(self):
        got = times({"at": ["20:00", "08:00"], "days": "weekdays"},
                    local(2026, 10, 2, 9, 0), 3)        # Friday 09:00
        assert got == [local(2026, 10, 2, 20, 0), local(2026, 10, 5, 8, 0),
                       local(2026, 10, 5, 20, 0)]

    @pytest.mark.parametrize("text,hm", [("8am", (8, 0)), ("8:30pm", (20, 30)),
                                         ("12am", (0, 0)), ("12pm", (12, 0)),
                                         ("07:05", (7, 5))])
    def test_times_of_day_in_either_style(self, text, hm):
        clock = parse({"at": text}, "UTC").at[0]
        assert (clock.hour, clock.minute) == hm

    def test_a_bare_number_is_ambiguous_and_refused(self):
        with pytest.raises(WhenError, match="08:00, 20:30 or 8am"):
            parse({"at": "8"}, "UTC")

    def test_two_times_too_close_are_caught_on_the_times(self):
        with pytest.raises(WhenError, match="2 minutes apart"):
            parse({"at": "08:00,08:02"}, "UTC")

    def test_a_day_range_can_wrap_the_weekend(self):
        assert parse({"at": "08:00", "days": "fri-mon"}, "UTC").days == {4, 5, 6, 0}


class TestOnceAndCron:
    def test_once_is_once(self):
        when = parse({"once": "2026-10-06T15:00"}, "America/New_York")
        assert when.next_after(local(2026, 10, 6, 14, 0)) == \
            local(2026, 10, 6, 15, 0).astimezone(UTC)
        assert when.next_after(local(2026, 10, 6, 15, 0)) is None

    def test_cron_every_two_hours(self):
        got = times({"cron": "0 */2 * * *"}, local(2026, 10, 4, 21, 30), 3)
        assert [t.hour for t in got] == [22, 0, 2]

    def test_cron_sunday_is_zero_and_seven(self):
        for line in ("0 9 * * 0", "0 9 * * 7", "0 9 * * sun"):
            got = times({"cron": line}, local(2026, 10, 5, 0, 0), 1)
            assert got[0].weekday() == 6

    def test_cron_with_day_and_weekday_matches_either(self):
        got = times({"cron": "0 9 1 * mon"}, local(2026, 10, 27, 0, 0), 2)
        assert got == [local(2026, 11, 1, 9, 0), local(2026, 11, 2, 9, 0)]

    def test_a_busy_cron_line_meets_the_floor(self):
        with pytest.raises(WhenError, match="shortest gap"):
            parse({"cron": "*/2 * * * *"}, "UTC")

    def test_a_short_cron_line_is_refused(self):
        with pytest.raises(WhenError, match="5 fields"):
            parse({"cron": "0 9 * *"}, "UTC")


class TestTheForm:
    def test_an_unknown_key_names_the_known_ones(self):
        with pytest.raises(WhenError, match="known: every, at, once, cron"):
            parse({"evry": "3h"}, "UTC")

    def test_exactly_one_kind(self):
        with pytest.raises(WhenError, match="exactly one"):
            parse({"every": "3h", "at": "08:00"}, "UTC")

    def test_a_window_needs_every(self):
        with pytest.raises(WhenError, match='"between" goes with "every"'):
            parse({"at": "08:00", "between": "09:00-10:00"}, "UTC")

    def test_an_unknown_zone_says_what_a_zone_looks_like(self):
        with pytest.raises(WhenError, match="America/New_York"):
            parse({"every": "3h"}, "Mars/Olympus")

    @pytest.mark.parametrize("text,form", [
        ("every 3h", {"every": "3h"}),
        ("every 30m between 09:00-18:00 on mon-fri",
         {"every": "30m", "between": "09:00-18:00", "days": "mon-fri"}),
        ("at 08:00,20:00 on weekdays", {"at": "08:00,20:00", "days": "weekdays"}),
        ("daily at 8am", {"at": "8am"}),
        ("once 2026-10-06T15:00", {"once": "2026-10-06T15:00"}),
        ("cron 0 */2 * * *", {"cron": "0 */2 * * *"}),
        ('{"every": "1h"}', {"every": "1h"}),
    ])
    def test_the_short_text_becomes_the_same_form_a_model_sends(self, text, form):
        assert parse_text(text) == form


class TestTheSentence:
    def test_says_what_and_when_next_in_the_persons_zone(self):
        when = parse({"at": "08:00", "days": "mon-fri"}, "America/New_York")
        said = describe(when, local(2026, 10, 2, 9, 0))
        assert said == ("at 08:00, Mon–Fri -- next: Mon 5 Oct 08:00, "
                        "Tue 6 Oct 08:00, Wed 7 Oct 08:00 (America/New_York)")

    def test_the_same_day_is_not_repeated(self):
        made = local(2026, 10, 4, 9, 0)
        said = describe(parse({"every": "3h"}, "America/New_York"), made,
                        anchor=made)
        assert "next: Sun 4 Oct 12:00, 15:00, 18:00" in said

    def test_a_passed_once_says_so(self):
        when = parse({"once": "2026-10-06T15:00"}, "America/New_York")
        assert "no time left" in describe(when, local(2026, 10, 7, 0, 0))


class TestWhoseZoneByDefault:
    """A schedule made with no zone takes the person's: in a container,
    /etc/localtime says UTC while $TZ says where they are. Read only the
    file, "at 08:00" ran at 4 am in New York."""

    def test_tz_names_the_zone_when_samay_tz_does_not(self, monkeypatch):
        from samay.schedules import default_tz

        monkeypatch.delenv("SAMAY_TZ", raising=False)
        monkeypatch.setenv("TZ", "America/New_York")
        assert default_tz() == "America/New_York"
        monkeypatch.setenv("TZ", ":Asia/Kolkata")
        assert default_tz() == "Asia/Kolkata"

    def test_samay_tz_still_wins(self, monkeypatch):
        from samay.schedules import default_tz

        monkeypatch.setenv("SAMAY_TZ", "Europe/Berlin")
        monkeypatch.setenv("TZ", "America/New_York")
        assert default_tz() == "Europe/Berlin"

    def test_a_tz_that_is_no_zone_is_passed_over(self, monkeypatch):
        from samay.schedules import default_tz

        monkeypatch.delenv("SAMAY_TZ", raising=False)
        for rule in ("EST5EDT", "Mars/Olympus"):
            monkeypatch.setenv("TZ", rule)
            assert default_tz() not in (rule, "")

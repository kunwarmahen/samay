# samay — the clock that asks your agent to do something later

"Check my email every two hours and tell me if anything needs me."
"Every weekday at 8, see what's new on my X timeline."

An agent can do either of those once, while you watch. **Samay** is
what makes it happen on a schedule, while you don't. It keeps a list
of schedules, wakes up when one is due, asks [Yantra](https://github.com/kunwarmahen/yantra)
to do the work, writes down what came back, and leaves you a record
you can read, pause, or delete.

*samay* (समय) is Hindi and Sanskrit for *time*.

```
            ┌─────────────────────────────┐
  samay add │  schedules      runs        │  samay list / runs / show
  ─────────▶│  (what to do,   (what       │◀─────────────────────────
            │   and when)      happened)  │
            └──────┬──────────────▲───────┘
                   │ due          │ answer, cost, what it needed
                   ▼              │
            yantra --json --unattended --prompt "..."
                   │
                   └─▶ the browser, your mail, your skills ...
```

**Samay never does the work itself.** It's a clock and a logbook.
Opening a browser, reading mail, running a skill: that's always a
Yantra turn, the same one you'd get by typing the prompt yourself.
Samay starts Yantra as a program and reads the one JSON object it
prints. It imports nothing from Yantra and has no dependencies of its
own.

How it's built, and why, is in the notes:
[01 — a clock and a logbook](notes/01-a-clock-and-a-logbook.md).

## Setup

```bash
uv sync
# Tell Samay how to start Yantra, and where (Yantra reads .env from there):
export SAMAY_YANTRA=~/yantra/.venv/bin/yantra
export SAMAY_YANTRA_HOME=~/yantra
```

Local models and cloud ones are both fine. Samay doesn't choose: the
Yantra it starts uses whatever its `.env` says. To run schedules on
your own Ollama box, put `YANTRA_PROVIDER=ollama` and
`OLLAMA_MODEL=qwen3.8:latest` in Yantra's `.env`, or in Samay's
environment, which the runs inherit.

## Using it

```bash
# what a 'when' means, before anything is saved
samay preview "at 08:00 on weekdays"
#   at 08:00, Mon–Fri -- next: Mon 5 Oct 08:00, Tue 6 Oct 08:00, Wed 7 Oct 08:00 (America/New_York)

# a plain question every two hours, told to you only when there is news
samay add "Any mail that needs me today? Say who and why." --when "every 2h"

# a browser check: the browser tools are allowed ahead of time
samay add "Open https://news.ycombinator.com and tell me the top 3 stories." \
      --when "at 08:00 on weekdays" --allow-tools 'browser_*' --notify always

# run the clock (keep it running: nothing runs on time otherwise)
samay serve

# see, check, stop, take back
samay list
samay runs                 # newest first, every schedule
samay show 67cad6f8        # one schedule in full (an id's first few letters do too)
samay run-now 67cad6f8     # once, now, here -- and wait for it
samay pause 67cad6f8
samay resume 67cad6f8      # its next time is worked out from now
samay rm 67cad6f8          # the schedule and its history
```

`samay list` looks like this:

```
67cad6f8  active  at 08:00, Mon–Fri -- next: Mon 5 Oct 08:00, Tue 6 Oct 08:00, Wed 7 Oct 08:00 (America/New_York)
          Open https://news.ycombinator.com with the browser and tell me the titles of the top 3…
          last: ok  Sun 4 Oct 20:42  'Here are the top 3 stories on Hacker News right now: 1. Run…'
```

Every command takes `--json`, for a page or a program to read.

### Saying when

`--when` takes a short form, or the same thing as JSON, which is what an
agent sends:

| Short form | JSON |
|---|---|
| `every 3h` | `{"every": "3h"}` |
| `every 30m between 09:00-18:00 on mon-fri` | `{"every": "30m", "between": "09:00-18:00", "days": "mon-fri"}` |
| `at 08:00` (or `daily at 8am`) | `{"at": "08:00"}` |
| `at 08:00,20:00 on weekdays` | `{"at": ["08:00", "20:00"], "days": "weekdays"}` |
| `once 2026-10-06T15:00` | `{"once": "2026-10-06T15:00"}` |
| `cron 0 */2 * * *` | `{"cron": "0 */2 * * *"}` |

Times are in your time zone (`--tz`, `$SAMAY_TZ`, or this machine's),
and "08:00" stays 08:00 when the clocks change. Nothing runs more often
than every five minutes, however it's written. A mistake is refused
before anything is saved, with what to write instead:

```
$ samay add "x" --when '{"evry": "3h"}'
error: unknown key(s) evry in "when"; known: every, at, once, cron, between, days
```

### What gets sent to you

`--notify` decides, per schedule:

* `when_new` (default): the agent is asked to reply `NOTHING NEW` when
  it did the check and found nothing worth telling. Those runs are
  kept and not sent.
* `always`: every answer is sent.
* `never`: everything is kept, nothing is sent.

If a schedule is paused (see below), you're always told, whatever
`--notify` says.

> **Where is "sent"?** Sending needs a channel. Schedules run through
> Dvara, the always-on service Yantra agents live behind, will reach
> you on Telegram. That road isn't built yet. Runs started directly, as here,
> are kept for `samay runs` and nothing more.

### When something goes wrong

| What happened | Recorded as | What Samay does |
|---|---|---|
| The machine was off at the time | `missed` | runs it late if still within its grace (half its step, at most an hour), otherwise moves on. **Never replays a backlog.** |
| The last run was still going | `skipped` | waits for the next time |
| The browser profile was in use by another Yantra | `busy` | nothing; the next time tries again |
| A site needs you to sign in again, or the agent had a question | `needs_person` | **pauses the schedule** and tells you what's needed |
| It failed 3 times in a row | `failed` | **pauses the schedule** and tells you |
| It ran past its time limit (default 10 minutes) | `timed_out` | stops it, browser and all |
| Samay stopped while it ran | `interrupted` | doesn't run it again |

Tools a run reached for and wasn't allowed are listed under the run
(`not allowed: web_fetch, bash`). They don't stop anything. They're
there so you can decide whether to allow them next time.

### Browser schedules

Logins live in a browser profile, and only one browser can use a
profile at a time. If your `yantra --web` keeps its browser open all
day, a scheduled browser run on the same profile will keep coming back
`busy`. Give the schedule a profile of its own and sign in there once:

```bash
YANTRA_BROWSER_PROFILE=~/samay-browser yantra --browse-login https://x.com
samay add "What's new on my X timeline?" --when "every 4h" \
      --allow-tools 'browser_*' --browser-profile ~/samay-browser
```

Your [Setu](https://github.com/kunwarmahen/setu) connections are there
for a scheduled run too, exactly as for any Yantra run. Their read-only
tools run without being named in `--allow-tools`.

## Settings

| Variable | What |
|---|---|
| `SAMAY_STATE` | where schedules and runs are kept (default `~/.samay`; also `--state`) |
| `SAMAY_YANTRA` | the command that starts Yantra; may be several words (`uv run --project ~/yantra yantra`) |
| `SAMAY_YANTRA_HOME` | the folder Yantra starts in, for its `.env` |
| `SAMAY_TZ` | the default time zone for new schedules |
| `SAMAY_MAX_SCHEDULES` | how many schedules one person may have (default 20) |

Everything is in one SQLite file, `~/.samay/samay.sqlite3`, readable
with the `sqlite3` shell. Each schedule's runs work in a folder of
their own, `~/.samay/work/<id>`. The agent's tools can't write outside it.

## The source

```
src/samay/
├── when.py       the 'when' form: checked, said back in words, the next times,
│                 a five-minute floor, time zones that survive a clock change
├── store.py      the SQLite file: schedules (the promise) and runs (the receipt)
├── schedules.py  add / pause / resume / remove, the per-person cap, preview
├── clock.py      the rules: missed, skipped, claimed before running, paused
│                 after failures or a need, what is sent; samay serve's loop
├── runners.py    the direct road: yantra as a program, killed with its whole
│                 process group at the time limit, only its JSON believed
└── cli.py        the commands above
```

## Status

The clock, the records, the rules above and the direct road all work,
and are covered by 95 tests. The API is not stable.

Not here yet:
* the Dvara road (a run as you, through Dvara: allowance, rules, Telegram);
* Samay's own page, and the tools an agent uses to suggest a schedule
  for you to accept;
* a Schedules tab in `yantra --web`.

## Tests

```bash
uv run pytest -q          # offline: a fake clock, a fake runner, a fake yantra
```

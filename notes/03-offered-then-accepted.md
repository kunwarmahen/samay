# 03 — Offered, then accepted

Notes [01](01-a-clock-and-a-logbook.md) and [02](02-as-the-person.md)
built a scheduler you drive from a terminal: `samay add`, `samay list`.
That's fine for someone who lives in one. It misses the two moments
when people actually want a schedule:

* **in the middle of a conversation.** "Can you keep an eye on this and
  tell me if it changes?" The agent is the one who knows how to do the
  check; it should be able to offer to do it again later.
* **afterwards, at a glance.** What have I set up? Did this morning's
  check happen? Why did that one stop? None of that should need a
  terminal.

This note covers both: the tools an agent uses to make the offer, and
the page you see things on.

## The offer: `samay mcp`

`samay mcp --for WHO` is an MCP server, a set of tools any MCP client
can give its model, written by hand over stdin and stdout like
Yantra's own client:

| Tool | read or write |
|---|---|
| `preview_schedule` | read |
| `list_schedules`, `schedule_runs` | read |
| `create_schedule` | write |
| `pause_schedule`, `resume_schedule`, `delete_schedule` | write (delete is marked destructive) |

**THE TOOL SAYS WHAT IT IS; THE HARNESS DECIDES WHO IS ASKED.** Nothing
in Samay asks a person anything. Each tool carries MCP's `readOnlyHint`,
and a harness that honours it puts the four write tools in front of the
person before they run. Yantra honours it, checked against Yantra's own
client:

```
mcp__samay__preview_schedule             read_only=True
mcp__samay__list_schedules               read_only=True
mcp__samay__schedule_runs                read_only=True
mcp__samay__create_schedule              read_only=False
mcp__samay__pause_schedule               read_only=False
mcp__samay__resume_schedule              read_only=False
mcp__samay__delete_schedule              read_only=False
```

So "the agent proposes, the person accepts" isn't a convention the
model has to follow. It's the permission gate every write already goes
through: a card in the browser, a y/N in the terminal, two buttons on
Telegram.

The tool descriptions do their part on top of that: *preview first,
tell the person the sentence, create only if they say yes*. The model
then asks in words before the card ever appears, and you've already
read what "at 08:00, Mon–Fri" means when you're asked to approve it.

**ONE PERSON, FIXED BY THE HARNESS.** `--for` is given when the server
starts. No tool has an argument that names a person, an agent or a
road, so the model can't schedule for someone else, and someone else's
schedule is "no schedule" to every tool. A schedule runs the agent the
harness named with `--agent`, so a schedule made while talking to your
mail agent runs your mail agent, whatever the model writes.

**NO RUN-NOW.** A run is itself an agent turn, often minutes long, and
possibly using the same browser profile. Started from inside the turn
that's talking to you, it would hold that turn up. The page and
`samay run-now` cover running one now.

### What a local model did with them

`qwen3.8:latest` through Ollama, given `samay mcp` as an MCP server and
the prompt *"Every weekday at 8am, check news.ycombinator.com and tell
me the top 3 stories. Please set that up for me."*:

* **With nothing allowed** (an unattended run, so nobody was there to
  approve): it called `preview_schedule`, then `create_schedule`, which
  was refused. It then tried to ask *"Ready to create this schedule —
  every weekday (Mon–Fri) at 08:00 America/New_York … OK to set it
  up?"*. That's the right question, recorded as needing a person.
* **With `create_schedule` allowed:** it called `preview_schedule` and
  then *stopped to ask* (*"Would you like me to create this
  schedule?"*) without creating anything. That's the offer working as
  described.
* **Told up front "I agree to it":** it created the schedule, and wrote
  a prompt fit for its future self:

  > Open https://news.ycombinator.com in the browser and report the top
  > 3 stories currently on the front page. For each: its rank, title,
  > and link. Keep it short — one line per story.

  It also passed on what the tool told it: *"the Samay scheduler isn't
  currently running on this machine, so the schedule won't actually
  fire until `samay serve` is started."*

Two things it got wrong, both visible on the approval card, which is
why the card shows the arguments:

* `allow_tools` listed `browser_navigate` and `browser_type`, which
  don't exist, alongside the real `browser_open`, `browser_click` and
  `browser_fill`. A name that matches nothing grants nothing, but the
  list was wider than an HN check needs (`browser_fill`).
* It picked `notify: when_new` for a daily digest, where `always` is
  what a person asking for "the top 3 every morning" would want.

## The page

`samay serve` now serves one page beside the clock:

![The page](../docs/page.png)

**THE DAY IS THE MEMORABLE THING.** A scheduler's page should look like
time. The strip at the top is the next 24 hours, with lines on the real
hours, a marigold line for *now*, and a dot for every run due, one lane
per schedule. Click a dot and its schedule is highlighted below.
Everything else is deliberately quiet: rows, not cards, each led by
its next time in large figures, then what it does, how its last run
went, and why it's paused if it is. "Needs you" is drawn in a warning
colour. "Paused by you" isn't, because nothing is wrong.

**A TOKEN ON EVERY CALL, EVEN ON LOCALHOST.** Any website you visit can
send a request to 127.0.0.1. Without a token, one of them could delete
your schedules, or add one that runs every five minutes. So every
`/api` call needs `Authorization: Bearer`, compared in constant time.
No CORS headers are sent, so another site can't read an answer either.
The page itself holds no data and needs no token. The token is made
once and kept in the state folder (mode 600). `samay serve` prints the
address with the token after a `#`, the one part of an address a
browser never sends to a server, so it stays out of logs. The page
keeps it after that.

**NOTHING FETCHED FROM ANYWHERE.** No web fonts, no scripts from a CDN.
A local tool that told a font server every time you opened it would be
reporting on you. The Devanagari समय is drawn with whatever Devanagari
font the machine has.

**RUN NOW ANSWERS AT ONCE.** A run can take minutes, so the page's
request gets `202` straight away and the run appears in the history
when it's done. A second click while it's running gets `409`, the same
rule the clock follows.

The page was reviewed from screenshots at desktop width, phone width,
and in dark mode. Three fixes came out of that review:
* the big time no longer wraps on 12-hour clocks ("08:00" large, "AM"
  small);
* the strip's lines now sit on real hours, not on "now + 6 hours";
* "paused by you" stopped using the warning colour.

## `samay status --json`

What a harness reads to decide whether to offer schedules at all:

```json
{"format": "samay.status.v1", "version": "0.1.0", "state": "/home/you/.samay",
 "serving": true, "url": "http://127.0.0.1:8780/",
 "schedules": {"active": 2, "paused": 2, "done": 0},
 "dvara": null,
 "mcp": {"command": "/home/you/samay/.venv/bin/samay", "args": ["--state", "/home/you/.samay", "mcp"]}}
```

The same shape as Setu's `status --json`. One function serves the
import and the command, the `format` is the contract, and no secret is
in it.

## What was deliberately not built

* **Validating `allow_tools` against the agent's real tools.** Samay
  doesn't know them, and a name that matches nothing grants nothing.
  The harness, which does know them, is the right place to say "these
  two don't exist" on the approval card.
* **Editing a schedule in place.** Delete and add again. An edit would
  need its own approval card showing what changed, which is a feature
  of its own.
* **Accounts on the page.** One person runs `samay serve`, and the
  token is theirs. The page shows every schedule in the file. Several
  people go through Dvara, where each person's channels and allowance
  already live.

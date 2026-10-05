# 04 — New against what was told

`notify: when_new` is the setting most schedules want: check every two
hours, and only bother me when there's something to say. It works by
asking the agent, in each run, to reply `NOTHING NEW` when that's the
case ([note 01](01-a-clock-and-a-logbook.md)). "New" means new since
last time. So the agent has to know what it said last time.

It didn't, really. Every run is a fresh conversation, so that cost stays
flat over hundreds of runs, and all it was given about the past was one
line: *"(Last run, Mon 5 Oct 14:54: …)"*, the first line of the last
reply, cut at 200 characters.

## What a live run showed

`qwen3.8:latest` on Ollama, on the direct road, a scratch browser
profile, the schedule *"Open https://news.ycombinator.com and tell me
the top 3 stories, with their points"*, `when_new`, run three times a
few minutes apart. The front page didn't change between runs.

Run 1 listed three stories. Run 2 listed **the same three** and wrote:

```
1. The future of independence is interdependence — 84 points (same as last run)
2. Web Search API — 351 points (new in top 3)
3. Making a GTK application in Haskell, part 1 — 94 points (new in top 3)
```

The model was right about the one story it had been shown. The
summary line was the reply's first line ("Here are the top 3
stories:") with the first story attached. It was wrong about the two it
hadn't been shown, and a schedule that calls unchanged news "new" sends
every time. Run 3 replied `NOTHING NEW`, and that was luck: the run
before it had said nothing beyond its intro, so run 3 had nothing to
compare against at all.

## The fix: the last report, not the last line

A `when_new` run is now also shown **the last reply that reported
something**: the last `ok` run, not the last run. A quiet run's whole
reply is `NOTHING NEW`, which is nothing to compare against. It's capped
at 1,500 characters:

```
(What you reported on Mon 5 Oct 14:57 -- compare against it; only what
is not in it is new:
Here are the top 3 Hacker News stories right now: ...
)
```

`always` and `never` schedules keep the one line. Nothing is compared
there, and their prompt stays the same size forever. A `when_new`
schedule pays for its comparison, about 400 tokens for a list like this
one, and no more than 1,500 characters for anything.

## The verdict at the end

With the last report in front of it, run 2 got it right:

```
The top 3 HN stories are identical to the last run (same three stories, same points):
1. ...
Nothing has changed since the last run.

NOTHING NEW
```

Samay still filed it `ok`, and on a channel it would have been sent:
`NOTHING NEW` only counted when it was the reply's first line. A model
that compares first and concludes second puts its verdict last. So
**the last line counts too**. A reply whose first or last non-empty
line is `NOTHING NEW` is quiet; a line that only mentions it ("NOTHING
NEW at the bank. But your landlord wrote…") is not.

This adds no new way for a failure to hide. A run that needed a person,
found the browser busy or failed is decided before the quiet check is
looked at. The instruction that forbids `NOTHING NEW` after a failure
still applies, and it already trusted the model's verdict when it came
first.

Three more runs on a fresh schedule, with both changes:

```
$ samay runs e7a2…
Mon 5 Oct 14:59  quiet   The top 3 stories are the same three as the last run — …
Mon 5 Oct 14:59  quiet   NOTHING NEW.
Mon 5 Oct 14:59  ok      Top 3 Hacker News stories (as of now): 1. **Denmark Data Breach …
```

The check that matters most was rerun too: X's timeline on a profile
that isn't signed in, `when_new`, twice. Neither run was quiet. Each
said what stopped it (*"I couldn't complete this: x.com refused
access … HTTP 403"*) and was filed `ok`, so it would be sent. One
change since note 01: x.com now answers a headless browser that isn't
signed in with a 403 rather than a sign-in page, so the model explains
instead of handing off. The run wasn't `needs_person`, and the schedule
wasn't paused: you'd have been told each morning until you signed in.
Noisier than a pause, but not silent, and silence is the failure that
matters. Yantra then gave a refused page in an unattended run the same
way out a sign-in page has (its note 114), and three runs out of three
handed off and paused.

## What was deliberately not built

* **Samay comparing the replies itself.** Two lists of the same stories
  are rarely the same text: points change, the wording changes. A
  "same as last time" check in code would need to understand the page,
  which is the agent's work, not the clock's.
* **The whole history.** One report is enough to say what's new since
  then. More would make every run's prompt grow with the schedule's age.
* **Pausing on a reply that says it couldn't look.** "x.com refused
  access" is prose. Reading it for a failure is guessing. A run is
  `needs_person` when the agent says so through its handoff tool,
  which is a fact Yantra reports, not a sentence Samay interprets.

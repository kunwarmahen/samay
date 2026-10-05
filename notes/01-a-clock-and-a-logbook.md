# 01 — A clock and a logbook

An agent that can check your email can do it whenever you ask. What it
can't do is ask itself. "Every two hours", "weekdays at 8" and "once,
on Tuesday at 3" all need something that's still running when you
aren't, keeps track of what you asked for, and can show you afterwards
what happened.

That something could have lived inside the agent framework, or inside
Dvara, the service the agents sit behind. Dvara's first note already
refused it: *no web UI, no registry, no scheduling, no second process
— each of those is a service of its own wearing this one's clothes.*
This is that service.

## Samay does no work

Samay keeps two lists, the **schedules** (what to do, and when) and the
**runs** (what happened each time). It wakes up when something is due
and hands it to Yantra. It does nothing else.

That's deliberate. A scheduled check of x.com is a browser, a model,
your sign-ins and your permission rules: everything Yantra already
does, and does the same way whether you typed the prompt or a clock
did. A scheduler that reached into any of that would be a second agent
framework, one that only runs at 08:00.

So a run is a program:

```
yantra --agent DIR --cwd ~/.samay/work/<id> --json --unattended \
       --allow-tools 'browser_*' --prompt "..."
```

Samay reads one JSON object from Yantra's output and believes nothing
else. **A PROCESS, NOT AN IMPORT**, for three reasons:

* a run that hangs on a page that never finishes loading can be
  killed, browser included, by killing its process group. A thread
  can't be;
* Yantra lives in its own environment with its own `.env`, and a
  program is the one interface that doesn't care;
* Samay stays small. Its dependency list is empty, and the JSON's
  `format` is the whole contract. A format it doesn't know is refused,
  not guessed at.

What Yantra does when nobody is watching, and what the JSON contains,
is Yantra's note 114.

## Saying when, in a form a model can fill

A schedule is accepted by a person, so what they accept should be a
sentence: *at 08:00, Mon–Fri — next: Mon 5 Oct 08:00, Tue 6 Oct 08:00*.
It's usually proposed by a model, and often a small local one, which
is bad at cron strings and good at forms. So the form is the contract:

```json
{"every": "30m", "between": "09:00-18:00", "days": "mon-fri"}
{"at": ["08:00", "20:00"], "days": "weekdays"}
{"once": "2026-10-06T15:00"}
{"cron": "0 */2 * * *"}
```

Cron is still there, as a way out for people who want it.

**THE SENTENCE AND THE CLOCK READ THE SAME PARSE.** `describe` builds
the words and the next three times from the object `next_after` runs
on. What a person accepts and what happens at 08:00 can't drift apart.

**A FLOOR UNDER EVERY FORM.** Nothing runs more often than every five
minutes. The check is on the times themselves, not on the field that
asked for them, so `{"at": ["08:00", "08:02"]}` and `*/2 * * * *` are
caught as well as `{"every": "2m"}`. A misunderstanding ("every
minute" for "every morning") would otherwise turn into a bill.

**TIME ZONES ARE THE SCHEDULE'S.** "08:00" is 08:00 where the person
is, through daylight saving. `every` counts real hours: on the night
the clocks go back, a run at 23:00 every 3 hours is next at 01:00
(two hours on the wall, three real) and then 04:00. That case is a
test, because the first version of the test expected 03:00 and the
code was right.

## The rules, each against a way it goes wrong

Every rule about time lives in `clock.py`. Each one is there because a
schedule nobody is watching fails in a way nobody would see:

* **A missed time runs once, late, or not at all.** If the machine was
  asleep at 08:00 and wakes at 08:20, the check still runs, because
  it's within the schedule's grace (half its step, at most an hour).
  If it wakes at 14:00, it doesn't: that would be a different check
  wearing the morning's name. However many times were missed, one row
  says so. **A backlog is never replayed**: twelve hourly checks fired
  at once would be twelve bills for one answer.
* **The next time is claimed before the run starts.** A run spends
  money and may have done something, so a crash partway through must
  not run that time again. On restart the run is marked `interrupted`.
* **One run of a schedule at a time.** A time that arrives while the
  last run is still going is recorded as `skipped`. A `running` row
  left by another process counts, but only for as long as that run
  could still be going (its time limit plus two minutes). A dead
  process's row doesn't block the schedule for ever.
* **Needing a person pauses at once.** An expired login won't fix
  itself between 09:00 and 10:00. The person is told what's needed,
  and resuming is up to them.
* **Three failures in a row pause the schedule**, and the person is
  told once. A schedule that fails every hour all night is a night of
  bills and no answers.
* **A busy browser is not a failure.** Another Yantra had the profile,
  so the run is recorded as `busy`, nobody is told, and the next time
  tries again.

## Quiet, and what "quiet" may not hide

Most checks find nothing most of the time. A schedule that messages
you "nothing new" twelve times a day is one you'll switch off. So each
schedule has `notify`: `always`, `never`, or `when_new`, where the
agent replies `NOTHING NEW` when there's nothing worth telling and
that run is kept but not sent.

The first version offered that reply as a plain choice, and a live run
showed what it costs. `qwen3.8:latest`, sent to `x.com/home` on a
profile that wasn't signed in, hit the sign-in wall and answered:

```
Sun 4 Oct 20:46  quiet         NOTHING NEW
```

A run that never got in was filed as a quiet success and told to
nobody. That's the worst result a scheduler can have: it looks like
it's working. **`NOTHING NEW` IS FOR A CHECK THAT WAS DONE**, and the
instruction now says so:

> If you did what was asked and there is nothing new worth telling the
> person since the last run, reply with exactly: NOTHING NEW. If you
> could NOT do it — a page asked you to sign in, something failed, a
> tool was refused — never reply NOTHING NEW; say what stopped you.

Yantra's handoff tool also got a description for unattended runs
(Yantra's note 114). On three more runs of the same schedule, all three
ended as `needs_person`, and each paused itself with a reason:

```
8e2bbd43  paused  every 4 hours
          paused: needs you: X/Twitter at x.com/home refused the headless browser
          (ERR_HTTP_RESPONSE_CODE_FAILURE) — almost certainly the login wall / bot check.
          You need to complete a sign-in (and any captcha/2FA) on X ...
```

**THE TRADEOFF.** `when_new` still trusts the model to tell "nothing
new" apart from "couldn't look". The instruction narrows that, and a
sign-in wall now has its own way out, but a model that says
`NOTHING NEW` about a page it misread can still go unnoticed. The runs
are all kept with their full answers, so `samay runs` shows it. Nothing
here *proves* the check was done.

## Refused is not the same as needed

The first version counted every tool the unattended run wasn't allowed
as "needed a person". A live run of the x.com schedule, with Setu on,
read the real timeline through the person's Setu X connection. It also
reached for `bash`, was told no, and wrote a complete answer anyway.
The schedule paused, because something "needed a person". Nothing did.

So Yantra now reports three separate lists, and Samay treats them
differently. Only `needs_person` stops a schedule. `busy` is shrugged
off. `refused` is printed under the run so a person can widen
`--allow-tools` if they want:

```
Sun 4 Oct 20:49  busy          I hit a wall on this one, so here's the honest status: …
    not allowed: web_fetch, bash (allow with --allow-tools when adding)
```

## Receipts

Everything below was run against `qwen3.8:latest` through Ollama, with
Samay's state and the browser profile in a scratch folder.

A plain question, through `samay run-now` (19 seconds):

```
$ samay add "What is 17 times 23? Answer in one sentence." --when "every 2h" --notify always
added bdef9ef0: every 2 hours -- next: Sun 4 Oct 22:42, Mon 5 Oct 00:42, 02:42 (America/New_York)
$ samay run-now bdef9ef0
Sun 4 Oct 20:42  ok            17 times 23 is 391.
```

A browser schedule, headless, Hacker News (22 seconds):

```
Sun 4 Oct 20:42  ok            Here are the top 3 stories on Hacker News right now:

1. Run Qwen 3.8 Flash Next (125B) on consumer hardware (RTX 4090) at 100T/s
2. Infidel goes wild
3. Turn off Apple Intelligence on macOS 27 and get its disk space back
```

That summary line is why `summarize` now takes the next line along
with one that ends in a colon. *"Here are the top 3 stories:"* alone
tells you nothing in `samay list`.

`samay serve`, with a schedule set for a minute ahead:

```
samay 0.1.0: 1 active schedule(s), state in .../samay-live
2f583880  Sun 4 Oct 20:51  ok            Mars is a planet in our solar system known for its reddish appearance…
stopped
```

and afterwards the one-time schedule reads `done`.

## What was deliberately not built

* **A second agent inside the scheduler.** No model call happens in
  Samay. Deciding when a run is worth sending is the agent's job, in
  its answer.
* **Retries.** A failed run is not tried again before its next time.
  The next time *is* the retry, and three in a row stop it.
* **Replaying missed times.** Covered above. One row says what was
  missed.
* **Triggers other than time** ("when a mail from my bank arrives").
  That's something that watches, not a clock, and it needs its own
  design.
* **Sending, on this road.** A run started directly has no channel to
  reach you on, so it's kept for `samay runs`. Sending arrives with
  runs through Dvara, where the channels already are.

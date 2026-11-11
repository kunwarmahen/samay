# 17 — Changed in place

"Make my morning brief 8 instead of 7" had one road: delete the
schedule and make it again. That cost more than it looked. The
logbook went with it, so "how did the brief go last week?" had nothing
to read. The tools it was allowed went with it, so the person said yes
to the same `web_fetch` again on a new card. And it came back with a new
id, so any link to the old one pointed at nothing.

`samay edit` changes a schedule where it stands:

```bash
samay edit c08821bf --when "at 08:00 on weekdays"
samay edit c08821bf --prompt "my brief, and the weather in Cary" --notify always
samay edit c08821bf --tz Asia/Kolkata
samay edit c08821bf --phone nexus         # a schedule that works a phone: which one
```

Only what you pass changes. The page has a **Change** button that does
the same, and an agent has `change_schedule`, which the person approves
on a card like any other change.

## What it may change, and what it may not

**WHAT IT ASKS AND WHEN, YES.** Its prompt (a routine schedule's prompt
is still a routine's name), its *when*, its zone, when it tells you,
which of your phones. These are the words of the schedule, and the
person who owns it can always reword it.

**WHAT IT RUNS, NO.** Its road (direct, Dvara, a routine, the backup),
its agent, and whether it works the phone at all were part of the yes it
was made with. A schedule that never touched the phone and now does is
a different promise, made in a chat that has the phone, so that's a new
schedule. Which phone, for one that already works a phone, is only a
name and may change.

**ITS TOOLS STAY.** A new prompt can't reach anything the old one
couldn't. The tools a run may use unasked are still the ones it was
allowed, and anything else that changes something is still asked about
or refused. So rewording a schedule needs no new yes for its tools, and
the person can do it from a chat command with no model at all (Dvara's
`/schedules does 2 …`).

## A new when counts from the change

`every 2h` counts from when the schedule started. A schedule made at
9:07 runs at 11:07, 13:07, and so on. Change it to `every 3h` at 15:00 and
it would be odd for it to keep the 9:07 beat. It doesn't: the schedule
keeps a `counted_from`, set when its *when* changes, and its times count
from there. "Every 3h" changed at 15:00 next runs at 18:00. Prompt, notify
and phone changes leave the beat alone.

A schedule that had finished (a `once` that ran) comes back when its new
*when* has time left. A paused one stays paused: changing its time is
not the same as saying go, and `samay resume` still says go. A *when*
Samay can't read is refused in Samay's own words, and nothing moves.

## Live receipt

Against a scratch state folder, `SAMAY_TZ=America/New_York`:

```
$ samay add "give me my morning brief" --when "at 07:00" --allow-tools web_fetch
added c08821bf: every day at 07:00 -- next: Wed 11 Nov 07:00, Thu 12 Nov 07:00, Fri 13 Nov 07:00 (America/New_York)

$ samay edit c08821bf --when "at 08:00 on weekdays"
c08821bf changed: runs at 08:00, Mon–Fri -- next: Wed 11 Nov 08:00, Thu 12 Nov 08:00, Fri 13 Nov 08:00 (America/New_York)

$ samay edit c08821bf --prompt "give me my morning brief, and the weather in Cary" --notify always
c08821bf changed: now asks: give me my morning brief, and the weather in Cary; tells always

$ samay edit c08821bf --when "sometimes"
error: cannot read 'sometimes'; start with every, at, once or cron (e.g. 'every 3h', 'at 08:00 on mon-fri')

$ samay show c08821bf
c08821bf  active  at 08:00, Mon–Fri -- next: Wed 11 Nov 08:00, Thu 12 Nov 08:00, Fri 13 Nov 08:00 (America/New_York)
          give me my morning brief, and the weather in Cary
          notify: always   runner: direct   time limit: 600s
          allowed: web_fetch
          made Tue 10 Nov 22:49 (by cli), for local; changed Tue 10 Nov 22:49
```

On the page (headless Chromium, same state folder): **Change** opened
under the schedule. Typing `at 09:15 on weekdays` showed *at 09:15,
Mon–Fri -- next: Wed 11 Nov 09:15, …* before saving. The form was still
as typed after the page's own 20-second refresh, and **Save changes**
left the row reading the new prompt and the new time.

## Where else

* The page sends `POST /api/schedules/ID/edit` with only the boxes that
  differ; the card that comes back carries `said`, the same sentence the
  terminal prints.
* Yantra's Schedules panel has the same **change**, through `samay edit`.
* Dvara answers `/schedules when 2 at 08:00` and `/schedules does 2 …`
  with no model, for the person's own schedules.
* This continues [14 — more time for a run](14-more-time-for-a-run.md),
  the first thing about a schedule that could change without remaking it.

# 14 — More time for a run

A schedule's time limit is a guess made before its first run, and the
default (ten minutes) is a cloud model's ten minutes. A local model
reading mail, a calendar, three brokerage accounts and a notes app can
need thirty (note 13). Until now the only way to change a limit was a
new schedule.

```bash
samay limits 713aefd8 --time-limit 1800
# 713aefd8 runs get 30 min of work, and 30 min for their questions
```

`--wait MINUTES` changes the time its questions may wait, in the same
command. Both apply from the next run.

## On the page, and from the agent

Each schedule on Samay's page has a **Time: 10 min** button next to
Pause. It asks how many minutes of work each run gets and sends
`POST /api/schedules/ID/limits {time_limit}`, which takes `wait` too.

`give_schedule_time` does the same from a chat, for the person's own
schedules: "the morning brief keeps coming back too long, give it
half an hour" is a call, not a new schedule. `create_schedule` takes
`time_limit_minutes`, so a schedule the agent makes for a long job can
start with the time it needs. Both are in minutes, as `wait` is, since
that is how a person says it. Samay keeps seconds.

**THE ANSWER TO TOO LONG IS MORE TIME, AND IT SAYS SO.** A
`timed_out` run's sentence ends with the command:

```
stopped after 600s, the time limit for this schedule. To give it
longer: samay limits 713aefd8 --time-limit SECONDS
```

**THE BOUNDS ARE THE ONES IT WAS MADE WITH.** 30 seconds to an hour of
work, 1 to 240 minutes for questions, checked in one place
(`schedules.set_limits`) for the command, the tool and `add`.

## What was deliberately not built

* **A limit that learns.** Samay could raise a limit after a timeout
  by itself. A run that never ends would then be given an hour every
  morning. More time is the person's call, or their agent's when they
  ask.
* ~~**A box on Samay's page.**~~ The **Time** button, above. The wait
  for questions is still the command, the chat or the API: a page
  button for a number most people never change would be clutter.

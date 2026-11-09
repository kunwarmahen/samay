# 16 — A routine, on time

Vidhi keeps routines a person drew once: steps that fetch side by side,
ask the model, ask the person yes or no, and tell them. *Every morning
at seven* is Samay's. A schedule that asked the agent "do my morning
brief" would spend a model call deciding what the routine already
decided, and might do it differently each morning.

Continues [12 — the house, backed up every night](12-the-house-backed-up-every-night.md),
another road that asks no agent anything.

## The routine road

`--runner vidhi`, with the routine's name as the prompt:

```bash
samay add morning-brief --when "at 07:00" --runner vidhi
```

At its time the road runs `vidhi start morning-brief --as <the
schedule's person> --by samay:<its id> --json`. That only adds a run to
Vidhi's state folder (the containers share it); Vidhi's own server runs
the steps.

**STARTING IS ALL SAMAY DOES, AND IT'S QUIET.** A routine that started is
`NOTHING NEW`, with which run it was. The routine tells the person what
it found itself, so Samay saying "started" every morning would be a
second message about the same morning.

**ONE THAT DIDN'T START SAYS WHY, IN VIDHI'S WORDS.** Paused, removed,
five runs already open, an input missing: a failed run whose detail is
Vidhi's own sentence (*the routine didn't start: paused-one is paused:
vidhi resume paused-one*). Three in a row pause the schedule, as any
failing road does.

**A ROUTINE SCHEDULE ASKS NO AGENT ANYTHING.** It takes no agent, tools,
phone or browser, and its prompt must be a routine's name
(`morning-brief`), not a sentence.

**THE AGENT ASKS FOR ONE BY NAME.** `create_schedule` takes `routine`
instead of a prompt; the schedule is the person's, on this road.

## Live receipt

A scratch Samay and a scratch Vidhi with `coat-check` installed:

```
$ samay add coat-check --runner vidhi --when "at 07:00"
added 0a769de1: every day at 07:00 -- next: Tue 10 Nov 07:00, …
$ samay run-now 0a769de1
Mon 9 Nov 11:39  quiet         NOTHING NEW
Started the routine coat-check (run 60833e71); Vidhi tells you what it finds.

$ vidhi runs --limit 1
60833e71  coat-check  done  2/5 steps  by samay:0a769de1
```

## Not here

* **Inputs per schedule.** The routine runs with the inputs it was
  installed with; different ones are a second routine.

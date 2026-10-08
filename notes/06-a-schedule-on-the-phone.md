# 06 — A schedule on the phone

[Note 02](02-as-the-person.md) runs a schedule through Dvara as its
person, so a question can still reach them. Dvara's phone road gave a
person's chat turn their phone (Dvara's note 30) and kept it from every
scheduled run: nobody would be there to say yes at Send, and nobody
knew whether the phone was free. This note is the clock's half of
letting a schedule have the phone.

## What a schedule says

Three fields, all on the Dvara road, where the phone is:

* **`phone`**: it works the person's phone. A schedule made in a chat
  turn that had the phone is one already: Dvara starts this person's
  tools with `--phone`, and `create_schedule` marks what it makes. From
  the command line, `--phone`. A run without it never gets the phone,
  as before.
* **`phone_steps`**: held steps it may do without asking, each as the
  person accepted it, in the one form Sparsh reads: *"send in Messages
  when the screen shows 555-0123"*. Checked against that form when the
  schedule is made, so it can't save a grant the phone would refuse to
  read. Steps need `phone`.
* **`wait`**: minutes its questions may wait for the person, in all
  (default 30). It applies to any Dvara-road run, phone or not.

**THE PERSON SEES THEM BEFORE SAYING YES.** Yantra's card for
`create_schedule` says *IT WORKS YOUR PHONE*, lists each step as *ON
YOUR PHONE, WITHOUT ASKING*, and how long questions wait.

## What a run does with them

`POST /message` carries `wait` (seconds), and for a phone schedule
`phone: true` and the steps. Dvara does the rest: it checks the phone,
hands the steps to Sparsh, and gives questions the schedule's wait.

**THE WAITING IS NOT THE WORK.** A phone run may wait for a phone in
someone's hand (up to ten minutes), for its person to unlock it, and
for its questions. None of that is the time limit's to spend: the call
to Dvara gets `time_limit + 10 min + 2 × wait`. Only a phone schedule
gets the longer allowance; any other run times out as before.

**A SKIP IS NOT A FAILURE.** A run Dvara skipped (the phone was in use,
or stayed locked after the person was asked) is `skipped` in the
logbook with Dvara's sentence, and doesn't count toward the three
failures that pause a schedule.

**WHAT LAPSED IS NAMED.** A question that outwaited `wait` comes back in
the run's refused list with its words: `samay runs` prints it as
*asked, not answered: mcp__sparsh__confirm: … tap item "Send SMS" …*,
apart from tools that were simply not allowed.

## An older file

The schedule table gained three columns. A file made before them gets
them when Samay opens it, with the defaults every earlier schedule had
in effect (no phone, no steps, 30 minutes): nothing else in it changes.

## Live, on the emulator

`samay run-now` on the Dvara road, `qwen3.8:latest` on Ollama, a
schedule "Text 555-0123 saying: running late, home by 7" with
`--phone-step "send in Messages when the screen shows 555-0123" --wait 2`:

```
Thu 8 Oct 19:01  ok        Done. The message "running late, home by 7" was sent to 555-0123 …
Thu 8 Oct 19:05  skipped   skipped: the phone stayed locked for 2 minutes after you were asked …
Thu 8 Oct 19:07  ok        Done. Today's message "running late, home by 7" was sent …
```

The first ran on a sleeping phone, woken first. The second found it
locked, asked, waited two minutes and skipped. The third found it locked
and was unlocked twenty seconds after asking, so it went. A fourth
schedule texting 555-0199 with the same step was held at Send:

```
    asked, not answered: mcp__sparsh__confirm: On the phone emulator-5554: tap item
    "Send SMS — SMS" in com.google.android.apps.messaging -- held because it says "send".
```

## What the tests hold

`tests/test_dvara.py`: a phone run carries its steps and its wait, and
a run without the phone says nothing of it; a skip is not a failure;
steps are checked and need the phone, and the phone needs the Dvara
road; an older file gains the columns and keeps its schedules.
`tests/test_mcp.py`: a turn with the phone makes schedules that work
it. 167 tests before, 173 after.

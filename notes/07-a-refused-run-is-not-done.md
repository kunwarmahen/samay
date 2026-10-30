# 07 — A refused run is not done

A person asked their agent to turn off the stairs light in five minutes.
The agent made a schedule, they said yes, and at 16:03 Samay ran it. In
Samay's record the run said:

```
done   Couldn't do it.** The scheduled run is unattended, so it only
       auto-approves read-only tools — my switch/turn_off call on
       switch.lights_2 was refused ("Nobody is available to ask").
```

The light stayed on. Samay filed that run as `ok`, the outcome meaning
*it did what it was asked*. The person was in front of Telegram the
whole time.

Three of the causes are Yantra's: the model allowed nothing, the card
didn't warn about it, and a run nobody watched couldn't ask anyone
(Yantra's notes/126). Two are Samay's: the direct road never told Yantra
there was somebody to ask, and the clock believed `ok`.

## The direct road can ask

A schedule made at this computer runs on the direct road: Samay starts
`yantra --unattended` as a program. Before this note, that meant every
write nothing allowed was refused. But in Sarathi, Samay's clock already
knows a Dvara (`SAMAY_DVARA_URL`) and who the person at this computer is
(`SAMAY_DVARA_ACTOR`). It used them only to *send* answers.

Now the direct road uses them to *ask*. When `DirectRunner` has a Dvara
and a person for the schedule, the Yantra it starts gets:

```
YANTRA_ASK_URL=http://sarathi-dvara:8765   YANTRA_ASK_ACTOR=owner
YANTRA_ASK_TOKEN=…                         YANTRA_ASK_WAIT=1800
```

A write nothing allowed becomes Dvara's `POST /ask`: the same two
buttons on Telegram, the same card on Sarathi's page. The answer is the
decision.

**THE WAIT IS THE SCHEDULE'S `wait`, AND IT IS NOT THE WORK.** A question
may wait as long as the schedule's `wait` (30 minutes by default) for
the whole run, the same field the Dvara road uses (note 06). The run's
time limit grows by that much, so ten minutes of work doesn't get
killed while its person reads the question. Silence is a refusal.
The Dvara road does the same for every run, not only a phone's
([notes/13](13-a-question-is-not-the-work.md)).

With no Dvara, nothing changes: nobody to ask, and the variables are
removed from what Yantra inherits, so a leftover in the clock's
environment can't point a run at a Dvara this Samay doesn't know.

## `refused` is its own outcome

A run that finished, but was refused a tool on the way (nobody allowed
it, or its person said no), is now `refused`, not `ok`.

**IT IS ALWAYS SAID AS ONE.** Under `when_new` an `ok` reply is sent
only when it's new. A refused one is sent every time, unless the
schedule says `never`, and it ends with what wasn't allowed and the way
out:

```
I couldn't do it. The write_file call to create stairs2.txt was denied —
the owner was asked and said no … The stairs light is **not** off.

Not allowed without asking: write_file.
To let it next time, say so in a chat with me, or run: samay allow bf1d68c0 'write_file'
```

A one-off that has had its time can't run again, so its notice says to
ask for it again instead.

**IT DOES NOT PAUSE THE SCHEDULE.** Failures pause a schedule after
three in a row (note 01). A refusal doesn't count. The run often does
most of its job without the tool it reached for: a digest that wanted
`bash` for one step is still a digest. Pausing it would stop the part
that works. The person hears every time instead, and can allow the tool.

## Allowing a tool later

`samay allow ID TOOL…` adds tools to what a schedule may use unasked,
from its next run. **ADDED, NEVER REPLACED.** The yes given when the
schedule was made still stands; taking a tool away means making a new
schedule. The agent has the same thing as `allow_for_schedule`, a
write, so the person approves it on a card like any other change, and
Yantra's card names each grant and what it reaches.

## A grant can be fixed to one thing

`allow_tools` entries may now fix arguments:
`call_service(domain=switch, service=turn_off,
entity_id=switch.lights_2)` covers the stairs light, not the front
door. Yantra and Dvara read the form (Yantra's `Grant`). Samay checks
its shape when the schedule is saved, so a grant that would be refused
at its time is refused now instead, in words.

## The receipt

Scratch Samay and a scratch Dvara on this machine, the direct road, the
`scribe` package, `qwen3.8:latest`. The job was *write OFF into
stairs.txt*, standing in for the switch. Nothing allowed.

```
$ samay run-now b994fc79           # the question reaches Dvara:
{"asks":[{"tool":"write_file","summary":"NEW FILE stairs.txt (1 lines)",…}]}
                                   # answered yes, as the Telegram button does
Sat 10 Oct 19:08  ok            sent  The stairs light is off. (I wrote "OFF" …

$ samay run-now bf1d68c0           # same job; answered no
Sat 10 Oct 19:12  refused       sent  I couldn't do it. The `write_file` call …
    not allowed: write_file

$ samay allow bf1d68c0 'write_file(path=stairs2.txt)'
bf1d68c0 may now use without asking: write_file(path=stairs2.txt)
$ samay run-now bf1d68c0
Sat 10 Oct 19:16  ok            sent  Stairs light is off. I wrote OFF to stairs2.txt …
                                   # and Dvara's question list stayed empty
```

## Not built

- **Telling a refusal that broke the job from one that didn't.** Both
  are `refused`. The model's reply says which, and the person reads it.
  A rule that guessed would file some broken jobs as done again.
- **Run again now.** The notice for a one-off says to ask the agent. A
  run is an agent turn, minutes long, and `samay run-now` is still the
  person's (note 03), not the model's.
- **Taking a tool away.** `allow` only adds. A schedule that may now do
  less is a different promise, and a new schedule says it plainly.

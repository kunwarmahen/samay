# 08 — A night of your own tests

A conversation that went right can be kept as a test (Yantra's note
141). Its last turn is replayed with the tools answering from what they
said then, so nothing real runs, and the answer is checked three ways:
the tools it used, the words the person gave, and the model's own
judgement against the kept answer. `yantra --tests` runs every suite at
once. Something has to start it every night, and that is a clock's job.

## A road that asks nothing

Every other schedule asks an agent something. This one doesn't, so it
is a third runner beside the direct road and the Dvara road, not a
prompt:

```bash
samay add "the night's kept tests" --when "at 03:00" --runner tests --time-limit 3600
```

The prompt is only the schedule's name. The runner starts
`yantra --tests --json` (with `SAMAY_TESTS_PROVIDER` and
`SAMAY_TESTS_MODEL` when set) and reads the one object it prints,
`yantra.tests.v1`. A shape it doesn't know is refused rather than
guessed at, the same contract as `yantra.run.v1`. A tests schedule
takes no agent, no tools, no phone and no browser profile. It replays
each suite against the agent that suite was kept from, so there is
nothing to give it, and anything given is refused when it is made.

On Samay's page the same road is the third choice under *Run* (*the
kept tests*), and Sarathi's home page has a button that asks Samay's
API for exactly this schedule (Sarathi's note 27).

## Only news is sent

Under `when_new` (note 04), a run whose reply is NOTHING NEW is kept
quiet. The night's reply leads with it unless there is something to
do:

| the night | the logbook | sent |
|---|---|---|
| every suite ran, nothing broke | `quiet`: NOTHING NEW, then the count and anything fixed | no |
| a case was red last night too | `quiet` | no |
| a case broke since last night | `ok`: the count, and which broke, whose agent | yes |
| a suite could not run | `failed`: its reason | counts toward a pause, like any failure |

A case red two nights running isn't news the second night; the first
morning said it. Something fixed goes in the logbook and isn't sent.
A suite that could not run is the one thing that must never look quiet:
a card that says green when it checked less is worse than no card.

## Live receipt

A scratch Samay, the real Yantra, `qwen3.8-64k:latest` on Ollama, two
conversations kept as tests:

```
$ export SAMAY_YANTRA="uv run --project ~/yantra yantra" SAMAY_YANTRA_HOME=~/yantra
$ export SAMAY_TESTS_MODEL=qwen3.8-64k:latest
$ samay add "the night's kept tests" --when "at 03:00" --runner tests --time-limit 3600
$ samay run-now 952910a1
0 of 2 kept tests passed, 1 broke since last time.
· yantra: broke kept-da553c46
```

That took 1.4 s, too fast for a model. With the model given and no
provider, Yantra guessed one from `.env` (`responses`), and every case
crashed with *not a valid model ID*. The night said so loudly instead
of quietly, but the cause was a missing setting, so the road gained
`SAMAY_TESTS_PROVIDER`:

```
$ export SAMAY_TESTS_PROVIDER=ollama
$ samay run-now 952910a1                       # 4 m 19 s
NOTHING NEW
1 of 2 kept tests passed, 1 fixed.
· yantra: fixed kept-da553c46
$ samay runs 952910a1
Fri 23 Oct 07:29  quiet         NOTHING NEW
Fri 23 Oct 07:29  ok            0 of 2 kept tests passed, 1 broke since last time.
```

The case still red is the one whose kept answer was wrong (Yantra's
note 141). It was red the night before, so it wasn't news.

## Tests

`tests/test_tests_road.py` (6):

* it asks Yantra for every kept test as JSON, unattended, with the
  provider and model set;
* something broke is news;
* red that was red yesterday is not;
* a suite that could not run is a failed run with its reason;
* an unknown shape, or nothing printed, is refused;
* a tests schedule takes no agent or tools.

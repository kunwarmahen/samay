# 10 — A run a restart stopped, carried on

A schedule checks the parcel tracker at 09:00 and, if it's arrived,
books the collection. That's a dozen steps on a site. At 09:04 the owner
runs `sarathi down && sarathi up`.

Samay's rule was the safe one: **the next time is claimed before the run
starts**, so a crash never runs the same time again. A run spends money
and may have done something, and running it a second time could pay
twice or book twice. So the run was marked `interrupted` and that was
that. The booking form stayed half filled, and the next try was
tomorrow's 09:00.

Yantra can now carry a stopped turn on from its last saved step (its
note 144). That doesn't break the rule. **Carried on is not run again:**
the steps already done stay done and aren't repeated. The agent is told
it stopped, and looks at the page again before it acts.

## Each run is a Job

The clock sets `JOB` (a context variable, one per worker thread) to the
run's id around `runner.run`. The runners keep their old signature, so a
runner that knows nothing of jobs still works.

* **The direct road** gives Yantra `--job <work>/.jobs/<schedule>-<run>.sqlite`.
  The file sits beside the work folders, never in one, so the agent's own
  tools can't read it. Yantra saves the run there after every step and
  holds `FILE.lock` while it runs. A run that comes back, however it
  ended, has its file deleted. Only a run Samay never saw end leaves one.
* **The Dvara road** names the thread after the run,
  `samay-<schedule>-<run>`, where it used to be named after the clock.
  Dvara saves every step under that thread.

## On start: carry on, or interrupted

`serve` used to mark every `running` run `interrupted`. Now
`carry_on_or_interrupt` looks at each one, and carries it on only when
all of these hold:

* **It's recent.** The run started within the schedule's grace (half its
  step, at most an hour). That's the same window in which a missed time
  still runs. A restart after a night off leaves the run `interrupted`:
  *"it is too long ago to carry on."*
* **Something was saved.** `can_carry` on the direct road reads the job
  file with `sqlite3` alone (Samay imports nothing of Yantra's) and
  wants its newest checkpoint `unfinished`. The Dvara road asks Dvara,
  which answers `stop_reason: "nothing"` when it has no stopped turn in
  the thread.
* **Nothing is still at it.** On plain programs, a Yantra that Samay's
  death left running still holds `FILE.lock`, and is left alone. Two
  Yantras on one job is the double booking this whole rule exists to
  prevent.

A carried-on run keeps its own row, so the logbook still has one row per
time. It ends with its usual outcome and the detail *carried on after a
restart*. With nothing saved, the row says *"nothing was saved to carry
on from; it was not run again."* A road with no `can_carry` (the tests
road, the doctor road) is `interrupted`, as before. Neither has steps to
carry on.

## Receipt

The direct road, by hand, on `qwen3.8:latest` (Yantra's note 144): a
three-step job killed with `SIGKILL` after its first step, then the same
`yantra --job` command:

```
carrying on "Read a.txt, then b.txt, then c.txt, ..." (1 step done: read_file), stopped by a restart
→ read_file()   "path": "b.txt"
→ read_file()   "path": "c.txt"
{"ok": true, "stop_reason": "end_turn", "text": "... Their sum is **50**."}
```

The clock's side is in `tests/test_carry_on.py`, against fake runners:

* a recent run is carried on in its own row;
* a run from 45 minutes ago on an hourly schedule (grace 30) is
  interrupted;
* nothing saved, or a road that says `nothing`, stays interrupted;
* a job file whose lock is held is left alone.

## What was deliberately not built

* **Carrying on a run from a long-stopped Samay.** An hour later the
  parcel's collection slot may be gone. The next time is the schedule's
  own.
* **A second carry-on.** A carried-on run killed again is interrupted on
  the next start if it's past its grace, like any other.

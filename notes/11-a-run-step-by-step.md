# 11 — A run, step by step

A schedule's run went wrong in the night. Its logbook row says
`failed`, maybe with a sentence. To see which step went wrong, what the
agent saw and what it tried, you used to need a terminal and Dvara's
ledger.

Each run on Samay's page now has a **Steps** button in its details. It
shows the run's tools in order: what each was given, what came back,
when, how long it ran, who said yes, and any picture a tool returned.
It's the same `yantra.steps.v1` that Yantra's and Dvara's pages draw
(Yantra's note 145).

## Two roads, one answer

`GET /api/runs/{id}/steps` asks the road that ran it:

* **The Dvara road**: the run has Dvara's run id, so Samay asks Dvara for
  it (`GET /runs/{id}/steps`, with the token it already holds). Dvara
  keeps a schedule's conversation a week (its `tidy`).
* **The direct road**: Samay asks Yantra to read the run's own job file,
  `yantra --steps FILE --json`. It's a program, not an import, as it is
  for every run (runners.py). So the job file a run was given for
  carrying on (note 10) is now **kept after the run**. A finished file
  is never carried on, and files are let go after 30 days
  (`KEEP_JOBS`), checked as each run starts.

A run whose steps are gone says so: *"this run's steps are not kept …"*.
The tests and doctor roads have no steps, and say that too.

## Receipt

From `tests/test_carry_on.py` (`TestSteps`): a direct run's steps read
by a stand-in `yantra --steps`; a Dvara run's asked of a stand-in Dvara at
`GET /runs/d-77/steps`; a file 31 days old let go and a new one kept. The
real `yantra --steps` on a real run is in Yantra's note 145.

## What was deliberately not built

* **Steps for runs from before the job files were kept.** They were
  deleted when the run ended; there's nothing to read.

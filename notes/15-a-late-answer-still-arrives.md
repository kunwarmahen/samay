# 15 — A late answer still arrives

On the Dvara road, Samay waits a run's time limit (and its questions'
wait, note 13) for Dvara's answer, then records `timed_out` and stops
listening. The turn goes on in Dvara, and used to finish into a
connection nobody held: the morning brief that took fifty minutes was
written for nobody.

Every run now tells Dvara what a late answer is for:

| the schedule's `--notify` | `if_late` | if Samay has hung up when the turn ends |
|---|---|---|
| `when_new`, `always` | `send` | Dvara sends the answer to the person's channels |
| `never` | `keep` | it stays in Dvara's run record; nobody is told |

The person sees Samay's *too long* first, and the brief after it,
headed *Finished after Samay had stopped waiting (morning)*. The
timeout sentence says so:

```
no answer from dvara within 2400s (the time limit, 600s, and 30 min
for its questions); the turn may still finish there (dvara runs), and
its answer is sent to you when it does. To give it longer: samay
limits 713aefd8 --time-limit SECONDS, or ask your agent
```

**NOT SENT BY WHEN_NEW'S RULE.** A late answer skips the "only when
it's new" check: Samay has no answer to compare. A schedule that wants
quiet says `never`.

**SAMAY STILL SAYS TIMED_OUT.** The logbook records what Samay saw.
Dvara's run log has the turn, its steps and its answer. A late answer
is a sign the limit is wrong; `samay limits` (note 14) is the fix that
puts the answer back in Samay's own record.

An older Dvara ignores `if_late`, so the two can be updated in either
order. How Dvara tells a caller has gone is in Dvara's notes/76.

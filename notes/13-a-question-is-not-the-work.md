# 13 — A question is not the work

A weekday morning brief on the Dvara road (`morning` agent, 07:30,
the default ten-minute limit) came back `timed_out` two mornings
running:

```
too long
no answer from dvara within 600s, the time limit for this schedule;
the turn may still finish there (dvara runs)
```

Dvara's run log said both turns did finish, just later than Samay
waited:

| morning | turn took | of which waiting for a yes | tool calls |
|---|---|---|---|
| first  | 20 min | 76 s | 34 |
| second | 50 min | 30 min (nobody answered) | 31 |

Both briefs were written, and neither reached the person: Samay had
already stopped listening.

## Two causes, one of them Samay's

**THE WAITING IS NOT THE WORK, ON EVERY RUN.** Note 06 gave a phone run
its waiting on top of the limit. Note 07 did the same for the direct
road's questions. The Dvara road without a phone was left out, but any
turn can stop for a yes, and Dvara holds its questions to the
schedule's `wait`. So on the second morning, one unanswered question
used up the whole ten minutes and more. The call to Dvara now gets
`time_limit + wait` (and a phone run gets `time_limit + 10 min + 2 ×
wait`, as before). The timeout sentence names both parts:

```
no answer from dvara within 2400s (the time limit, 600s, and 30 min
for its questions); the turn may still finish there (dvara runs)
```

**TEN MINUTES IS A CLOUD MODEL'S TEN MINUTES.** Even without the
question, the first morning was about nineteen minutes of real work:
`qwen3.8-64k:latest` on this machine, reading mail, calendar, three
brokerage accounts and Notion through 34 tool calls. A limit is the
schedule's own, so this one was raised to 30 minutes. There is no
command to change a schedule's limit after it is made yet. The agent
that makes a schedule can't set it either.

The question itself was the agent's copy, not Samay. The installed
`morning` agent had lost the `[tools] allow` list its example ships
with, so it had `bash`, and the local model reached for it each
morning. The list was put back. A brief that only reads should have
nothing to ask.

## What was deliberately not built

* **Collecting the answer after a timeout.** The turn that finishes in
  Dvara after Samay gave up is still lost to the person. Asking Dvara
  for it later (by its thread) would fix that for good, but it is a
  second call path and a second record of the same run. A limit that
  fits the work comes first.

# 02 — As the person

[Note 01](01-a-clock-and-a-logbook.md) built the clock and the direct
road: Samay starts Yantra as a program on the same machine, with nobody
attached, and writes down what came back. That does the work, and stops
there. A run on the direct road can't reach the person it's for, isn't
charged to anybody's allowance, and doesn't see the rules the owner
wrote. If it needs a yes, the only possible answer is no.

All three of those already exist in Dvara, the service the person's
agents live behind. So the second road doesn't build them again. It
runs the turn *in Dvara*, as that person:

```
samay ── POST /message ──▶ dvara ──▶ yantra turn, as "mahen"
  {actor: "mahen", agent: "scribe", unattended: true,
   allow_tools: ["write_file"], thread: "samay-4dd8ac19-1791163020"}
                                       │ their allowance pays
                                       │ the owner's rules apply
                                       │ a question goes to their Telegram
samay ◀── reply (+ needs_person, busy, refused, held, run_id) ──┘
  │ worth telling?
  └── POST /notify {actor: "mahen", text} ──▶ dvara ──▶ their channels
```

## What "allowed ahead of time" may grant

When the person accepts "every 6 hours, write a line to log.txt", they
have said yes to `write_file` before the call exists. On the direct
road that's `--allow-tools`, and it works because nothing else stands
between the run and the tool. In Dvara there's more: a rung (the mode
the package, owner and person agree on), standing rules, and a desk
that puts questions to people.

Dvara already had a rule about standing answers: **`allow` grants
nothing the rung would not have been willing to ASK about**. An answer
given ahead of time is the same kind of thing, so it goes in the same
place: the start of `gate.put`, the one function a question is put
from. A call only gets there if the person *could* have been asked,
which settles every edge case:

* **a deny rule still refuses**, because deny is decided before any
  question;
* **a read-only person is never answered for**. They're never asked,
  so `put` is never reached;
* **a Dvara started without `--ask` grants nothing**. With no desk
  there's nobody to ask, so there's nothing to answer ahead of time;
* **a tool that asks on every call still asks**. That's Yantra's
  `always_ask`, the same rule `--yolo` follows.

And it's on the record. `dvara runs` marks the call `[ahead]`, beside
`[rule:…]` and `[asked:telegram]`, so "why did this run without
asking me?" has an answer:

```
2026-10-05 01:17  owner/scribe  end_turn  $0.0000  '(A scheduled run -- every 6 hours. Nobody is wat'
                  read_file -> write_file[ahead]
```

A tool *not* named is put to the person, as it would be for any turn.
If nobody answers in time and the owner runs Dvara with
`--on-timeout hold`, the turn waits for them (Dvara's note 16). Samay
records that run as **`held`**. It isn't a failure, and it sends
nothing more, because the person was already asked on their channel:

```
Sun 4 Oct 21:18  held   Nobody answered in time, so this is waiting for your approval and not…
$ dvara held
lVxSFx5_…  owner/scribe  thread samay-678740c0-1791163084  run 58b8c388a0a9
    call_dfah3uxz  write_file: NEW FILE log2.txt (1 lines)
```

## Telling someone who didn't ask

Everything Dvara sent before this was an *answer*. Somebody wrote, a
turn ran, the reply went back to where the message came from. A
scheduled run has nowhere to reply to, because nobody wrote. So Dvara
grew one new direction: **`POST /notify`**, which takes a person and a
text and sends it to that person's channels from the actors file. That
is the same place a question for them goes.

**SAMAY DECIDES WHETHER, DVARA ONLY SENDS.** `/notify` knows nothing
about schedules, `NOTHING NEW` or pausing. That logic stays in Samay's
clock, so any other program that needs to tell a person something can
use the same endpoint.

A Telegram bot running inside Dvara sends a notice straight away, split
the way an answer is. A channel served by an adapter in *another*
process collects its notices from `GET /notices?channel=KIND`, each
handed over once. If a send fails, the text is kept for collection
rather than lost. A notice is kept **in memory**, and that's stated
plainly: a restart drops whatever wasn't collected. Samay's run log is
the durable record, and it shows which runs were `sent`.

The person a direct-road schedule belongs to is "local", which Dvara
has never heard of. `SAMAY_DVARA_ACTOR` names who that is, so a
schedule run on this machine can still send its answer to someone's
phone.

## A fresh conversation every run

Each run is its own Dvara thread, `samay-<schedule>-<time>`. A
schedule that has run four hundred times would otherwise bring four
hundred answers into its next turn, and pay for them every time.
What the agent needs from the last run, Samay puts in the prompt
(note 01). The tradeoff is that Dvara keeps a small session per run.
Pruning old `samay-*` threads isn't built yet.

## One turn's record, not the process's

Yantra's unattended record — what the run needed, what was busy, what
was refused — used to belong to the process. That was fine for a
one-shot run, which *is* a process, and wrong for Dvara, which serves
many turns at once. Two scheduled turns would have reported each
other's sign-in walls. Yantra now gives each turn its own record
(`unattended.scope()`, a context variable), and Dvara opens one around
every unattended turn. The browser carries it onto its own worker
thread, so a busy profile lands on the turn that found it.

## Checked when it is made

A Dvara-road schedule is checked against Dvara when you add it, not at
08:00 the next morning:

```
$ samay add "x" --when "every 6h" --runner dvara --agent nope --as owner
error: dvara has no agent 'nope'; it offers: greeter, scribe
$ samay add "x" --when "every 6h" --runner dvara --agent scribe
error: say who this runs as: --as ACTOR (someone in Dvara's actors file), or set SAMAY_DVARA_ACTOR
```

## Receipts

Run against `qwen3.8:latest` through Ollama. `dvara serve` used the
example `scribe` agent with `--ask --ask-timeout 20 --on-timeout hold`,
and the person's only channel was one nothing in that process serves,
so notices waited to be collected instead of going to a real phone.

`write_file` allowed ahead of time (36 seconds):

```
$ samay add "Write the word 'checked' and the current time into log.txt, then say
             in one sentence what you wrote." --when "every 6h" \
        --runner dvara --agent scribe --as owner --allow-tools write_file --notify always
$ samay run-now 4dd8ac19
Sun 4 Oct 21:17  ok            sent  I wrote 'checked' plus the current time (≈ 2026-10-05 01:17 UTC) into…
$ curl -H "Authorization: Bearer $TOKEN" "localhost:8799/notices?channel=signal"
{"notices":[{"id":"aeab6950","actor":"owner","channel":"signal","to":"me",
  "text":"I wrote 'checked' plus the current time (≈ 2026-10-05 01:17 UTC) into a freshly created log.txt.", ...}]}
```

Not allowed, nobody answering: `held` after the 20-second ask, shown
above.

## What was deliberately not built

* **Samay holding a Telegram token.** One bot per token. A second
  poller on the same token splits the person's messages between two
  processes (Dvara's note 07), and the channels already live in Dvara.
* **Cancelling a turn that runs past the time limit.** Samay stops
  waiting and records `timed_out`, but the turn may still finish in
  Dvara, and the detail says so. A cancel endpoint would let one
  program stop another person's turn. That's a bigger decision than a
  timeout.
* **Durable notices.** See above: Samay's run log is the record.

The page where a person sees all of this, and the tools their agent
uses to offer a schedule in the first place, are
[note 03](03-offered-then-accepted.md).

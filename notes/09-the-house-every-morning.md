# 09 — The house, every morning

Sarathi's doctor (its note 28) says what's wrong in the house, each line
with the thing that fixes it: a stopped piece, a phone unplugged, an
image older than the code, a Google sign-in ending in two days, the
iPhone's signature running out. Asked when somebody remembers to ask,
it finds trouble the morning after it started. Starting it every
morning is a clock's job, so it's a fourth road beside direct, Dvara and
the kept tests (note 08):

```bash
samay add "the house, checked by Sarathi's doctor" --when "at 07:30" --runner doctor
```

## Over HTTP, not as a program

The tests road starts `yantra --tests` as a program. The doctor can't be
run that way, because it looks at the computer itself: systemd units,
Podman's images, the firewall, the free disk. On the Podman road Samay
runs in a container, where none of those can be seen. So the doctor
answers on the host, at Sarathi's home page (`GET /api/doctor`), and
this road asks it there. `SAMAY_DOCTOR_URL` says where (from a container,
`host.containers.internal`), and `SAMAY_DOCTOR_TOKEN` is the key.
`sarathi up` sets both.

That key is not the home page's. The home page's token opens every
page's key and the chat. A key Samay holds opens the doctor's answer
and nothing else, and Sarathi's tests check that it gets 401 everywhere
else.

## Only what's new

The road asks with `?news=1`. The doctor then also says which red and
amber lines weren't there the last time it was asked that way, and
which are gone, and it remembers this answer for the next morning:

| the morning | the reply | sent (`when_new`) |
|---|---|---|
| something new is wrong | `0 to fix, 5 worth a look, 8 fine. New since last time:` and each new line with its `fix:` | yes |
| the same problems as yesterday | `NOTHING NEW`, the counts | no |
| something was fixed, nothing new | `NOTHING NEW`, the counts, `Fixed since last time: …` | no |
| the doctor can't be reached, or answers in a shape Samay doesn't know | a failed run, with why | as any failed run |

A phone left unplugged all week is said on Monday, not every morning.
Only the morning road updates what was told. Pressing **Check** on the
home page asks without `news`, so looking doesn't eat the morning's
news.

## Live receipt

On a scratch state folder, against a scratch Sarathi home page on this
house (port 8797), `samay run-now` twice:

```
== run 1
Fri 23 Oct 09:41  ok            0 to fix, 5 worth a look, 8 fine. New since last time: …
· worth a look -- setu: gmail:personal: Google ends this sign-in Sun 25 Oct 22:44 (an app in Testing ...)
  fix: sign in again before then: setu connect gmail --as personal; or publish the Google app, ...
· worth a look -- phone: nexus isn't connected: not answering over Wi-Fi -- ...
  fix: plug it in by cable, then Bring it back (or `sparsh tcpip`)
...
== run 2
Fri 23 Oct 09:41  quiet         NOTHING NEW
```

The second run was quiet, as it should be. The scratch run's memory of
what was told was deleted afterwards, so the real first morning starts
fresh.

## Not here

* No choice of hour on Sarathi's button (07:30). Change the schedule on
  Samay's page.
* Each person behind Dvara doesn't get their own doctor. The house has
  one owner, and the doctor's lines are the owner's to act on.

The same road, for the night's backup: [12 — the house, backed up every
night](12-the-house-backed-up-every-night.md).

Tests: `tests/test_doctor_road.py` (7).

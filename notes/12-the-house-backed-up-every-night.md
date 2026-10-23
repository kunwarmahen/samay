# 12 — The house, backed up every night

Sarathi makes a backup of the house: every program's own files in one
locked file (`sarathi backup`, its note 29). A backup made when somebody
remembers is the one from three weeks ago on the day a disk dies.
Making one every night is a clock's job, so it is a fifth road beside
direct, Dvara, the kept tests (note 08) and the doctor (note 09):

```bash
samay add "the house, backed up" --when "at 02:30" --runner backup
```

or, on Sarathi's home page, Settings → Check → **Back up every night**.

## The doctor road's twin

Like the doctor, the backup is made by Sarathi, not by Samay. It asks
each program what it keeps, dumps Smritikosh's database from its
container and writes into a folder on the computer, and Samay may be in
a container that sees none of that. So the road is one HTTP call:
`POST $SAMAY_BACKUP_URL` with `$SAMAY_BACKUP_TOKEN`, both set by
`sarathi up`. It waits as long as the schedule's time limit allows
(the button's schedule: an hour).

**A KEY THAT MAKES A BACKUP AND OPENS NOTHING.** The backup key opens
`POST /api/backup` and nothing else: no page, no settings, no doctor.
Each backup is sealed to a public key, so no passphrase is anywhere in
Samay, and a Samay that leaked would leak a key that makes another
backup.

## Quiet when it worked

A night that went well is `NOTHING NEW`, with where it went:

```
NOTHING NEW
Backed up: ~/sarathi-backups/sarathi-beast-20261024-023000.sarathi-backup (512.3 MB); 1 older removed.
```

A `when_new` schedule therefore says nothing on a good night. Everything
else is a failed run that says why, in Sarathi's own words where it has
them:

* a backup made without part of the house (*"· not in it: Smritikosh's
  database isn't running…"*);
* no passphrase chosen yet (*"run `sarathi backup` once at a terminal to
  choose it"*);
* Sarathi unreachable, or an answer this Samay can't read
  (`sarathi.backup.made.v1` is the only shape it believes).

## Live receipt

Against a scratch Sarathi home page (a house made by hand, on port
18760), Samay's own `BackupRunner`:

```
ok: True | stop: backup | detail:
NOTHING NEW
Backed up: …/backups/sarathi-…-165523.sarathi-backup (60.6 KB); 1 older removed.
wrong key -> ok: False | the backup wasn't made: missing or wrong token, or signed out
```

## Not here

* No choice of hour on Sarathi's button (02:30, before the kept tests
  at 03:00). Change the schedule on Samay's page.
* A backup road for each person behind Dvara: there is one house and
  one backup, the owner's.

Tests: `tests/test_backup_road.py` (6).

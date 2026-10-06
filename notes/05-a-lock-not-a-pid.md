# 05 — A lock, not a pid

"Is the clock running?" has two askers. `samay serve` asks it before
starting, so there's never a second clock running every schedule twice.
`samay status` asks it for whoever wants to know, Yantra's page among
them, so a schedule made while nothing serves comes with a warning.

The answer used to be a pid. `samay serve` wrote its process id to
`serve.json`, and the question was "is that process alive?"
(`os.kill(pid, 0)`). On one desktop that's usually right. Run in
containers, it fails both ways.

## Wrong after a crash

Kill the clock with `-9`, or let the machine lose power, and
`serve.json` stays behind. Its pid now names nothing, or names something
else. In a container it's worse than unlucky. A fresh container numbers
its processes from 1 again, so the dead clock's pid is often the new
clock's own. The new `samay serve` checks, finds "itself" alive, and
refuses:

```
error: samay serve is already running for /home/mahen/.samay
sarathi-clock.service: Start request repeated too quickly.
```

That's what happened when Sarathi ran the clock as a systemd unit and
the container was killed. systemd restarted it four times, each refused
by its own pid, and gave up. A clock that can't come back after a crash
is exactly what a unit with `Restart=on-failure` exists to prevent.

## Wrong from another container

A pid means something only inside its own pid namespace. Yantra's page,
in a container of its own, checking the clock's pid, gets "not running"
for a clock that is running, and warns the person on every schedule.
The workaround was to put the page in the clock's namespace, which tied
the two containers together so tightly that Podman then refused to
replace the clock while the page still existed.

## The kernel already knows

**THE CLOCK HOLDS A LOCK FOR AS LONG AS IT RUNS.** `samay serve` takes
an exclusive `flock` on `serve.lock` and keeps the file open until it
exits. "Is it serving?" becomes "is that lock held?". The kernel answers
that question, and it is right in every case the pid was wrong:

* **however the holder dies** (`-9`, a crash, power), the lock goes with
  it. A stale `serve.json` changes nothing;
* **whichever namespace asks**, the same file on the same disk has the
  same lock. Another container mounting `~/.samay` sees it;
* **taking it is the check.** The old "is it running? no? then write
  the file" had a gap between the two, and two `samay serve` started
  together could both get through it. `LOCK_NB` either takes the lock or
  fails, in one step.

`serve.json` still holds the page's address, which `status` reports.
It's information now, not evidence.

## Live receipt

A real `samay serve`, a second one, a `kill -9`, and a restart:

```
status: True
second: error: samay serve is already running for .../tmp.PROKkgPg8A
after kill -9: False  serve.json still there: yes
restart: samay 0.1.0: 0 active schedule(s), state in .../tmp.PROKkgPg8A
```

The tests (`tests/test_serve_lock.py`) cover the case that started
this: a `serve.json` naming a pid that is alive, the test's own, is not
a running clock.

## What it doesn't cover

`flock` needs one kernel. Two machines sharing `~/.samay` over NFS
would each see only their own lock. Samay keeps its state on the
machine it runs on, and that's still the rule.

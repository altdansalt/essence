# systemd units for the essence loop

These run the porting loop on a schedule: one language per firing, committed
and pushed.

- `essence-loop.service` — oneshot: runs `tools/loop.py --limit 1`.
- `essence-loop.timer` — fires every 20 minutes (after boot, and persistently).

## Install (user systemd)

```sh
mkdir -p ~/.config/systemd/user
cp systemd/essence-loop.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now essence-loop.timer
# check:
systemctl --user list-timers essence-loop.timer
journalctl --user -u essence-loop.service -f
tail -f logs/cron.log
```

To run a few languages at once instead of one per firing, edit the service's
`ExecStart` to `--limit 5` (or remove `--limit` for all remaining).

To stop: `systemctl --user disable --now essence-loop.timer`.

## Why a timer, not cron(8)

User systemd timers give us per-run logging via journald, `Persistent=true`
(catches up if the VM was off), and a clean oneshot lifecycle. The loop is
idempotent (skips slugs that already have `runs/<slug>/meta.json`), so repeated
firings just advance through the language set.

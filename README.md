# CTFd Challenge Scheduler

Lets an admin set, per challenge, an offset from the competition's start
time (CTFd's own `start` config, set under Admin &rarr; Config &rarr; Time)
at which the challenge should automatically become visible.

- Offset `0:00` &rarr; visible the moment the CTF starts.
- Offset `3:00` &rarr; visible 3 hours after start.
- No schedule entry &rarr; challenge stays under normal manual control, untouched.

This plugin only ever flips a challenge **hidden &rarr; visible** once its
scheduled time has passed. It never hides anything.

## How it works
- Adds a `challenge_schedule` table (`challenge_id`, `offset_seconds`, `released_at`).
- Admin page at `/admin/challenge-schedule` lists every challenge with an
  editable `H:MM` offset field and a Save button.
- The due-check runs on every request (`app.before_request`), not a
  background thread — during an active CTF, traffic is constant, so
  challenges unlock within a few seconds of their scheduled time with no
  extra process or dependency (e.g. APScheduler) required.
- Reads the start time via CTFd's own `get_config("start")` /
  `ctf_started()` helpers, so it stays in sync with the same setting CTFd
  itself uses for freezing the scoreboard etc.

## Install
1. Copy this directory to `CTFd/CTFd/plugins/ctfd-challenge-scheduler/` on
   the server running CTFd.
2. Restart CTFd. `app.db.create_all()` creates the `challenge_schedule`
   table automatically on first start.
3. Set your CTF's start time under Admin &rarr; Config &rarr; Time if you
   haven't already.
4. Visit `/admin/challenge-schedule`, set offsets, Save.

## Verification performed
Tested against a disposable local CTFd + MariaDB instance:
- 3 challenges created hidden, `start` config set to "now".
- Offsets saved: `0:00`, `0:02`, `1:00`.
- Immediately after saving: the `0:00` challenge was visible, the other
  two still hidden.
- Waited past the 2-minute mark: the `0:02` challenge flipped to visible
  on its own (via ordinary page-load traffic hitting `before_request`),
  while the `1:00` challenge correctly remained hidden throughout.

An earlier version's save form was missing CTFd's CSRF nonce hidden
field entirely — harmless in isolation, but would have made the Save
button silently fail with a 403 for every real admin, not just script
testing. Fixed by reading `session["nonce"]` server-side and rendering
it as a hidden `<input name="nonce">`, matching how CTFd's own
login/register/setup forms do it.

"""
CTFd Challenge Scheduler
-------------------------
Lets an admin set, per challenge, an offset from the competition's start
time (CTFd's own "start" config, set under Admin > Config > Time) at
which the challenge should automatically become visible. e.g. an offset
of 0:00 reveals it the moment the CTF starts; an offset of 3:00 reveals
it 3 hours after start.

This never hides a challenge -- it only flips hidden -> visible once its
scheduled time has passed. Challenges with no schedule entry are
completely unaffected (manual admin control as normal).

The check runs on every request (cheap query against a handful of rows)
rather than a background scheduler thread, so no extra process/dependency
is needed -- during an active CTF, traffic is constant, so reveals land
within a few seconds of their scheduled time.
"""
import re
from datetime import datetime

from flask import Blueprint, redirect, render_template, request, session, url_for

from CTFd.models import Challenges, db
from CTFd.utils import get_config
from CTFd.utils.dates import ctf_started
from CTFd.utils.decorators import admins_only

OFFSET_RE = re.compile(r"^(\d+):([0-5]\d)$")


class ChallengeSchedule(db.Model):
    __tablename__ = "challenge_schedule"

    challenge_id = db.Column(
        db.Integer, db.ForeignKey("challenges.id"), primary_key=True
    )
    offset_seconds = db.Column(db.Integer, nullable=False, default=0)
    released_at = db.Column(db.DateTime, nullable=True)

    challenge = db.relationship(
        "Challenges", foreign_keys="ChallengeSchedule.challenge_id", lazy="joined"
    )


def _parse_offset(value):
    """Parse 'H:MM' (hours:minutes since CTF start) into seconds. Returns
    None for a blank value (meaning: unschedule / no auto-release)."""
    value = (value or "").strip()
    if not value:
        return None
    m = OFFSET_RE.match(value)
    if not m:
        raise ValueError(f"Invalid offset '{value}', expected H:MM (e.g. 3:00)")
    hours, minutes = int(m.group(1)), int(m.group(2))
    return hours * 3600 + minutes * 60


def _format_offset(seconds):
    hours, minutes = divmod(seconds // 60, 60)
    return f"{hours}:{minutes:02d}"


def _release_due_challenges():
    if not ctf_started():
        return

    start = int(get_config("start") or 0)
    now = int(datetime.utcnow().timestamp())

    pending = ChallengeSchedule.query.filter(
        ChallengeSchedule.released_at.is_(None)
    ).all()

    changed = False
    for sched in pending:
        if now >= start + sched.offset_seconds:
            challenge = Challenges.query.get(sched.challenge_id)
            if challenge and challenge.state != "visible":
                challenge.state = "visible"
                db.session.add(challenge)
            sched.released_at = datetime.utcnow()
            db.session.add(sched)
            changed = True

    if changed:
        db.session.commit()


scheduler_bp = Blueprint(
    "challenge_scheduler", __name__, template_folder="templates"
)


@scheduler_bp.route("/admin/challenge-schedule", methods=["GET"])
@admins_only
def view_schedule():
    challenges = Challenges.query.order_by(
        Challenges.category, Challenges.name
    ).all()
    schedules = {
        s.challenge_id: s for s in ChallengeSchedule.query.all()
    }

    rows = []
    for c in challenges:
        sched = schedules.get(c.id)
        rows.append(
            {
                "challenge": c,
                "offset_display": _format_offset(sched.offset_seconds)
                if sched
                else "",
                "released_at": sched.released_at if sched else None,
            }
        )

    start_ts = get_config("start")
    start_display = (
        datetime.utcfromtimestamp(int(start_ts)).strftime("%Y-%m-%d %H:%M:%S")
        if start_ts
        else None
    )
    return render_template(
        "schedule.html",
        rows=rows,
        start_display=start_display,
        ctf_started=ctf_started(),
        nonce=session.get("nonce"),
    )


@scheduler_bp.route("/admin/challenge-schedule", methods=["POST"])
@admins_only
def save_schedule():
    errors = []
    for key, value in request.form.items():
        if not key.startswith("offset_"):
            continue
        challenge_id = int(key[len("offset_") :])

        try:
            offset_seconds = _parse_offset(value)
        except ValueError as e:
            errors.append(str(e))
            continue

        existing = ChallengeSchedule.query.get(challenge_id)

        if offset_seconds is None:
            # Blank input: unschedule (remove any existing row)
            if existing:
                db.session.delete(existing)
            continue

        if existing:
            existing.offset_seconds = offset_seconds
            existing.released_at = None  # re-arm on edit
        else:
            db.session.add(
                ChallengeSchedule(
                    challenge_id=challenge_id, offset_seconds=offset_seconds
                )
            )

    db.session.commit()

    # Apply immediately in case the new schedule is already due
    _release_due_challenges()

    return redirect(url_for("challenge_scheduler.view_schedule", saved=1))


def load(app):
    app.db.create_all()

    @app.before_request
    def _check_challenge_schedule():
        _release_due_challenges()

    app.register_blueprint(scheduler_bp)

    try:
        from CTFd.plugins import register_admin_plugin_menu_bar

        register_admin_plugin_menu_bar(
            title="Challenge Schedule", route="/admin/challenge-schedule"
        )
    except ImportError:
        pass

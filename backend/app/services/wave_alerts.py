"""Wave alert emails: tell subscribers when a new wave forms on the board.

The founder's ORCL trade is the product thesis: peers rip, the next name in
the group re-prices before it reports. When the daily refresh finds new wave
targets, this emails every opted-in Pro user so they get their shot at the
same setup without watching the board all day.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import subscription_is_active
from app.config import Settings, get_settings
from app.db.models import User
from app.services.auth_email import resend_configured, send_email
from app.services.waves import RIP_MOVE_PCT, filter_by_min_peers

logger = logging.getLogger(__name__)

# Keep the email scannable: full detail for a handful of waves, names for the rest.
MAX_DETAILED_TARGETS = 5


def unsubscribe_sig(email: str, secret: str) -> str:
    """HMAC so the one-click unsubscribe link can't flip other people's prefs."""
    msg = f"wave-alerts:{email.strip().lower()}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def summarize_wave_targets(payload: dict | None) -> list[dict]:
    """Collapse a waves board payload into one summary per target.

    Returns dicts with: target, target_name, target_report_date, peers
    (ticker, move_pct, beat), ripped_count, avg_expected_runup_pct,
    best (win_rate, sample_size), themes (labels).
    """
    if not payload:
        return []
    signals = filter_by_min_peers(list(payload.get("signals") or []))
    by_target: dict[str, list[dict]] = {}
    order: list[str] = []
    for s in signals:
        target = str(s.get("target") or "").upper()
        if not target:
            continue
        if target not in by_target:
            by_target[target] = []
            order.append(target)
        by_target[target].append(s)

    out: list[dict] = []
    for target in order:
        group = by_target[target]
        first = group[0]
        peers = []
        seen: set[str] = set()
        ripped = 0
        expected: list[float] = []
        best_stats: dict = {}
        best_score = -1.0
        themes: list[str] = []
        for s in group:
            trig = str(s.get("trigger") or "").upper()
            move = s.get("trigger_move_pct")
            if trig and trig not in seen:
                seen.add(trig)
                peers.append(
                    {"ticker": trig, "move_pct": move, "beat": s.get("trigger_beat")}
                )
                if move is not None and move >= RIP_MOVE_PCT:
                    ripped += 1
            if s.get("expected_runup_pct") is not None:
                expected.append(float(s["expected_runup_pct"]))
            stats = s.get("stats") or {}
            score = float(stats.get("score") or 0)
            if score > best_score:
                best_score = score
                best_stats = stats
            for t in s.get("shared_themes") or []:
                label = t.get("label")
                if label and label not in themes:
                    themes.append(label)
        out.append(
            {
                "target": target,
                "target_name": first.get("target_name"),
                "target_report_date": first.get("target_report_date"),
                "peers": peers,
                "peer_count": len(peers),
                "ripped_count": ripped,
                "avg_expected_runup_pct": (
                    round(sum(expected) / len(expected), 4) if expected else None
                ),
                "best_win_rate": best_stats.get("win_rate"),
                "best_sample_size": best_stats.get("sample_size"),
                "themes": themes,
            }
        )
    # Most "alive" waves first: peers actually ripping, then the soonest report.
    out.sort(
        key=lambda w: (
            -w["ripped_count"],
            w["target_report_date"] or "9999-99-99",
        )
    )
    return out


def _fmt_pct(value: float | None, *, signed: bool = True) -> str:
    if value is None:
        return "n/a"
    sign = "+" if signed and value >= 0 else ""
    return f"{sign}{value * 100:.1f}%"


def _fmt_date(value: str | None) -> str:
    if not value:
        return "soon"
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%a %b %d")
    except ValueError:
        return value


def _peer_line(peers: list[dict]) -> str:
    parts = []
    for p in peers[:4]:
        move = p.get("move_pct")
        chunk = p["ticker"]
        if move is not None:
            chunk += f" {_fmt_pct(move)}"
        if p.get("beat") is True:
            chunk += " (beat)"
        parts.append(chunk)
    if len(peers) > 4:
        parts.append(f"+{len(peers) - 4} more")
    return ", ".join(parts)


def _target_text(w: dict) -> str:
    name = f" ({w['target_name']})" if w.get("target_name") else ""
    lines = [
        f"{w['target']}{name} reports {_fmt_date(w.get('target_report_date'))}.",
        f"Peers already reported: {_peer_line(w['peers'])}.",
    ]
    if w.get("avg_expected_runup_pct") is not None:
        stat = f"Historical run-up into its print: {_fmt_pct(w['avg_expected_runup_pct'])} avg"
        if w.get("best_win_rate") is not None and w.get("best_sample_size"):
            stat += (
                f" (best peer: win {_fmt_pct(w['best_win_rate'], signed=False)}"
                f", n={w['best_sample_size']})"
            )
        lines.append(stat + ".")
    return "\n".join(lines)


def _target_html(w: dict) -> str:
    name = f" <span style='color:#666'>({w['target_name']})</span>" if w.get("target_name") else ""
    ripped = (
        f" · {w['ripped_count']} ripped" if w.get("ripped_count") else ""
    )
    stat_html = ""
    if w.get("avg_expected_runup_pct") is not None:
        stat = f"Historical run-up into its print: <strong>{_fmt_pct(w['avg_expected_runup_pct'])}</strong> avg"
        if w.get("best_win_rate") is not None and w.get("best_sample_size"):
            stat += (
                f" (best peer: win {_fmt_pct(w['best_win_rate'], signed=False)}"
                f", n={w['best_sample_size']})"
            )
        stat_html = f"<br>{stat}."
    return (
        "<p style='margin:0 0 14px'>"
        f"<strong>{w['target']}</strong>{name} reports {_fmt_date(w.get('target_report_date'))}"
        f"<span style='color:#666'> · {w['peer_count']} peers reported{ripped}</span><br>"
        f"Peers: {_peer_line(w['peers'])}."
        f"{stat_html}"
        "</p>"
    )


def _recipients(db: Session, settings: Settings) -> list[User]:
    users = db.scalars(select(User).where(User.wave_alerts.isnot(False))).all()
    return [
        u
        for u in users
        if subscription_is_active(
            email=u.email,
            status=u.subscription_status,
            period_end=u.current_period_end,
            settings=settings,
        )
    ]


def send_wave_alert_emails(
    db: Session,
    *,
    prev_waves: dict | None,
    new_waves: dict,
    settings: Settings | None = None,
) -> int:
    """Email opted-in subscribers about wave targets that just appeared.

    Returns the number of emails sent. Never raises.
    """
    settings = settings or get_settings()
    if not settings.email_wave_alerts or not resend_configured(settings):
        return 0
    # First snapshot after a deploy isn't "new" - only alert on real diffs,
    # mirroring the Telegram setup alerts.
    if prev_waves is None:
        return 0

    prev_targets = {w["target"] for w in summarize_wave_targets(prev_waves)}
    fresh = [
        w for w in summarize_wave_targets(new_waves) if w["target"] not in prev_targets
    ]
    if not fresh:
        return 0

    recipients = _recipients(db, settings)
    if not recipients:
        return 0

    base = (settings.public_app_url or "").rstrip("/") or "https://www.earningsfollower.com"
    board = f"{base}/boards?tab=waves"

    tickers = [w["target"] for w in fresh]
    if len(tickers) == 1:
        subject = f"Wave forming into {tickers[0]}"
    else:
        subject = f"Waves forming into {', '.join(tickers[:3])}"
        if len(tickers) > 3:
            subject += f" +{len(tickers) - 3} more"

    detailed = fresh[:MAX_DETAILED_TARGETS]
    rest = fresh[MAX_DETAILED_TARGETS:]

    # Proof from resolved waves so the email sells with receipts, not adjectives.
    proof = ""
    try:
        from app.services import board_snapshots, wave_receipts

        proof = (
            wave_receipts.receipts_proof_line(
                board_snapshots.get_snapshot(
                    db, "wave_receipts", board_snapshots.wave_receipts_key()
                )
            )
            or ""
        )
    except Exception:  # noqa: BLE001 - proof line is optional garnish
        proof = ""

    intro_text = (
        "Peers just reported and these names are still waiting on their own print. "
        "That's a wave: the setup this site was built on.\n\n"
    )
    body_text = intro_text + "\n\n".join(_target_text(w) for w in detailed)
    if rest:
        body_text += "\n\nAlso on the board: " + ", ".join(w["target"] for w in rest)
    if proof:
        body_text += f"\n\n{proof}"
    body_text += f"\n\nOpen the live board:\n{board}\n"

    intro_html = (
        "<p>Peers just reported and these names are still waiting on their own "
        "print. That's a <strong>wave</strong>: the setup this site was built on.</p>"
    )
    body_html = intro_html + "".join(_target_html(w) for w in detailed)
    if rest:
        body_html += (
            "<p style='color:#666'>Also on the board: "
            + ", ".join(w["target"] for w in rest)
            + "</p>"
        )
    if proof:
        body_html += f"<p style='color:#444'>{proof}</p>"
    body_html += f"<p><a href='{board}'>Open the live Waves board</a></p>"

    sent = 0
    for user in recipients:
        email = user.email
        # One-click unsubscribe hits the API directly with a signed link; when
        # the API origin or secret isn't configured, the account page works too.
        if settings.api_public_url and settings.auth_secret:
            sig = unsubscribe_sig(email, settings.auth_secret)
            unsub_link = (
                f"{settings.api_public_url.rstrip('/')}/waves/alerts/unsubscribe"
                f"?email={email}&sig={sig}"
            )
        else:
            unsub_link = f"{base}/account"
        footer_text = (
            f"\nYou get wave alerts because your Pro account has them on. "
            f"Turn off: {unsub_link}\nNot advice; history and sample sizes are on the board."
        )
        footer_html = (
            "<p style='color:#666;font-size:12px'>You get wave alerts because your "
            f"Pro account has them on. <a href='{unsub_link}'>Turn off wave alerts</a>. "
            "Not advice; history and sample sizes are on the board.</p>"
        )
        ok = send_email(
            settings,
            to=email,
            subject=subject,
            text=body_text + footer_text,
            html=body_html + footer_html,
        )
        if ok:
            sent += 1
    logger.info(
        "Wave alert emails: %d new target(s), %d/%d sent",
        len(fresh),
        sent,
        len(recipients),
    )
    return sent

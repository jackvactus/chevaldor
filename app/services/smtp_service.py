"""Service SMTP + logs e-mail."""
from __future__ import annotations

from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib
from typing import Optional

from sqlalchemy.orm import Session

from app.models_prefs import EmailLog, SmtpSettings


def get_smtp_settings(db: Session) -> SmtpSettings:
    s = db.query(SmtpSettings).filter(SmtpSettings.id == 1).first()
    if not s:
        s = SmtpSettings(id=1)
        db.add(s)
        db.commit()
        db.refresh(s)
    return s


def log_email(
    db: Session,
    *,
    to_email: str,
    subject: str,
    body: str,
    status: str,
    error: str = "",
    provider: str = "smtp",
) -> EmailLog:
    row = EmailLog(
        to_email=to_email,
        subject=subject,
        body=body[:5000],
        status=status,
        error=error[:5000],
        provider=provider,
        created_at=datetime.utcnow().isoformat(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def send_email_via_smtp(
    db: Session,
    *,
    to_email: str,
    subject: str,
    body: str,
    smtp_override: Optional[SmtpSettings] = None,
) -> dict:
    cfg = smtp_override or get_smtp_settings(db)
    if not cfg.enabled or not cfg.host:
        msg = "SMTP non configuré ou désactivé."
        log_email(db, to_email=to_email, subject=subject, body=body, status="error", error=msg)
        return {"ok": False, "message": msg}

    message = MIMEMultipart()
    message["From"] = f"{cfg.sender_name} <{cfg.sender_email}>"
    message["To"] = to_email
    message["Subject"] = subject
    message.attach(MIMEText(body, "html", "utf-8"))

    try:
        if cfg.use_ssl:
            server = smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=15)
        else:
            server = smtplib.SMTP(cfg.host, cfg.port, timeout=15)
            if cfg.use_tls:
                server.starttls()
        if cfg.username:
            server.login(cfg.username, cfg.password or "")
        server.sendmail(cfg.sender_email, [to_email], message.as_string())
        server.quit()
        log_email(db, to_email=to_email, subject=subject, body=body, status="sent")
        return {"ok": True, "message": "E-mail envoyé"}
    except Exception as exc:
        log_email(db, to_email=to_email, subject=subject, body=body, status="error", error=str(exc))
        return {"ok": False, "message": f"Erreur SMTP: {exc}"}

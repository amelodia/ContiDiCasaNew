"""
Invio e ricezione email tramite SMTP e IMAP (libreria standard).
Le credenziali sono memorizzate nel database cifrato dall'app.
"""
from __future__ import annotations

import imaplib
import re
import smtplib
import ssl
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import default as email_policy
from typing import Any

DEFAULT_EMAIL_SETTINGS: dict[str, Any] = {
    "smtp_host": "",
    "smtp_port": 587,
    "smtp_implicit_ssl": False,
    "smtp_use_starttls": True,
    "imap_host": "",
    "imap_port": 993,
    "imap_use_ssl": True,
    "username": "",
    "password": "",
    "from_address": "",
}


def ensure_email_settings(db: dict) -> None:
    if "email_settings" not in db or not isinstance(db["email_settings"], dict):
        db["email_settings"] = dict(DEFAULT_EMAIL_SETTINGS)
        return
    for k, v in DEFAULT_EMAIL_SETTINGS.items():
        if k not in db["email_settings"]:
            db["email_settings"][k] = v


def _settings_dict(db: dict) -> dict[str, Any]:
    ensure_email_settings(db)
    return db["email_settings"]


def _decode_header_value(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return raw


def _message_text_from_bytes(raw: bytes) -> str:
    msg = BytesParser(policy=email_policy).parsebytes(raw)
    if msg.is_multipart():
        plain_parts: list[str] = []
        html_parts: list[str] = []
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain":
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        plain_parts.append(payload.decode(charset, errors="replace"))
                except Exception:
                    pass
            elif ctype == "text/html":
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        html_parts.append(payload.decode(charset, errors="replace"))
                except Exception:
                    pass
        if plain_parts:
            return "\n\n".join(plain_parts)
        if html_parts:
            # strip rudimentale tag HTML per anteprima
            t = html_parts[0]
            t = re.sub(r"(?s)<script.*?>.*?</script>", "", t, flags=re.I)
            t = re.sub(r"<[^>]+>", " ", t)
            return " ".join(t.split())
        return ""
    try:
        payload = msg.get_payload(decode=True)
        if isinstance(payload, bytes):
            return payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
        return str(payload or "")
    except Exception:
        return ""


def send_email(
    db: dict,
    *,
    to_addr: str,
    subject: str,
    body: str,
) -> None:
    """Invia un'email in testo semplice."""
    s = _settings_dict(db)
    host = (s.get("smtp_host") or "").strip()
    user = (s.get("username") or "").strip()
    password = s.get("password") or ""
    if not host or not user:
        raise ValueError("Configura SMTP: server e nome utente sono obbligatori.")
    if not password:
        raise ValueError("Password non impostata (salva le impostazioni account).")
    to_addr = (to_addr or "").strip()
    if not to_addr:
        raise ValueError("Indirizzo destinatario mancante.")
    subj = (subject or "").strip() or "(senza oggetto)"
    body = body or ""
    from_addr = (s.get("from_address") or "").strip() or user
    port = int(s.get("smtp_port") or 587)
    implicit_ssl = bool(s.get("smtp_implicit_ssl"))
    use_starttls = bool(s.get("smtp_use_starttls")) and not implicit_ssl

    msg = EmailMessage()
    msg["Subject"] = subj
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(body)

    if implicit_ssl:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, context=context, timeout=60) as smtp:
            smtp.login(user, password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=60) as smtp:
            smtp.ehlo()
            if use_starttls:
                context = ssl.create_default_context()
                smtp.starttls(context=context)
                smtp.ehlo()
            smtp.login(user, password)
            smtp.send_message(msg)


def list_inbox_messages(db: dict, *, limit: int = 80) -> list[dict[str, Any]]:
    """
    Elenco messaggi dalla posta in arrivo (più recenti per primi).
    Ogni elemento: imap_id (bytes str), subject, from_addr, date_hdr
    """
    s = _settings_dict(db)
    host = (s.get("imap_host") or "").strip()
    user = (s.get("username") or "").strip()
    password = s.get("password") or ""
    if not host or not user:
        raise ValueError("Configura IMAP: server e nome utente sono obbligatori.")
    if not password:
        raise ValueError("Password non impostata.")
    port = int(s.get("imap_port") or 993)
    use_ssl = bool(s.get("imap_use_ssl", True))

    if use_ssl:
        mail = imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context(), timeout=60)
    else:
        mail = imaplib.IMAP4(host, port, timeout=60)
    try:
        mail.login(user, password)
        mail.select("INBOX", readonly=True)
        typ, data = mail.search(None, "ALL")
        if typ != "OK" or not data or not data[0]:
            return []
        ids = data[0].split()
        take = ids[-limit:] if len(ids) > limit else ids
        out: list[dict[str, Any]] = []
        for num in reversed(take):
            typ, chunk = mail.fetch(num, "(BODY.PEEK[HEADER])")
            if typ != "OK" or not chunk:
                continue
            raw: bytes | None = None
            for part in chunk:
                if isinstance(part, tuple) and len(part) >= 2 and isinstance(part[1], (bytes, bytearray)):
                    raw = bytes(part[1])
                    break
            if raw is None:
                continue
            msg = BytesParser(policy=email_policy).parsebytes(raw)
            subj = _decode_header_value(msg.get("Subject"))
            frm = _decode_header_value(msg.get("From"))
            d = _decode_header_value(msg.get("Date"))
            out.append(
                {
                    "imap_id": num.decode("ascii") if isinstance(num, bytes) else str(num),
                    "subject": subj or "(senza oggetto)",
                    "from_addr": frm or "?",
                    "date_hdr": d or "",
                }
            )
        return out
    finally:
        try:
            mail.logout()
        except Exception:
            pass


def fetch_message_body(db: dict, imap_id: str) -> str:
    """Scarica il corpo (testo) di un messaggio per ID IMAP."""
    s = _settings_dict(db)
    host = (s.get("imap_host") or "").strip()
    user = (s.get("username") or "").strip()
    password = s.get("password") or ""
    if not host or not user or not password:
        raise ValueError("Configurazione IMAP incompleta.")
    port = int(s.get("imap_port") or 993)
    use_ssl = bool(s.get("imap_use_ssl", True))
    num = imap_id.encode("ascii") if isinstance(imap_id, str) else imap_id

    if use_ssl:
        mail = imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context(), timeout=90)
    else:
        mail = imaplib.IMAP4(host, port, timeout=90)
    try:
        mail.login(user, password)
        mail.select("INBOX", readonly=True)
        typ, chunk = mail.fetch(num, "(RFC822)")
        if typ != "OK" or not chunk:
            raise ValueError("Messaggio non trovato.")
        raw: bytes | None = None
        for part in chunk:
            if isinstance(part, tuple) and len(part) >= 2 and isinstance(part[1], (bytes, bytearray)):
                raw = bytes(part[1])
                break
        if raw is None:
            raise ValueError("Dati messaggio non validi.")
        return _message_text_from_bytes(raw)
    finally:
        try:
            mail.logout()
        except Exception:
            pass


_REG_APPROVAL_RE = re.compile(r"REGISTRA\s*:\s*(\S+@\S+)", re.IGNORECASE)


def send_registration_signup_notification(db: dict, *, display_suffix: str, user_email: str) -> None:
    """Invia all'amministratore i dati del primo accesso (SMTP da email_settings)."""
    ensure_email_settings(db)
    sc = db.get("security_config")
    if not isinstance(sc, dict):
        sc = {}
    to_addr = str(sc.get("admin_notify_email") or "").strip()
    if not to_addr:
        return
    ue = user_email.strip().lower()
    body = (
        "Nuovo primo accesso — Conti di casa\n\n"
        f"Nome schermata: Conti di casa {display_suffix}\n"
        f"Email utente: {ue}\n\n"
        "Stato account: non ancora registrato (in attesa di conferma amministratore).\n\n"
        "Per confermare la registrazione, includere in una email (oggetto o corpo) la riga esatta:\n\n"
        f"REGISTRA:{ue}\n"
    )
    send_email(db, to_addr=to_addr, subject=f"[Conti di casa] Nuovo accesso: {ue}", body=body)


def scan_inbox_for_registration_approval(db: dict, *, target_email: str) -> bool:
    """True se in INBOX compare REGISTRA:<email> (oggetto o testo)."""
    target_email = target_email.strip().lower()
    if not target_email:
        return False
    s = _settings_dict(db)
    host = (s.get("imap_host") or "").strip()
    user = (s.get("username") or "").strip()
    password = s.get("password") or ""
    if not host or not user or not password:
        return False
    port = int(s.get("imap_port") or 993)
    use_ssl = bool(s.get("imap_use_ssl", True))

    if use_ssl:
        mail = imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context(), timeout=90)
    else:
        mail = imaplib.IMAP4(host, port, timeout=90)
    try:
        mail.login(user, password)
        mail.select("INBOX", readonly=True)
        typ, data = mail.search(None, "ALL")
        if typ != "OK" or not data or not data[0]:
            return False
        ids = data[0].split()
        take = ids[-80:] if len(ids) > 80 else ids
        for num in reversed(take):
            typ, chunk = mail.fetch(num, "(RFC822)")
            if typ != "OK" or not chunk:
                continue
            raw: bytes | None = None
            for part in chunk:
                if isinstance(part, tuple) and len(part) >= 2 and isinstance(part[1], (bytes, bytearray)):
                    raw = bytes(part[1])
                    break
            if raw is None:
                continue
            msg = BytesParser(policy=email_policy).parsebytes(raw)
            subj = _decode_header_value(msg.get("Subject"))
            text = _message_text_from_bytes(raw)
            blob = f"{subj}\n{text}"
            for m in _REG_APPROVAL_RE.finditer(blob):
                if m.group(1).strip().lower() == target_email:
                    return True
        return False
    finally:
        try:
            mail.logout()
        except Exception:
            pass

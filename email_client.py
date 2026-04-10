"""
Invio e ricezione email tramite SMTP e IMAP (libreria standard).
Le credenziali sono memorizzate nel database cifrato dall'app.
"""
from __future__ import annotations

import imaplib
import re
import smtplib
import ssl
import tkinter as tk
from collections.abc import Callable
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import default as email_policy
from email.utils import parsedate_to_datetime
from tkinter import messagebox, ttk
from typing import Any

SaveMailFn = Callable[[], None]

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
    # False = non verificare il certificato del server (meno sicuro; solo se CERTIFICATE_VERIFY_FAILED persiste).
    "ssl_verify_certificates": True,
}


def _ssl_context_for_settings(s: dict[str, Any]) -> ssl.SSLContext:
    """
    Contesto TLS per SMTP/IMAP. Su macOS Python spesso manca il bundle CA di sistema:
    si usa il file CA di certifi se installato (python3 -m pip install certifi).
    """
    if not bool(s.get("ssl_verify_certificates", True)):
        return ssl._create_unverified_context()
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _smtp_imap_credentials_rejected(blob_lower: str) -> bool:
    return any(
        token in blob_lower
        for token in (
            "535",
            "5.7.8",
            "badcredentials",
            "username and password not accepted",
            "authenticationfailed",
            "invalid credentials",
            "auth plain failed",
        )
    )


def _mail_password_help_text(s: dict[str, Any]) -> str:
    """Suggerimenti se SMTP/IMAP rispondono credenziali non valide."""
    user_l = (s.get("username") or "").lower()
    hosts = f"{s.get('smtp_host', '')} {s.get('imap_host', '')}".lower()
    is_gmail = "gmail" in user_l or "googlemail" in user_l or "gmail" in hosts
    base = (
        "\n\n— Credenziali rifiutate dal server —\n"
        "• Controlla utente e password (nessuno spazio in più copiato/incollato).\n"
        "• L'utente è di solito l'indirizzo email completo dell'account di posta.\n"
    )
    if is_gmail:
        base += (
            "\n— Account Gmail / Google —\n"
            "Google non accetta la password normale dell'account per le app esterne.\n"
            "1) Attiva la verifica in due passaggi sull'account Google.\n"
            "2) Vai su https://myaccount.google.com/apppasswords e crea una «Password per le app» "
            "(es. nome «Conti di casa»).\n"
            "3) Incolla quella password di 16 caratteri nel campo password dell'app (non la password di login).\n"
            "4) In Gmail web: Impostazioni → Inoltro e POP/IMAP → abilita «Accesso IMAP».\n"
            "5) SMTP: smtp.gmail.com, porta 587, STARTTLS sì, SSL implicito (465) no.\n"
            "   IMAP: imap.gmail.com, porta 993, SSL sì.\n"
        )
    return base


def ensure_email_settings(db: dict) -> None:
    if "email_settings" not in db or not isinstance(db["email_settings"], dict):
        db["email_settings"] = dict(DEFAULT_EMAIL_SETTINGS)
        return
    for k, v in DEFAULT_EMAIL_SETTINGS.items():
        if k not in db["email_settings"]:
            db["email_settings"][k] = v


def is_app_mail_configured(db: dict) -> bool:
    """True se SMTP, IMAP, credenziali e email amministratore sono impostati (notifiche / IMAP)."""
    ensure_email_settings(db)
    s = _settings_dict(db)
    sc = db.get("security_config")
    if not isinstance(sc, dict):
        sc = {}
    admin = (sc.get("admin_notify_email") or "").strip()
    return bool(
        admin
        and (s.get("smtp_host") or "").strip()
        and (s.get("imap_host") or "").strip()
        and (s.get("username") or "").strip()
        and (s.get("password") or "").strip()
    )


def test_email_configuration(db: dict) -> tuple[bool, str]:
    """
    Verifica connessione SMTP (login) e IMAP (login + INBOX).
    Ritorna (ok, messaggio utente).
    """
    ensure_email_settings(db)
    s = _settings_dict(db)
    sc = db.get("security_config")
    if not isinstance(sc, dict):
        sc = {}
    errs: list[str] = []

    host = (s.get("smtp_host") or "").strip()
    user = (s.get("username") or "").strip()
    password = s.get("password") or ""
    if not host or not user or not password:
        errs.append("SMTP: host, utente e password sono obbligatori.")
    else:
        port = int(s.get("smtp_port") or 587)
        implicit_ssl = bool(s.get("smtp_implicit_ssl"))
        use_starttls = bool(s.get("smtp_use_starttls")) and not implicit_ssl
        try:
            tls_ctx = _ssl_context_for_settings(s)
            if implicit_ssl:
                with smtplib.SMTP_SSL(host, port, context=tls_ctx, timeout=60) as smtp:
                    smtp.login(user, password)
            else:
                with smtplib.SMTP(host, port, timeout=60) as smtp:
                    smtp.ehlo()
                    if use_starttls:
                        smtp.starttls(context=tls_ctx)
                        smtp.ehlo()
                    smtp.login(user, password)
        except Exception as exc:
            errs.append(f"SMTP: {exc}")

    host_i = (s.get("imap_host") or "").strip()
    if not host_i or not user or not password:
        errs.append("IMAP: host, utente e password sono obbligatori.")
    else:
        port_i = int(s.get("imap_port") or 993)
        use_ssl = bool(s.get("imap_use_ssl", True))
        try:
            if use_ssl:
                mail = imaplib.IMAP4_SSL(
                    host_i, port_i, ssl_context=_ssl_context_for_settings(s), timeout=60
                )
            else:
                mail = imaplib.IMAP4(host_i, port_i, timeout=60)
            try:
                mail.login(user, password)
                mail.select("INBOX", readonly=True)
            finally:
                try:
                    mail.logout()
                except Exception:
                    pass
        except Exception as exc:
            errs.append(f"IMAP: {exc}")

    admin = (sc.get("admin_notify_email") or "").strip()
    if not admin:
        errs.append("Indirizzo email amministratore (notifiche) mancante.")

    if errs:
        cert_hint = (
            "\n\nSuggerimenti (certificati): «python3 -m pip install certifi» e riavvio; "
            "oppure disattiva «Verifica certificati SSL» in Opzioni solo se necessario."
        )
        blob = "\n".join(errs)
        low = blob.lower()
        if "certificate_verify_failed" in low or "certificate verify failed" in low:
            blob += cert_hint
        if _smtp_imap_credentials_rejected(low):
            blob += _mail_password_help_text(s)
        return False, blob
    return True, "Connessione SMTP e IMAP riuscita. Le impostazioni possono essere salvate."


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

    tls_ctx = _ssl_context_for_settings(s)
    if implicit_ssl:
        with smtplib.SMTP_SSL(host, port, context=tls_ctx, timeout=60) as smtp:
            smtp.login(user, password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=60) as smtp:
            smtp.ehlo()
            if use_starttls:
                smtp.starttls(context=tls_ctx)
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
        mail = imaplib.IMAP4_SSL(host, port, ssl_context=_ssl_context_for_settings(s), timeout=60)
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
        mail = imaplib.IMAP4_SSL(host, port, ssl_context=_ssl_context_for_settings(s), timeout=90)
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


# Accetta REGISTRA: o REGISTRATO: (oggetto o corpo), case-insensitive.
_REG_APPROVAL_RE = re.compile(r"(?:REGISTRA|REGISTRATO)\s*:\s*(\S+@\S+)", re.IGNORECASE)


def _utc_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_registration_not_before_iso(s: str) -> datetime | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None
    return _utc_aware(dt)


def _internaldate_utc_from_fetch_blob(blob: bytes) -> datetime | None:
    m = re.search(rb'INTERNALDATE\s+"([^"]+)"', blob)
    if not m:
        return None
    try:
        ds = m.group(1).decode("ascii", errors="replace")
        dt = parsedate_to_datetime(ds)
        return _utc_aware(dt)
    except Exception:
        return None


def _message_received_utc_from_msg(
    msg: Any, mail: imaplib.IMAP4_SSL | imaplib.IMAP4, num: bytes
) -> datetime | None:
    ds = msg.get("Date")
    if ds:
        try:
            return _utc_aware(parsedate_to_datetime(ds))
        except Exception:
            pass
    try:
        typ, chunk = mail.fetch(num, "(INTERNALDATE)")
        if typ != "OK" or not chunk:
            return None
        blob = b"".join(p for p in chunk if isinstance(p, (bytes, bytearray)))
        return _internaldate_utc_from_fetch_blob(blob)
    except Exception:
        return None


def send_registration_signup_notification(db: dict, *, display_suffix: str, user_email: str) -> None:
    """
    Notifica il primo accesso:
    - all'email amministratore (se impostata in sicurezza), con istruzioni REGISTRA:/REGISTRATO:…
    - sempre una copia di conferma all'indirizzo immesso nel wizard (così ricevi mail anche su Gmail).

    Richiede SMTP configurato e funzionante (con Gmail usa password per le app, non la password normale).
    """
    ensure_email_settings(db)
    sc = db.get("security_config")
    if not isinstance(sc, dict):
        sc = {}
    admin = str(sc.get("admin_notify_email") or "").strip()
    ue = (user_email or "").strip().lower()
    if not ue or "@" not in ue:
        raise ValueError("Email utente non valida.")

    admin_body = (
        "Nuovo primo accesso — Conti di casa\n\n"
        f"Nome schermata: Conti di casa {display_suffix}\n"
        f"Email utente: {ue}\n\n"
        "Stato account: non ancora registrato (in attesa di conferma amministratore).\n\n"
        "Per confermare la registrazione, includere in una email (oggetto o corpo) una di queste righe esatte:\n\n"
        f"REGISTRA:{ue}\n"
        f"oppure\nREGISTRATO:{ue}\n"
    )
    user_body = (
        "Conti di casa — primo accesso effettuato\n\n"
        f"Hai completato la registrazione iniziale con l'indirizzo {ue}.\n"
        f"Nome nell'app: Conti di casa {display_suffix}\n\n"
        "Per risultare «registrato» nell'applicazione, l'amministratore deve far sì che nella casella "
        "IMAP configurata in Opzioni compaia un messaggio (oggetto o testo) che contenga una di queste righe:\n\n"
        f"REGISTRA:{ue}\n"
        f"oppure\nREGISTRATO:{ue}\n\n"
        "Se non vedi altre email di sistema, controlla in Opzioni SMTP/IMAP e la cartella Spam."
    )

    if not admin:
        send_email(
            db,
            to_addr=ue,
            subject="[Conti di casa] Primo accesso — conferma",
            body=user_body
            + "\n\n---\nNota: non è impostata l'email amministratore nelle Opzioni; "
            "solo tu ricevi questa conferma.",
        )
        return

    admin_l = admin.strip().lower()
    if admin_l == ue:
        send_email(
            db,
            to_addr=admin,
            subject=f"[Conti di casa] Nuovo accesso (account {ue})",
            body=admin_body + "\n\n---\nMessaggio unico: amministratore e utente coincidono.",
        )
        return

    send_email(db, to_addr=admin, subject=f"[Conti di casa] Nuovo accesso: {ue}", body=admin_body)
    send_email(
        db,
        to_addr=ue,
        subject="[Conti di casa] Conferma del tuo primo accesso",
        body=user_body,
    )


def scan_inbox_for_registration_approval(db: dict, *, target_email: str) -> bool:
    """
    True se in INBOX compare REGISTRA:<email> o REGISTRATO:<email> (oggetto o testo).

    Se il profilo ha `registration_poll_not_before_iso` (ISO UTC impostato al termine del primo accesso),
    viene ignorato ogni messaggio la cui data (header Date o INTERNALDATE IMAP) non è **successiva**
    a quell'istante — così non si conferma la registrazione con risposte rimaste in casella da cicli
    precedenti.
    """
    target_email = target_email.strip().lower()
    if not target_email:
        return False
    up = db.get("user_profile")
    if not isinstance(up, dict):
        up = {}
    not_before_utc = _parse_registration_not_before_iso(
        str(up.get("registration_poll_not_before_iso") or "")
    )
    s = _settings_dict(db)
    host = (s.get("imap_host") or "").strip()
    user = (s.get("username") or "").strip()
    password = s.get("password") or ""
    if not host or not user or not password:
        return False
    port = int(s.get("imap_port") or 993)
    use_ssl = bool(s.get("imap_use_ssl", True))

    if use_ssl:
        mail = imaplib.IMAP4_SSL(host, port, ssl_context=_ssl_context_for_settings(s), timeout=90)
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
            if not_before_utc is not None:
                msg_dt = _message_received_utc_from_msg(msg, mail, num)
                if msg_dt is None or msg_dt <= not_before_utc:
                    continue
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

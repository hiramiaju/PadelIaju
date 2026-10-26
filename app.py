from __future__ import annotations

import base64
import html
import json
import os
import re
import secrets
import smtplib
import ssl
import string
import tempfile
import threading
from datetime import date as date_cls
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["JSON_AS_ASCII"] = False

# ---------------------------------------------------------------------------
# CONFIGURACIÓN DEL SERVICIO
# ---------------------------------------------------------------------------
COURTS = ["Cancha 1", "Cancha 2"]
SLOT_DURATION_MIN = 60
MAX_PEOPLE = 4
MAX_PUBLIC_HOURS_PER_DAY = 2
COOLDOWN_DAYS_AFTER_TWO_HOURS = 4
BOOKING_HORIZON_DAYS = 5

# Lunes a viernes: 08:00–23:00. Los valores son horas de INICIO.
WEEKDAY_SLOTS = [f"{hour:02d}:00" for hour in range(8, 23)]
# Sábado: 08:00–19:00. Último bloque 18:00–19:00.
SATURDAY_SLOTS = [f"{hour:02d}:00" for hour in range(8, 19)]
ALL_SLOTS = WEEKDAY_SLOTS

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "cambia-esta-clave")
INSTITUTE_WHATSAPP = os.getenv("INSTITUTE_WHATSAPP", "5215500000000")
LOCAL_TZ = ZoneInfo(os.getenv("LOCAL_TIMEZONE", "America/Mexico_City"))

DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data"))).expanduser().resolve()
DB_FILE = DATA_DIR / "reservas.json"
BLOCKS_FILE = DATA_DIR / "bloqueos.json"
FIXED_FILE = DATA_DIR / "reservas_fijas.json"

_json_lock = threading.RLock()

# Python weekday: lunes=0 ... domingo=6.
DEFAULT_FIXED_RESERVATIONS: list[dict[str, Any]] = [
    {
        "id": "FIX-SILVIA-LUN-C2",
        "name": "Silvia Garfias",
        "weekday": 0,
        "court": "Cancha 2",
        "start": "20:00",
        "end": "23:00",
        "active": True,
    },
    {
        "id": "FIX-SERGIO-MAR-C1",
        "name": "Sergio Castañeda",
        "weekday": 1,
        "court": "Cancha 1",
        "start": "19:00",
        "end": "21:00",
        "active": True,
    },
    {
        "id": "FIX-GILBERTO-MAR-C2",
        "name": "Gilberto Navarro",
        "weekday": 1,
        "court": "Cancha 2",
        "start": "18:00",
        "end": "20:00",
        "active": True,
    },
    {
        "id": "FIX-MARIO-MIE-C1",
        "name": "Mario Sosa",
        "weekday": 2,
        "court": "Cancha 1",
        "start": "18:00",
        "end": "20:00",
        "active": True,
    },
    {
        "id": "FIX-MARIO-MIE-C2",
        "name": "Mario Sosa",
        "weekday": 2,
        "court": "Cancha 2",
        "start": "18:00",
        "end": "20:00",
        "active": True,
    },
    {
        "id": "FIX-PAOLA-JUE-C1",
        "name": "Paola Díaz",
        "weekday": 3,
        "court": "Cancha 1",
        "start": "19:00",
        "end": "21:00",
        "active": True,
    },
    {
        "id": "FIX-KARINA-JUE-C2",
        "name": "Karina Galaviz",
        "weekday": 3,
        "court": "Cancha 2",
        "start": "18:00",
        "end": "20:00",
        "active": True,
    },
    {
        "id": "FIX-LUIS-VIE-C2",
        "name": "Luis Rendón",
        "weekday": 4,
        "court": "Cancha 2",
        "start": "18:00",
        "end": "20:00",
        "active": True,
    },
    {
        "id": "FIX-JONATHAN-LUN-C2",
        "name": "Jonathan Olivas",
        "weekday": 0,
        "court": "Cancha 2",
        "start": "08:00",
        "end": "11:00",
        "active": True,
    },
    {
        "id": "FIX-JONATHAN-MIE-C2",
        "name": "Jonathan Olivas",
        "weekday": 2,
        "court": "Cancha 2",
        "start": "08:00",
        "end": "11:00",
        "active": True,
    },
    {
        "id": "FIX-JONATHAN-VIE-C2",
        "name": "Jonathan Olivas",
        "weekday": 4,
        "court": "Cancha 2",
        "start": "08:00",
        "end": "11:00",
        "active": True,
    },
]


def _ensure_json_file(path: Path, default: list[dict[str, Any]] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps(default or [], ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path, default: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    _ensure_json_file(path, default)
    with _json_lock:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []


def _write_json(path: Path, rows: list[dict[str, Any]]) -> None:
    _ensure_json_file(path)
    with _json_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                json.dump(rows, tmp, ensure_ascii=False, indent=2)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)


def read_all() -> list[dict[str, Any]]:
    return _read_json(DB_FILE)


def write_all(rows: list[dict[str, Any]]) -> None:
    _write_json(DB_FILE, rows)


def read_blocks() -> list[dict[str, Any]]:
    return _read_json(BLOCKS_FILE)


def write_blocks(rows: list[dict[str, Any]]) -> None:
    _write_json(BLOCKS_FILE, rows)


def read_fixed() -> list[dict[str, Any]]:
    return _read_json(FIXED_FILE, DEFAULT_FIXED_RESERVATIONS)


def write_fixed(rows: list[dict[str, Any]]) -> None:
    _write_json(FIXED_FILE, rows)


_ensure_json_file(DB_FILE)
_ensure_json_file(BLOCKS_FILE)
_ensure_json_file(FIXED_FILE, DEFAULT_FIXED_RESERVATIONS)

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def parse_iso_date(value: str | None) -> date_cls | None:
    if not value or not DATE_RE.fullmatch(value):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def is_valid_date(value: str | None) -> bool:
    return parse_iso_date(value) is not None


def is_sunday(date_str: str) -> bool:
    parsed = parse_iso_date(date_str)
    return bool(parsed and parsed.weekday() == 6)


def add_days(date_str: str, delta: int) -> str:
    parsed = parse_iso_date(date_str)
    if not parsed:
        return date_str
    return (parsed + timedelta(days=delta)).isoformat()


def normalize_phone(phone: Any) -> str:
    return re.sub(r"\D", "", str(phone or ""))


def normalize_email(email: Any) -> str:
    return str(email or "").strip().lower()


def same_identity(row: dict[str, Any], person: dict[str, Any]) -> bool:
    p1, p2 = normalize_phone(row.get("phone")), normalize_phone(person.get("phone"))
    e1, e2 = normalize_email(row.get("email")), normalize_email(person.get("email"))
    return bool((p1 and p2 and p1 == p2) or (e1 and e2 and e1 == e2))


def random_id(length: int, *, uppercase: bool = False) -> str:
    alphabet = string.ascii_letters + string.digits
    value = "".join(secrets.choice(alphabet) for _ in range(length))
    return value.upper() if uppercase else value


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def local_today() -> date_cls:
    return datetime.now(LOCAL_TZ).date()


def time_to_minutes(value: str) -> int | None:
    if not TIME_RE.fullmatch(str(value or "")):
        return None
    h, m = map(int, value.split(":"))
    return h * 60 + m


def minutes_to_time(value: int) -> str:
    value = max(0, min(value, 24 * 60))
    h, m = divmod(value, 60)
    return f"{h:02d}:{m:02d}"


def date_slots(date_str: str) -> list[str]:
    parsed = parse_iso_date(date_str)
    if not parsed or parsed.weekday() == 6:
        return []
    if parsed.weekday() == 5:
        return SATURDAY_SLOTS.copy()
    return WEEKDAY_SLOTS.copy()


def is_date_bookable(date_str: str) -> tuple[bool, str | None]:
    parsed = parse_iso_date(date_str)
    if not parsed:
        return False, "Fecha inválida"
    today = local_today()
    if parsed < today:
        return False, "No se pueden crear reservaciones en fechas pasadas"
    if parsed > today + timedelta(days=BOOKING_HORIZON_DAYS):
        return False, f"Solo puedes reservar con hasta {BOOKING_HORIZON_DAYS} días de anticipación"
    return True, None


def interval_overlaps(start_a: int, end_a: int, start_b: int, end_b: int) -> bool:
    return start_a < end_b and start_b < end_a


def row_interval(row: dict[str, Any]) -> tuple[int, int] | None:
    start = time_to_minutes(str(row.get("time", "")))
    if start is None:
        return None

    explicit_end = time_to_minutes(str(row.get("end_time", "")))
    if explicit_end is not None and explicit_end > start:
        return start, explicit_end

    try:
        duration = int(row.get("duration_min") or SLOT_DURATION_MIN)
    except (TypeError, ValueError):
        duration = SLOT_DURATION_MIN
    duration = max(1, duration)
    return start, start + duration


def requested_interval(time_str: str, duration_hours: int) -> tuple[int, int] | None:
    start = time_to_minutes(time_str)
    if start is None:
        return None
    return start, start + duration_hours * 60


def fixed_for_date(date_str: str) -> list[dict[str, Any]]:
    parsed = parse_iso_date(date_str)
    if not parsed:
        return []
    weekday = parsed.weekday()
    return [
        row for row in read_fixed()
        if row.get("active", True) and int(row.get("weekday", -1)) == weekday
    ]


def conflicts_with_fixed(court: str, date_str: str, start: int, end: int) -> bool:
    for fixed in fixed_for_date(date_str):
        if fixed.get("court") != court:
            continue
        f_start = time_to_minutes(str(fixed.get("start", "")))
        f_end = time_to_minutes(str(fixed.get("end", "")))
        if f_start is None or f_end is None:
            continue
        if interval_overlaps(start, end, f_start, f_end):
            return True
    return False


def conflicts_with_rows(rows: list[dict[str, Any]], court: str, date_str: str, start: int, end: int) -> bool:
    for row in rows:
        if row.get("court") != court or row.get("date") != date_str:
            continue
        interval = row_interval(row)
        if interval and interval_overlaps(start, end, interval[0], interval[1]):
            return True
    return False


def person_conflicts_with_interval(
    rows: list[dict[str, Any]], person: dict[str, Any], date_str: str, start: int, end: int
) -> bool:
    for row in rows:
        if row.get("date") != date_str or not same_identity(row, person):
            continue
        interval = row_interval(row)
        if interval and interval_overlaps(start, end, interval[0], interval[1]):
            return True
    return False


def daily_reserved_minutes(rows: list[dict[str, Any]], person: dict[str, Any], date_str: str) -> int:
    total = 0
    for row in rows:
        if row.get("date") != date_str or not same_identity(row, person):
            continue
        interval = row_interval(row)
        if interval:
            total += max(0, interval[1] - interval[0])
    return total


def person_has_any_booking(rows: list[dict[str, Any]], person: dict[str, Any], date_str: str) -> bool:
    return any(row.get("date") == date_str and same_identity(row, person) for row in rows)


def find_blocking_rule(person: dict[str, Any], date_str: str, time_str: str) -> dict[str, Any] | None:
    parsed = parse_iso_date(date_str)
    if not parsed:
        return None

    # Compatibilidad con el panel: domingo=0, lunes=1 ... sábado=6.
    js_weekday = (parsed.weekday() + 1) % 7
    n_phone = normalize_phone(person.get("phone"))
    n_email = normalize_email(person.get("email"))

    for block in read_blocks():
        matches_identity = (
            bool(block.get("phone") and n_phone and normalize_phone(block.get("phone")) == n_phone)
            or bool(block.get("email") and n_email and normalize_email(block.get("email")) == n_email)
        )
        if not matches_identity:
            continue

        if block.get("time") not in ("all", time_str):
            continue

        if block.get("type") == "once" and block.get("date") == date_str:
            return block
        if block.get("type") == "weekly" and int(block.get("weekday", -1)) == js_weekday:
            return block
    return None


def public_reservation_payload(row: dict[str, Any]) -> dict[str, Any]:
    interval = row_interval(row)
    end_time = row.get("end_time")
    if not end_time and interval:
        end_time = minutes_to_time(interval[1])
    duration_min = (interval[1] - interval[0]) if interval else int(row.get("duration_min") or SLOT_DURATION_MIN)
    return {
        "id": row.get("id"),
        "code": row.get("code"),
        "court": row.get("court"),
        "date": row.get("date"),
        "time": row.get("time"),
        "endTime": end_time,
        "durationMin": duration_min,
        "durationHours": duration_min // 60 if duration_min % 60 == 0 else round(duration_min / 60, 1),
        "name": row.get("name"),
        "phone": row.get("phone"),
        "email": row.get("email"),
        "people": row.get("people"),
    }


def delete_reservation(reservation_id: str) -> bool:
    with _json_lock:
        rows = read_all()
        new_rows = [r for r in rows if r.get("id") != reservation_id]
        if len(new_rows) == len(rows):
            return False
        write_all(new_rows)
        return True


# ---------------------------------------------------------------------------
# CORREO AUTOMÁTICO (SMTP)
# ---------------------------------------------------------------------------
def brand_email_html(reservation: dict[str, Any]) -> str:
    safe = {k: html.escape(str(v or "")) for k, v in reservation.items()}
    interval = row_interval(reservation)
    end_time = reservation.get("end_time") or (minutes_to_time(interval[1]) if interval else "")
    time_range = f"{safe.get('time', '')}–{html.escape(str(end_time))} hrs"
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:520px;margin:0 auto;border:1px solid #e8edf5;border-radius:14px;overflow:hidden">
      <div style="background:linear-gradient(90deg,#3cb4e5,#003DA5);padding:20px 24px;color:#fff">
        <strong style="font-size:20px;letter-spacing:.2px">Instituto de la Juventud</strong>
      </div>
      <div style="height:7px;background:linear-gradient(90deg,#df1683 0 20%,#c2d500 20% 40%,#3cb4e5 40% 60%,#003DA5 60% 80%,#ffcd00 80% 100%)"></div>
      <div style="padding:24px;color:#14213d">
        <h2 style="margin:0 0 6px;color:#003DA5">¡Reservación confirmada!</h2>
        <p style="margin:0 0 20px;color:#5b6b8c">Guarda este pase para ingresar. Con el código puedes cancelar tu reservación.</p>
        <table style="width:100%;border-collapse:collapse;font-size:14px">
          <tr><td style="padding:8px 0;color:#5b6b8c">Nombre</td><td style="padding:8px 0;text-align:right;font-weight:bold">{safe.get('name','')}</td></tr>
          <tr style="border-top:1px solid #eee"><td style="padding:8px 0;color:#5b6b8c">Cancha</td><td style="padding:8px 0;text-align:right;font-weight:bold">{safe.get('court','')}</td></tr>
          <tr style="border-top:1px solid #eee"><td style="padding:8px 0;color:#5b6b8c">Fecha</td><td style="padding:8px 0;text-align:right;font-weight:bold">{safe.get('date','')}</td></tr>
          <tr style="border-top:1px solid #eee"><td style="padding:8px 0;color:#5b6b8c">Horario</td><td style="padding:8px 0;text-align:right;font-weight:bold">{time_range}</td></tr>
          <tr style="border-top:1px solid #eee"><td style="padding:8px 0;color:#5b6b8c">Personas</td><td style="padding:8px 0;text-align:right;font-weight:bold">{safe.get('people','')}</td></tr>
          <tr style="border-top:1px solid #eee"><td style="padding:8px 0;color:#5b6b8c">Código</td><td style="padding:8px 0;text-align:right;font-weight:bold;letter-spacing:2px">{safe.get('code','')}</td></tr>
        </table>
        <div style="margin-top:24px;padding:14px;background:#f2f8ff;border-radius:8px;font-size:13px;color:#5b6b8c">
          Presenta la imagen adjunta o este correo al llegar a las instalaciones del IAJU.
        </div>
      </div>
    </div>
    """


def send_confirmation_email(reservation: dict[str, Any], image_base64: str | None) -> dict[str, Any]:
    smtp_host = os.getenv("SMTP_HOST")
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    recipient = normalize_email(reservation.get("email"))

    if not recipient or not smtp_host or not smtp_user or not smtp_pass:
        return {"sent": False, "reason": "sin correo o SMTP no configurado"}

    interval = row_interval(reservation)
    end_time = reservation.get("end_time") or (minutes_to_time(interval[1]) if interval else "")

    msg = EmailMessage()
    msg["From"] = os.getenv("FROM_EMAIL", smtp_user)
    msg["To"] = recipient
    admin_email = os.getenv("ADMIN_EMAIL")
    if admin_email:
        msg["Bcc"] = admin_email
    msg["Subject"] = (
        f"Reservación confirmada · {reservation.get('court')} · "
        f"{reservation.get('date')} {reservation.get('time')}–{end_time}"
    )
    msg.set_content(
        f"Reservación confirmada. Código: {reservation.get('code')}. "
        f"Cancha: {reservation.get('court')}. Fecha: {reservation.get('date')} "
        f"{reservation.get('time')}–{end_time}."
    )
    msg.add_alternative(brand_email_html(reservation), subtype="html")

    if image_base64:
        try:
            raw = re.sub(r"^data:image/png;base64,", "", image_base64)
            image_bytes = base64.b64decode(raw, validate=True)
            msg.add_attachment(
                image_bytes,
                maintype="image",
                subtype="png",
                filename=f"pase-iaju-{reservation.get('code')}.png",
            )
        except Exception:
            pass

    try:
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, context=ssl.create_default_context(), timeout=20) as server:
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
                server.ehlo()
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
        return {"sent": True}
    except Exception as exc:
        app.logger.exception("Error enviando correo")
        return {"sent": False, "reason": str(exc)}


# ---------------------------------------------------------------------------
# VISTAS
# ---------------------------------------------------------------------------
@app.get("/")
def index():
    return render_template("index.html")


@app.get("/admin")
@app.get("/admin.html")
def admin_page():
    return render_template("admin.html")


@app.get("/health")
def health():
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# API PÚBLICA
# ---------------------------------------------------------------------------
@app.get("/api/config")
def api_config():
    return jsonify(
        {
            "courts": COURTS,
            "slots": ALL_SLOTS,
            "weekdaySlots": WEEKDAY_SLOTS,
            "saturdaySlots": SATURDAY_SLOTS,
            "slotDurationMin": SLOT_DURATION_MIN,
            "whatsapp": INSTITUTE_WHATSAPP,
            "maxPeople": MAX_PEOPLE,
            "maxPublicHoursPerDay": MAX_PUBLIC_HOURS_PER_DAY,
            "cooldownDaysAfterTwoHours": COOLDOWN_DAYS_AFTER_TWO_HOURS,
            "bookingHorizonDays": BOOKING_HORIZON_DAYS,
        }
    )


@app.get("/api/availability")
def availability():
    date_str = request.args.get("date", "")
    if not is_valid_date(date_str):
        return jsonify({"error": "Fecha inválida (usa YYYY-MM-DD)"}), 400

    if is_sunday(date_str):
        return jsonify({"date": date_str, "closed": True, "slots": [], "busy": None})

    slots = date_slots(date_str)
    rows = [r for r in read_all() if r.get("date") == date_str]
    fixed = fixed_for_date(date_str)
    busy = {court: {slot: False for slot in slots} for court in COURTS}

    for court in COURTS:
        for slot in slots:
            start = time_to_minutes(slot)
            if start is None:
                continue
            end = start + SLOT_DURATION_MIN
            if conflicts_with_rows(rows, court, date_str, start, end) or conflicts_with_fixed(court, date_str, start, end):
                busy[court][slot] = True

    return jsonify({"date": date_str, "closed": False, "slots": slots, "busy": busy, "fixedCount": len(fixed)})


@app.post("/api/reservations")
def create_reservation():
    payload = request.get_json(silent=True) or {}
    court = str(payload.get("court", ""))
    date_str = str(payload.get("date", ""))
    time_str = str(payload.get("time", ""))
    first_name = " ".join(str(payload.get("firstName", "")).split())
    last_name = " ".join(str(payload.get("lastName", "")).split())
    name = f"{first_name} {last_name}".strip()
    if not first_name or not last_name:
        return jsonify({"error": "Nombre(s) y apellido(s) son obligatorios y deben coincidir con tu INE"}), 400
    if len(first_name) > 100 or len(last_name) > 120:
        return jsonify({"error": "El nombre o los apellidos exceden el límite permitido"}), 400
    if payload.get("acceptedNotice") is not True:
        return jsonify({"error": "Debes aceptar el aviso sobre INE y préstamo de equipo"}), 400
    phone = str(payload.get("phone", "")).strip()
    email = str(payload.get("email", "")).strip()

    try:
        people_num = int(payload.get("people"))
    except (TypeError, ValueError):
        people_num = 0

    try:
        duration_hours = int(payload.get("durationHours", 1))
    except (TypeError, ValueError):
        duration_hours = 0

    if court not in COURTS:
        return jsonify({"error": "Cancha inválida"}), 400
    if not is_valid_date(date_str):
        return jsonify({"error": "Fecha inválida"}), 400
    date_ok, date_error = is_date_bookable(date_str)
    if not date_ok:
        return jsonify({"error": date_error}), 400
    if is_sunday(date_str):
        return jsonify({"error": "El servicio no está disponible los domingos. Elige otro día."}), 400
    if duration_hours not in {1, 2}:
        return jsonify({"error": "Puedes reservar 1 o 2 horas consecutivas"}), 400
    if not name or not phone or not email:
        return jsonify({"error": "Nombre, teléfono y correo son obligatorios"}), 400
    if people_num < 1 or people_num > MAX_PEOPLE:
        return jsonify({"error": f"El número de personas debe ser entre 1 y {MAX_PEOPLE}"}), 400

    slots = date_slots(date_str)
    if time_str not in slots:
        return jsonify({"error": "Horario inválido para ese día"}), 400

    interval = requested_interval(time_str, duration_hours)
    if interval is None:
        return jsonify({"error": "Horario inválido"}), 400
    start, end = interval

    requested_starts = [minutes_to_time(start + i * 60) for i in range(duration_hours)]
    if any(slot not in slots for slot in requested_starts):
        return jsonify({"error": "La duración elegida rebasa el horario de servicio de ese día"}), 400

    person = {"name": name, "phone": phone, "email": email}

    with _json_lock:
        rows = read_all()

        if conflicts_with_rows(rows, court, date_str, start, end) or conflicts_with_fixed(court, date_str, start, end):
            return jsonify({"error": "Uno de esos horarios ya está ocupado. Elige otro horario o una duración menor."}), 409

        if person_conflicts_with_interval(rows, person, date_str, start, end):
            return jsonify({"error": "Ya tienes otra reservación que se empalma con este horario."}), 409

        for slot in requested_starts:
            blocking_rule = find_blocking_rule(person, date_str, slot)
            if blocking_rule:
                return (
                    jsonify(
                        {
                            "error": blocking_rule.get("reason")
                            or "No tienes permitido reservar este horario. Contacta al IAJU para más información."
                        }
                    ),
                    403,
                )

        existing_today = daily_reserved_minutes(rows, person, date_str)
        requested_minutes = duration_hours * 60
        new_total_today = existing_today + requested_minutes
        if new_total_today > MAX_PUBLIC_HOURS_PER_DAY * 60:
            return (
                jsonify({"error": f"El máximo por persona es de {MAX_PUBLIC_HOURS_PER_DAY} horas en un mismo día."}),
                429,
            )

        # Si en alguno de los 4 días anteriores ya acumuló 2 horas, sigue en periodo de espera.
        for offset in range(1, COOLDOWN_DAYS_AFTER_TWO_HOURS + 1):
            previous_date = add_days(date_str, -offset)
            if daily_reserved_minutes(rows, person, previous_date) >= MAX_PUBLIC_HOURS_PER_DAY * 60:
                available_again = add_days(previous_date, COOLDOWN_DAYS_AFTER_TWO_HOURS + 1)
                return (
                    jsonify(
                        {
                            "error": (
                                f"Después de reservar {MAX_PUBLIC_HOURS_PER_DAY} horas debes esperar "
                                f"{COOLDOWN_DAYS_AFTER_TWO_HOURS} días antes de volver a reservar. "
                                f"Podrás reservar nuevamente a partir del {available_again}."
                            )
                        }
                    ),
                    429,
                )

        # Si con esta operación llega a 2 horas, no permitimos que ya tenga otra reserva
        # en los cuatro días siguientes. Así la regla no se puede saltar reservando primero el día posterior.
        if new_total_today >= MAX_PUBLIC_HOURS_PER_DAY * 60:
            for offset in range(1, COOLDOWN_DAYS_AFTER_TWO_HOURS + 1):
                future_date = add_days(date_str, offset)
                if person_has_any_booking(rows, person, future_date):
                    return (
                        jsonify(
                            {
                                "error": (
                                    f"Ya tienes una reservación el {future_date}. Al completar 2 horas el {date_str}, "
                                    f"los siguientes {COOLDOWN_DAYS_AFTER_TWO_HOURS} días deben quedar libres."
                                )
                            }
                        ),
                        429,
                    )

        reservation = {
            "id": random_id(10),
            "code": random_id(6, uppercase=True),
            "court": court,
            "date": date_str,
            "time": time_str,
            "end_time": minutes_to_time(end),
            "duration_min": requested_minutes,
            "name": name,
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone,
            "email": email,
            "people": people_num,
            "created_at": utc_now_iso(),
        }
        rows.append(reservation)
        write_all(rows)

    return jsonify(public_reservation_payload(reservation)), 201


@app.post("/api/reservations/<reservation_id>/email-ticket")
def email_ticket(reservation_id: str):
    payload = request.get_json(silent=True) or {}
    image_base64 = payload.get("imageBase64")
    reservation = next((r for r in read_all() if r.get("id") == reservation_id), None)
    if not reservation:
        return jsonify({"error": "Reservación no encontrada"}), 404
    if not image_base64:
        return jsonify({"error": "Falta la imagen del comprobante"}), 400

    result = send_confirmation_email(reservation, str(image_base64))
    return jsonify({"emailSent": bool(result.get("sent")), "reason": result.get("reason")})


@app.post("/api/reservations/cancel")
def cancel_reservation():
    payload = request.get_json(silent=True) or {}
    code = str(payload.get("code", "")).strip().upper()
    phone = str(payload.get("phone", "")).strip()
    if not code or not phone:
        return jsonify({"error": "Ingresa tu código y el teléfono con el que reservaste"}), 400

    with _json_lock:
        rows = read_all()
        match = next(
            (
                r
                for r in rows
                if str(r.get("code", "")).strip().upper() == code
                and normalize_phone(r.get("phone")) == normalize_phone(phone)
            ),
            None,
        )
        if not match:
            return jsonify({"error": "No encontramos una reservación con ese código y teléfono"}), 404

        write_all([r for r in rows if r.get("id") != match.get("id")])

    public = public_reservation_payload(match)
    return jsonify(
        {
            "ok": True,
            "cancelled": {
                "court": public.get("court"),
                "date": public.get("date"),
                "time": public.get("time"),
                "endTime": public.get("endTime"),
            },
        }
    )


# ---------------------------------------------------------------------------
# API ADMIN
# ---------------------------------------------------------------------------
def admin_authorized() -> bool:
    return request.headers.get("x-admin-password", "") == ADMIN_PASSWORD


def require_admin_response():
    if not admin_authorized():
        return jsonify({"error": "No autorizado"}), 401
    return None


@app.post("/api/admin/login")
def admin_login():
    payload = request.get_json(silent=True) or {}
    if str(payload.get("password", "")) == ADMIN_PASSWORD:
        return jsonify({"ok": True})
    return jsonify({"ok": False}), 401


@app.get("/api/admin/reservations")
def admin_reservations():
    denied = require_admin_response()
    if denied:
        return denied

    date_filter = request.args.get("date")
    rows = read_all()
    if date_filter:
        rows = [r for r in rows if r.get("date") == date_filter]
    rows.sort(key=lambda r: f"{r.get('date','')}{r.get('time','')}")
    if not date_filter:
        rows.reverse()
    return jsonify(rows)


@app.get("/api/admin/stats")
def admin_stats():
    denied = require_admin_response()
    if denied:
        return denied

    rows = read_all()
    today_iso = local_today().isoformat()
    total_reservations = len(rows)
    total_people = sum(int(r.get("people") or 0) for r in rows)
    total_hours = 0.0
    today_count = sum(1 for r in rows if r.get("date") == today_iso)
    upcoming_count = sum(1 for r in rows if str(r.get("date", "")) >= today_iso)

    by_court = {court: 0 for court in COURTS}
    by_slot = {slot: 0 for slot in ALL_SLOTS}
    by_date_map: dict[str, int] = {}

    for row in rows:
        court = row.get("court")
        date_str = row.get("date")
        interval = row_interval(row)
        if court in by_court:
            by_court[court] += 1
        if interval:
            total_hours += max(0, interval[1] - interval[0]) / 60
            # Cuenta cada bloque horario completo/solapado para la gráfica.
            for slot in ALL_SLOTS:
                slot_start = time_to_minutes(slot)
                if slot_start is not None and interval_overlaps(interval[0], interval[1], slot_start, slot_start + 60):
                    by_slot[slot] += 1
        if date_str:
            by_date_map[str(date_str)] = by_date_map.get(str(date_str), 0) + 1

    by_date = [{"date": d, "count": by_date_map[d]} for d in sorted(by_date_map)]
    busiest_slot = max(by_slot.items(), key=lambda item: item[1]) if by_slot else ("—", 0)
    busiest_court = max(by_court.items(), key=lambda item: item[1]) if by_court else ("—", 0)

    return jsonify(
        {
            "totalReservations": total_reservations,
            "totalPeople": total_people,
            "totalHours": round(total_hours, 1),
            "todayCount": today_count,
            "upcomingCount": upcoming_count,
            "fixedWeeklyCount": len([r for r in read_fixed() if r.get("active", True)]),
            "byCourt": by_court,
            "bySlot": by_slot,
            "byDate": by_date,
            "busiestSlot": busiest_slot[0] if busiest_slot[1] > 0 else "—",
            "busiestCourt": busiest_court[0] if busiest_court[1] > 0 else "—",
        }
    )


@app.delete("/api/admin/reservations/<reservation_id>")
def admin_delete_reservation(reservation_id: str):
    denied = require_admin_response()
    if denied:
        return denied
    delete_reservation(reservation_id)
    return jsonify({"ok": True})


@app.get("/api/admin/blocks")
def admin_blocks():
    denied = require_admin_response()
    if denied:
        return denied
    return jsonify(read_blocks())


@app.post("/api/admin/blocks")
def admin_create_block():
    denied = require_admin_response()
    if denied:
        return denied

    payload = request.get_json(silent=True) or {}
    phone = str(payload.get("phone", "")).strip()
    email = str(payload.get("email", "")).strip()
    name = str(payload.get("name", "")).strip()
    block_type = str(payload.get("type", ""))
    date_str = str(payload.get("date", ""))
    time_str = str(payload.get("time", ""))
    reason = str(payload.get("reason", "")).strip()

    try:
        weekday = int(payload.get("weekday"))
    except (TypeError, ValueError):
        weekday = -1

    if not phone and not email:
        return jsonify({"error": "Ingresa al menos el teléfono o el correo de la persona"}), 400
    if block_type not in {"once", "weekly"}:
        return jsonify({"error": "Tipo de bloqueo inválido"}), 400
    if block_type == "once" and not is_valid_date(date_str):
        return jsonify({"error": "Fecha inválida"}), 400
    if block_type == "weekly" and not (0 <= weekday <= 6):
        return jsonify({"error": "Día de la semana inválido"}), 400
    if time_str != "all" and time_str not in ALL_SLOTS:
        return jsonify({"error": "Horario inválido"}), 400

    block = {
        "id": random_id(10),
        "phone": phone or None,
        "email": email or None,
        "name": name or None,
        "type": block_type,
        "date": date_str if block_type == "once" else None,
        "weekday": weekday if block_type == "weekly" else None,
        "time": time_str,
        "reason": reason or None,
        "created_at": utc_now_iso(),
    }

    with _json_lock:
        blocks = read_blocks()
        blocks.append(block)
        write_blocks(blocks)
    return jsonify(block), 201


@app.delete("/api/admin/blocks/<block_id>")
def admin_delete_block(block_id: str):
    denied = require_admin_response()
    if denied:
        return denied

    with _json_lock:
        blocks = [b for b in read_blocks() if b.get("id") != block_id]
        write_blocks(blocks)
    return jsonify({"ok": True})


@app.get("/api/admin/fixed-reservations")
def admin_fixed_reservations():
    denied = require_admin_response()
    if denied:
        return denied
    rows = read_fixed()
    rows.sort(key=lambda r: (int(r.get("weekday", 9)), str(r.get("start", "")), str(r.get("court", ""))))
    return jsonify(rows)


@app.post("/api/admin/fixed-reservations")
def admin_create_fixed_reservation():
    denied = require_admin_response()
    if denied:
        return denied

    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "")).strip()
    court = str(payload.get("court", "")).strip()
    start_str = str(payload.get("start", "")).strip()
    end_str = str(payload.get("end", "")).strip()
    try:
        weekday = int(payload.get("weekday"))
    except (TypeError, ValueError):
        weekday = -1

    start = time_to_minutes(start_str)
    end = time_to_minutes(end_str)
    if not name:
        return jsonify({"error": "Ingresa el nombre"}), 400
    if court not in COURTS:
        return jsonify({"error": "Cancha inválida"}), 400
    if not (0 <= weekday <= 5):
        return jsonify({"error": "Elige un día de lunes a sábado"}), 400
    if start is None or end is None or end <= start:
        return jsonify({"error": "Horario inválido"}), 400

    allowed_slots = SATURDAY_SLOTS if weekday == 5 else WEEKDAY_SLOTS
    open_start = time_to_minutes(allowed_slots[0])
    open_end = (time_to_minutes(allowed_slots[-1]) or 0) + 60
    if open_start is None or start < open_start or end > open_end:
        return jsonify({"error": "La reservación fija queda fuera del horario de servicio de ese día"}), 400

    with _json_lock:
        fixed_rows = read_fixed()
        for row in fixed_rows:
            if not row.get("active", True) or row.get("court") != court or int(row.get("weekday", -1)) != weekday:
                continue
            existing_start = time_to_minutes(str(row.get("start", "")))
            existing_end = time_to_minutes(str(row.get("end", "")))
            if existing_start is not None and existing_end is not None and interval_overlaps(start, end, existing_start, existing_end):
                return jsonify({"error": "Ese horario fijo se empalma con otra reservación semanal de la misma cancha"}), 409

        fixed = {
            "id": "FIX-" + random_id(8, uppercase=True),
            "name": name,
            "weekday": weekday,
            "court": court,
            "start": start_str,
            "end": end_str,
            "active": True,
            "created_at": utc_now_iso(),
        }
        fixed_rows.append(fixed)
        write_fixed(fixed_rows)
    return jsonify(fixed), 201


@app.delete("/api/admin/fixed-reservations/<fixed_id>")
def admin_delete_fixed_reservation(fixed_id: str):
    denied = require_admin_response()
    if denied:
        return denied

    with _json_lock:
        rows = read_fixed()
        new_rows = [r for r in rows if r.get("id") != fixed_id]
        if len(new_rows) == len(rows):
            return jsonify({"error": "Reservación fija no encontrada"}), 404
        write_fixed(new_rows)
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)

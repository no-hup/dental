"""Mock OpenDental API functions.

Drop-in replacements for every function in opendental_client.py that makes
HTTP calls.  Pure formatters (format_datetime_voice, format_slot_voice) are
NOT duplicated here — the originals are kept.

All data lives in a local SQLite database managed by mock_opendental_db.
"""

import logging
from datetime import datetime, timedelta

import mock_opendental_db as db

logger = logging.getLogger(__name__)

# ── Helpers ──────────────────────────────────────────────────────────


def _row_to_dict(row):
    """Convert a sqlite3.Row to a plain dict."""
    if row is None:
        return None
    return dict(row)


def _rows_to_list(rows):
    """Convert a list of sqlite3.Row to list of dicts."""
    return [dict(r) for r in rows]


def _clean_phone(phone):
    """Strip +1 country code, matching opendental_client behavior."""
    clean = phone.lstrip("+")
    if clean.startswith("1") and len(clean) == 11:
        clean = clean[1:]
    return clean


# Provider → operatory mapping (for slot generation)
_PROV_OPS = {
    1: [1, 2],   # Dr. Mitchell
    2: [3, 4],   # Dr. Rodriguez
    3: [5],      # Dr. Chen
    4: [6],      # Lisa Thompson
    5: [7],      # Rachel Davis
}

# ── Patient Endpoints ────────────────────────────────────────────────


def lookup_patient_by_phone(phone):
    """Search for patient by phone number."""
    clean = _clean_phone(phone)
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM patients WHERE HmPhone=? OR WkPhone=? OR WirelessPhone=?",
        (clean, clean, clean),
    )
    rows = cur.fetchall()
    conn.close()
    return _rows_to_list(rows) if rows else []


def get_patient(pat_num):
    """Get full patient record by PatNum."""
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM patients WHERE PatNum=?", (pat_num,))
    row = cur.fetchone()
    conn.close()
    return _row_to_dict(row)


def create_patient(first_name, last_name, phone=None, birthdate=None,
                   email=None, gender=None):
    """Create a new patient. Returns the created patient dict with PatNum."""
    conn = db.get_connection()
    cur = conn.cursor()

    clean_phone = _clean_phone(phone) if phone else None
    gender_val = 2  # Unknown
    if gender:
        gender_map = {"male": 0, "female": 1, "m": 0, "f": 1}
        gender_val = gender_map.get(gender.lower(), 2)

    cur.execute(
        "INSERT INTO patients (LName, FName, WirelessPhone, Birthdate, Email, Gender, PriProv) "
        "VALUES (?,?,?,?,?,?,?)",
        (last_name, first_name, clean_phone, birthdate, email, gender_val, 1),
    )
    pat_num = cur.lastrowid
    conn.commit()
    conn.close()

    logger.info(f"Mock: Created patient {first_name} {last_name} (PatNum={pat_num})")
    return {
        "PatNum": pat_num,
        "FName": first_name,
        "LName": last_name,
        "WirelessPhone": clean_phone,
        "Birthdate": birthdate,
        "Email": email,
        "Gender": gender_val,
    }


# ── Appointment Endpoints ────────────────────────────────────────────


def get_patient_appointments(pat_num, status="Scheduled"):
    """Get appointments for a patient, filtered by status."""
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM appointments WHERE PatNum=? AND AptStatus=? ORDER BY AptDateTime",
        (pat_num, status),
    )
    rows = cur.fetchall()
    conn.close()
    return _rows_to_list(rows)


def get_appointment(apt_num):
    """Get a single appointment by AptNum."""
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM appointments WHERE AptNum=?", (apt_num,))
    row = cur.fetchone()
    conn.close()
    return _row_to_dict(row)


def get_available_slots(date_start=None, date_end=None, prov_num=None,
                        op_num=None, length_minutes=None):
    """Generate available appointment slots.

    For each weekday in the date range, for each provider:
      1. Working hours: 8:00 AM - 5:00 PM
      2. Block lunch: 12:00 - 1:00 PM
      3. Subtract existing appointments
      4. Split remaining free time into slots of length_minutes
      5. Assign operatory from provider mapping
    """
    if not length_minutes:
        length_minutes = 30

    # Parse date range
    try:
        start = datetime.strptime(date_start, "%Y-%m-%d") if date_start else datetime.now() + timedelta(days=1)
    except (ValueError, TypeError):
        start = datetime.now() + timedelta(days=1)

    try:
        end = datetime.strptime(date_end, "%Y-%m-%d") if date_end else start + timedelta(days=7)
    except (ValueError, TypeError):
        end = start + timedelta(days=7)

    # Which providers to check
    if prov_num:
        prov_list = [prov_num]
    else:
        prov_list = list(_PROV_OPS.keys())

    conn = db.get_connection()
    cur = conn.cursor()

    slots = []
    current_day = start
    while current_day <= end:
        if current_day.weekday() >= 5:  # skip weekends
            current_day += timedelta(days=1)
            continue

        day_str = current_day.strftime("%Y-%m-%d")

        for prov in prov_list:
            # Get existing appointments for this provider on this day
            cur.execute(
                "SELECT AptDateTime, Pattern FROM appointments "
                "WHERE ProvNum=? AND AptDateTime LIKE ? AND AptStatus='Scheduled'",
                (prov, f"{day_str}%"),
            )
            booked = cur.fetchall()

            # Build set of booked 5-minute blocks
            booked_blocks = set()
            for apt in booked:
                try:
                    apt_dt = datetime.strptime(apt["AptDateTime"], "%Y-%m-%d %H:%M:%S")
                except (ValueError, TypeError):
                    continue
                # Each char in Pattern = 5 minutes
                pattern = apt["Pattern"] or "/XX/"
                duration_minutes = len(pattern) * 5
                block_start = apt_dt
                while block_start < apt_dt + timedelta(minutes=duration_minutes):
                    booked_blocks.add(block_start)
                    block_start += timedelta(minutes=5)

            # Working hours: 8:00-12:00, 13:00-17:00 (lunch break 12-1)
            work_periods = [
                (current_day.replace(hour=8, minute=0, second=0),
                 current_day.replace(hour=12, minute=0, second=0)),
                (current_day.replace(hour=13, minute=0, second=0),
                 current_day.replace(hour=17, minute=0, second=0)),
            ]

            # Filter by op if requested
            ops = _PROV_OPS.get(prov, [1])
            if op_num and op_num in ops:
                ops = [op_num]

            for period_start, period_end in work_periods:
                slot_start = period_start
                while slot_start + timedelta(minutes=length_minutes) <= period_end:
                    # Check if all 5-minute blocks for this slot are free
                    all_free = True
                    check = slot_start
                    while check < slot_start + timedelta(minutes=length_minutes):
                        if check in booked_blocks:
                            all_free = False
                            break
                        check += timedelta(minutes=5)

                    if all_free:
                        slot_end = slot_start + timedelta(minutes=length_minutes)
                        slots.append({
                            "DateTimeStart": slot_start.strftime("%Y-%m-%d %H:%M:%S"),
                            "DateTimeEnd": slot_end.strftime("%Y-%m-%d %H:%M:%S"),
                            "ProvNum": prov,
                            "OpNum": ops[0],
                        })

                    slot_start += timedelta(minutes=length_minutes)

        current_day += timedelta(days=1)

    conn.close()

    # Sort by DateTimeStart
    slots.sort(key=lambda s: s["DateTimeStart"])
    return slots


def book_appointment(pat_num, op_num, apt_datetime, pattern=None,
                     prov_num=None, is_new_patient=False, note=None,
                     appointment_type_num=None):
    """Create a new appointment."""
    conn = db.get_connection()
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO appointments (PatNum, ProvNum, Op, AptDateTime, Pattern, IsNewPatient, Note, AppointmentTypeNum, AptStatus) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (pat_num, prov_num, op_num, apt_datetime,
         pattern or "/XX/",
         "true" if is_new_patient else "false",
         note, appointment_type_num, "Scheduled"),
    )
    apt_num = cur.lastrowid
    conn.commit()
    conn.close()

    logger.info(f"Mock: Booked appointment {apt_num} for PatNum={pat_num} at {apt_datetime}")
    return {
        "AptNum": apt_num,
        "PatNum": pat_num,
        "ProvNum": prov_num,
        "Op": op_num,
        "AptDateTime": apt_datetime,
        "Pattern": pattern or "/XX/",
        "AptStatus": "Scheduled",
        "Note": note,
    }


def confirm_appointment(apt_num, confirm_val="Confirmed"):
    """Confirm an appointment."""
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE appointments SET Confirmed=? WHERE AptNum=?",
        (confirm_val, apt_num),
    )
    updated = cur.rowcount
    conn.commit()
    conn.close()

    if updated:
        logger.info(f"Mock: Confirmed appointment {apt_num}")
        return {"status": "ok"}
    return None


def reschedule_appointment(apt_num, new_datetime=None, new_op=None,
                           new_prov_num=None):
    """Reschedule an appointment."""
    updates = []
    params = []
    if new_datetime:
        updates.append("AptDateTime=?")
        params.append(new_datetime)
    if new_op:
        updates.append("Op=?")
        params.append(new_op)
    if new_prov_num:
        updates.append("ProvNum=?")
        params.append(new_prov_num)

    if not updates:
        return None

    params.append(apt_num)
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute(f"UPDATE appointments SET {', '.join(updates)} WHERE AptNum=?", params)
    updated = cur.rowcount
    conn.commit()
    conn.close()

    if updated:
        logger.info(f"Mock: Rescheduled appointment {apt_num} to {new_datetime}")
        return {"status": "ok"}
    return None


def cancel_appointment(apt_num, send_to_unscheduled=True):
    """Cancel (break) an appointment."""
    new_status = "UnschedList" if send_to_unscheduled else "Broken"
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE appointments SET AptStatus=? WHERE AptNum=?",
        (new_status, apt_num),
    )
    updated = cur.rowcount
    conn.commit()
    conn.close()

    if updated:
        logger.info(f"Mock: Cancelled appointment {apt_num}")
        return {"status": "ok"}
    return None


# ── Provider & Operatory Endpoints ───────────────────────────────────


def get_providers(clinic_num=None):
    """Get all providers."""
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM providers")
    rows = cur.fetchall()
    conn.close()
    return _rows_to_list(rows)


def get_provider(prov_num):
    """Get a single provider by ProvNum."""
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM providers WHERE ProvNum=?", (prov_num,))
    row = cur.fetchone()
    conn.close()
    return _row_to_dict(row)


def get_operatories(clinic_num=None):
    """Get all operatories."""
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM operatories")
    rows = cur.fetchall()
    conn.close()
    return _rows_to_list(rows)


def get_appointment_types():
    """Get all configured appointment types."""
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM appointment_types")
    rows = cur.fetchall()
    conn.close()
    return _rows_to_list(rows)


# ── Recall Endpoints ─────────────────────────────────────────────────


def get_recalls(pat_num):
    """Get recall/recare info for a patient."""
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM recalls WHERE PatNum=?", (pat_num,))
    rows = cur.fetchall()
    conn.close()
    return _rows_to_list(rows)


# ── Communication Log ────────────────────────────────────────────────


def create_commlog(pat_num, note, mode="Phone"):
    """Log a communication entry."""
    mode_map = {
        "None": 0, "Email": 1, "Mail": 2, "Phone": 3,
        "InPerson": 4, "Text": 5,
    }
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO commlogs (PatNum, Note, Mode_, CommDateTime) VALUES (?,?,?,?)",
        (pat_num, note, mode_map.get(mode, 3),
         datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    commlog_num = cur.lastrowid
    conn.commit()
    conn.close()

    logger.info(f"Mock: CommLog {commlog_num} for PatNum={pat_num}")
    return {"CommlogNum": commlog_num, "PatNum": pat_num, "Note": note}


# ── Recall Bulk Endpoints ────────────────────────────────────────────


def get_recall_list(date_start=None, date_end=None):
    """Get patients due for recall in a date range."""
    conn = db.get_connection()
    cur = conn.cursor()

    query = (
        "SELECT r.*, p.FName, p.LName, p.WirelessPhone, p.HmPhone, p.Email "
        "FROM recalls r JOIN patients p ON r.PatNum = p.PatNum"
    )
    conditions = []
    params = []

    if date_start:
        conditions.append("r.DateDue >= ?")
        params.append(date_start)
    if date_end:
        conditions.append("r.DateDue <= ?")
        params.append(date_end)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY r.DateDue"

    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    return _rows_to_list(rows)


def update_recall_status(pat_num, recall_type="Prophy", status="Contacted", note=None):
    """Mark recall as contacted."""
    conn = db.get_connection()
    cur = conn.cursor()

    # Update the recall record
    cur.execute(
        "UPDATE recalls SET RecallType=? WHERE PatNum=? AND RecallType=?",
        (recall_type, pat_num, recall_type),
    )

    # Log the contact attempt
    if note:
        cur.execute(
            "INSERT INTO commlogs (PatNum, Note, Mode_, CommDateTime) VALUES (?,?,?,?)",
            (pat_num, f"Recall contact: {note}", 3,
             datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )

    conn.commit()
    conn.close()
    logger.info(f"Mock: Updated recall status for PatNum={pat_num}: {status}")
    return {"status": "ok"}


# ── Appointment Bulk Endpoints ──────────────────────────────────────


def get_appointments_date_range(date_start, date_end, status="Scheduled"):
    """Bulk-fetch appointments in a date range."""
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT a.*, p.FName, p.LName, p.WirelessPhone, p.HmPhone "
        "FROM appointments a JOIN patients p ON a.PatNum = p.PatNum "
        "WHERE a.AptDateTime >= ? AND a.AptDateTime <= ? AND a.AptStatus=? "
        "ORDER BY a.AptDateTime",
        (f"{date_start} 00:00:00", f"{date_end} 23:59:59", status),
    )
    rows = cur.fetchall()
    conn.close()
    return _rows_to_list(rows)


def append_appointment_note(apt_num, note):
    """Append a note to an appointment."""
    conn = db.get_connection()
    cur = conn.cursor()

    # Get existing note
    cur.execute("SELECT Note FROM appointments WHERE AptNum=?", (apt_num,))
    row = cur.fetchone()
    if row:
        existing = row["Note"] or ""
        new_note = f"{existing}\n{note}".strip() if existing else note
        cur.execute("UPDATE appointments SET Note=? WHERE AptNum=?", (new_note, apt_num))
        conn.commit()

    conn.close()
    logger.info(f"Mock: Appended note to appointment {apt_num}")
    return {"status": "ok"}


# ── Insurance Endpoints ─────────────────────────────────────────────


def get_patient_insurance(pat_num):
    """Get patient's current insurance info (combined view).

    Joins patplans, inssubs, insplans, and carriers to build a complete
    insurance record similar to /familymodules/{PatNum}/Insurance.
    """
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT pp.PatPlanNum, pp.Ordinal, pp.Relationship, "
        "       s.InsSubNum, s.SubscriberID, s.DateEffective, s.DateTerm, "
        "       p.PlanNum, p.GroupName, p.GroupNum, p.PlanType, "
        "       c.CarrierNum, c.CarrierName, c.Phone as CarrierPhone "
        "FROM patplans pp "
        "JOIN inssubs s ON pp.InsSubNum = s.InsSubNum "
        "JOIN insplans p ON s.PlanNum = p.PlanNum "
        "JOIN carriers c ON p.CarrierNum = c.CarrierNum "
        "WHERE pp.PatNum=? "
        "ORDER BY pp.Ordinal",
        (pat_num,),
    )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return []

    result = []
    for row in rows:
        result.append({
            "PatPlanNum": row["PatPlanNum"],
            "Ordinal": row["Ordinal"],
            "Relationship": row["Relationship"],
            "InsSubNum": row["InsSubNum"],
            "SubscriberID": row["SubscriberID"],
            "DateEffective": row["DateEffective"],
            "DateTerm": row["DateTerm"],
            "PlanNum": row["PlanNum"],
            "GroupName": row["GroupName"],
            "GroupNum": row["GroupNum"],
            "PlanType": row["PlanType"],
            "CarrierNum": row["CarrierNum"],
            "CarrierName": row["CarrierName"],
            "CarrierPhone": row["CarrierPhone"],
        })
    return result


def search_carriers(name):
    """Search for insurance carriers by name."""
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM carriers WHERE CarrierName LIKE ?",
        (f"%{name}%",),
    )
    rows = cur.fetchall()
    conn.close()
    return _rows_to_list(rows)


def create_carrier(name, phone=None, address=None, city=None,
                   state=None, zip_code=None, elect_id=None):
    """Create a new insurance carrier."""
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO carriers (CarrierName, Phone, Address, City, State, Zip, ElectID) "
        "VALUES (?,?,?,?,?,?,?)",
        (name, phone, address, city, state, zip_code, elect_id),
    )
    carrier_num = cur.lastrowid
    conn.commit()
    conn.close()

    logger.info(f"Mock: Created carrier {name} (CarrierNum={carrier_num})")
    return {"CarrierNum": carrier_num, "CarrierName": name}


def get_insurance_plan(plan_num):
    """Get insurance plan details by PlanNum."""
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT p.*, c.CarrierName FROM insplans p "
        "JOIN carriers c ON p.CarrierNum = c.CarrierNum "
        "WHERE p.PlanNum=?",
        (plan_num,),
    )
    row = cur.fetchone()
    conn.close()
    return _row_to_dict(row)


def search_insurance_plans(carrier_num):
    """Search for insurance plans by carrier."""
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT p.*, c.CarrierName FROM insplans p "
        "JOIN carriers c ON p.CarrierNum = c.CarrierNum "
        "WHERE p.CarrierNum=?",
        (carrier_num,),
    )
    rows = cur.fetchall()
    conn.close()
    return _rows_to_list(rows)


def create_insurance_plan(carrier_num, group_name=None, group_num=None,
                          plan_type=""):
    """Create a new insurance plan."""
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO insplans (CarrierNum, GroupName, GroupNum, PlanType) "
        "VALUES (?,?,?,?)",
        (carrier_num, group_name, group_num, plan_type),
    )
    plan_num = cur.lastrowid
    conn.commit()
    conn.close()

    logger.info(f"Mock: Created insurance plan (PlanNum={plan_num}) for CarrierNum={carrier_num}")
    return {"PlanNum": plan_num, "CarrierNum": carrier_num, "GroupName": group_name, "GroupNum": group_num}


def create_insurance_sub(plan_num, subscriber_pat_num, subscriber_id,
                         date_effective=None):
    """Create an insurance subscription (link plan to subscriber)."""
    conn = db.get_connection()
    cur = conn.cursor()
    if not date_effective:
        date_effective = datetime.now().strftime("%Y-%m-%d")
    cur.execute(
        "INSERT INTO inssubs (PlanNum, Subscriber, SubscriberID, DateEffective) "
        "VALUES (?,?,?,?)",
        (plan_num, subscriber_pat_num, subscriber_id, date_effective),
    )
    ins_sub_num = cur.lastrowid
    conn.commit()
    conn.close()

    logger.info(f"Mock: Created insurance sub (InsSubNum={ins_sub_num}) for PatNum={subscriber_pat_num}")
    return {"InsSubNum": ins_sub_num, "PlanNum": plan_num, "Subscriber": subscriber_pat_num,
            "SubscriberID": subscriber_id}


def create_patient_plan(pat_num, ins_sub_num, ordinal=1, relationship="Self"):
    """Assign a patient to an insurance subscription."""
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO patplans (PatNum, InsSubNum, Ordinal, Relationship) "
        "VALUES (?,?,?,?)",
        (pat_num, ins_sub_num, ordinal, relationship),
    )
    pat_plan_num = cur.lastrowid
    conn.commit()
    conn.close()

    logger.info(f"Mock: Created patient plan (PatPlanNum={pat_plan_num}) for PatNum={pat_num}")
    return {"PatPlanNum": pat_plan_num, "PatNum": pat_num, "InsSubNum": ins_sub_num,
            "Ordinal": ordinal, "Relationship": relationship}


def get_benefits(plan_num):
    """Get benefit details for an insurance plan."""
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM benefits WHERE PlanNum=?", (plan_num,))
    rows = cur.fetchall()
    conn.close()
    return _rows_to_list(rows)


def verify_insurance(pat_plan_num):
    """Mark insurance as verified with today's date."""
    conn = db.get_connection()
    cur = conn.cursor()
    now = datetime.now()
    cur.execute(
        "INSERT INTO insverifies (VerifyType, FKey, DateLastVerified, Note, DateTimeEntry) "
        "VALUES (?,?,?,?,?)",
        ("PatientEnrollment", pat_plan_num, now.strftime("%Y-%m-%d"),
         "Verified via AI phone call", now.strftime("%Y-%m-%d %H:%M:%S")),
    )
    verify_num = cur.lastrowid
    conn.commit()
    conn.close()

    logger.info(f"Mock: Verified insurance for PatPlanNum={pat_plan_num}")
    return {"InsVerifyNum": verify_num, "VerifyType": "PatientEnrollment",
            "FKey": pat_plan_num, "DateLastVerified": now.strftime("%Y-%m-%d")}

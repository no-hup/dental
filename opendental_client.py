"""OpenDental API client for Dental Voice AI Agent.

All interactions with the OpenDental REST API go through this module.
Auth header: Authorization: ODFHIR {DeveloperKey}/{CustomerKey}

When MOCK_MODE is enabled, all API functions are replaced by local SQLite
equivalents from mock_opendental.py — the rest of the app sees no difference.
"""

import logging
import requests
from datetime import datetime, timedelta

import config

logger = logging.getLogger(__name__)



def _headers():
    """Build auth headers for OpenDental API."""
    return {
        "Authorization": f"ODFHIR {config.OPENDENTAL_DEVELOPER_KEY}/{config.OPENDENTAL_CUSTOMER_KEY}",
        "Content-Type": "application/json",
    }


def _get(endpoint, params=None):
    """GET request to OpenDental API."""
    url = f"{config.OPENDENTAL_BASE_URL}{endpoint}"
    try:
        resp = requests.get(url, headers=_headers(), params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"OpenDental GET {endpoint} failed: {e}")
        return None


def _post(endpoint, data=None):
    """POST request to OpenDental API."""
    url = f"{config.OPENDENTAL_BASE_URL}{endpoint}"
    try:
        resp = requests.post(url, headers=_headers(), json=data, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"OpenDental POST {endpoint} failed: {e}")
        return None


def _put(endpoint, data=None):
    """PUT request to OpenDental API."""
    url = f"{config.OPENDENTAL_BASE_URL}{endpoint}"
    try:
        resp = requests.put(url, headers=_headers(), json=data, timeout=15)
        resp.raise_for_status()
        # Some PUT endpoints return 200 with no body
        try:
            return resp.json()
        except ValueError:
            return {"status": "ok"}
    except requests.exceptions.RequestException as e:
        logger.error(f"OpenDental PUT {endpoint} failed: {e}")
        return None


# ── Patient Endpoints ────────────────────────────────────────────────


def lookup_patient_by_phone(phone):
    """Search for patient by phone number.

    The Phone parameter matches HmPhone, WkPhone, and WirelessPhone.
    Returns list of condensed patient objects, or empty list.
    """
    # Strip +1 country code for OpenDental (expects 10-digit)
    clean_phone = phone.lstrip("+")
    if clean_phone.startswith("1") and len(clean_phone) == 11:
        clean_phone = clean_phone[1:]

    result = _get("/patients", params={"Phone": clean_phone})
    if result and isinstance(result, list):
        return result
    return []


def get_patient(pat_num):
    """Get full patient record by PatNum."""
    return _get(f"/patients/{pat_num}")


def create_patient(first_name, last_name, phone=None, birthdate=None,
                   email=None, gender=None):
    """Create a new patient in OpenDental.

    Returns created patient object with PatNum.
    """
    data = {
        "LName": last_name,
        "FName": first_name,
    }
    if phone:
        clean_phone = phone.lstrip("+")
        if clean_phone.startswith("1") and len(clean_phone) == 11:
            clean_phone = clean_phone[1:]
        data["WirelessPhone"] = clean_phone
    if birthdate:
        data["Birthdate"] = birthdate
    if email:
        data["Email"] = email
    if gender:
        # OpenDental expects: 0=Male, 1=Female, 2=Unknown
        gender_map = {"male": 0, "female": 1, "m": 0, "f": 1}
        data["Gender"] = gender_map.get(gender.lower(), 2)

    return _post("/patients", data=data)


# ── Appointment Endpoints ────────────────────────────────────────────


def get_patient_appointments(pat_num, status="Scheduled"):
    """Get appointments for a patient, filtered by status.

    Status options: Scheduled, Complete, Broken, UnschedList, Planned
    """
    return _get("/appointments", params={
        "PatNum": pat_num,
        "AptStatus": status,
    })


def get_appointment(apt_num):
    """Get a single appointment by AptNum."""
    return _get(f"/appointments/{apt_num}")


def get_available_slots(date_start=None, date_end=None, prov_num=None,
                        op_num=None, length_minutes=None):
    """Get available appointment slots.

    Returns array of: DateTimeStart, DateTimeEnd, ProvNum, OpNum
    """
    params = {}
    if date_start:
        params["dateStart"] = date_start
    if date_end:
        params["dateEnd"] = date_end
    if prov_num:
        params["ProvNum"] = prov_num
    if op_num:
        params["OpNum"] = op_num
    if length_minutes:
        params["lengthMinutes"] = length_minutes

    return _get("/appointments/Slots", params=params)


def book_appointment(pat_num, op_num, apt_datetime, pattern=None,
                     prov_num=None, is_new_patient=False, note=None,
                     appointment_type_num=None):
    """Create a new appointment.

    Args:
        pat_num: Patient number
        op_num: Operatory number
        apt_datetime: Appointment datetime as 'yyyy-MM-dd HH:mm:ss'
        pattern: Duration pattern (each char = 5 min, X=provider, /=assistant)
                 Default '/XX/' = 20 minutes
        prov_num: Provider number (optional)
        is_new_patient: Whether this is a new patient appointment
        note: Appointment note
        appointment_type_num: Appointment type number
    """
    data = {
        "PatNum": pat_num,
        "Op": op_num,
        "AptDateTime": apt_datetime,
    }
    if pattern:
        data["Pattern"] = pattern
    if prov_num:
        data["ProvNum"] = prov_num
    if is_new_patient:
        data["IsNewPatient"] = "true"
    if note:
        data["Note"] = note
    if appointment_type_num:
        data["AppointmentTypeNum"] = appointment_type_num

    return _post("/appointments", data=data)


def confirm_appointment(apt_num, confirm_val="Confirmed"):
    """Confirm an appointment.

    confirm_val options: None, Sent, Confirmed, Not Accepted, Failed
    """
    return _put(f"/appointments/{apt_num}/Confirm", data={
        "confirmVal": confirm_val,
    })


def reschedule_appointment(apt_num, new_datetime=None, new_op=None,
                           new_prov_num=None):
    """Reschedule an appointment by updating its datetime and/or operatory."""
    data = {}
    if new_datetime:
        data["AptDateTime"] = new_datetime
    if new_op:
        data["Op"] = new_op
    if new_prov_num:
        data["ProvNum"] = new_prov_num
    if not data:
        return None
    return _put(f"/appointments/{apt_num}", data=data)


def cancel_appointment(apt_num, send_to_unscheduled=True):
    """Cancel (break) an appointment.

    Uses breakType=Cancelled which adds D9987 procedure code.
    """
    return _put(f"/appointments/{apt_num}/Break", data={
        "sendToUnscheduledList": "true" if send_to_unscheduled else "false",
        "breakType": "Cancelled",
    })


# ── Provider & Operatory Endpoints ───────────────────────────────────


def get_providers(clinic_num=None):
    """Get all providers, optionally filtered by clinic."""
    params = {}
    if clinic_num:
        params["ClinicNum"] = clinic_num
    return _get("/providers", params=params)


def get_provider(prov_num):
    """Get a single provider by ProvNum."""
    return _get(f"/providers/{prov_num}")


def get_operatories(clinic_num=None):
    """Get all operatories, optionally filtered by clinic."""
    params = {}
    if clinic_num:
        params["ClinicNum"] = clinic_num
    return _get("/operatories", params=params)


def get_appointment_types():
    """Get all configured appointment types."""
    return _get("/appointmenttypes")


# ── Recall Endpoints ─────────────────────────────────────────────────


def get_recalls(pat_num):
    """Get recall/recare info for a patient."""
    return _get("/recalls", params={"PatNum": pat_num})


def get_recall_list(date_start=None, date_end=None):
    """Get patients due for recall in a date range.

    Returns list with patient info, recall type, due date, reminder count.
    """
    params = {}
    if date_start:
        params["DateStart"] = date_start
    if date_end:
        params["DateEnd"] = date_end
    return _get("/recalls/List", params=params)


def update_recall_status(pat_num, recall_type="Prophy", status="Contacted", note=None):
    """Mark recall as contacted. Auto-creates a CommLog with CommType.Recall."""
    data = {
        "PatNum": pat_num,
        "RecallType": recall_type,
        "Status": status,
    }
    if note:
        data["Note"] = note
    return _put("/recalls/Status", data=data)


# ── Appointment Bulk Endpoints ──────────────────────────────────────


def get_appointments_date_range(date_start, date_end, status="Scheduled"):
    """Bulk-fetch appointments in a date range.

    Used by the outbound confirmation runner to build the call queue.
    """
    params = {
        "dateStart": date_start,
        "dateEnd": date_end,
        "AptStatus": status,
    }
    return _get("/appointments", params=params)


def append_appointment_note(apt_num, note):
    """Append a note to an appointment (e.g., 'Confirmed via AI call 2/19')."""
    return _put(f"/appointments/{apt_num}/Note", data={
        "Note": note,
    })


# ── Insurance Endpoints ──────────────────────────────────────────────


def get_patient_insurance(pat_num):
    """Get patient's current insurance info (combined view).

    Returns carrier, plan, subscriber, and coverage details.
    """
    return _get(f"/familymodules/{pat_num}/Insurance")


def search_carriers(name):
    """Search for insurance carriers by name."""
    result = _get("/carriers", params={"CarrierName": name})
    if result and isinstance(result, list):
        return result
    return []


def create_carrier(name, phone=None, address=None, city=None,
                   state=None, zip_code=None, elect_id=None):
    """Create a new insurance carrier."""
    data = {"CarrierName": name}
    if phone:
        data["Phone"] = phone
    if address:
        data["Address"] = address
    if city:
        data["City"] = city
    if state:
        data["State"] = state
    if zip_code:
        data["Zip"] = zip_code
    if elect_id:
        data["ElectID"] = elect_id
    return _post("/carriers", data=data)


def get_insurance_plan(plan_num):
    """Get insurance plan details by PlanNum."""
    return _get(f"/insplans/{plan_num}")


def search_insurance_plans(carrier_num):
    """Search for insurance plans by carrier."""
    result = _get("/insplans", params={"CarrierNum": carrier_num})
    if result and isinstance(result, list):
        return result
    return []


def create_insurance_plan(carrier_num, group_name=None, group_num=None,
                          plan_type=""):
    """Create a new insurance plan."""
    data = {"CarrierNum": carrier_num}
    if group_name:
        data["GroupName"] = group_name
    if group_num:
        data["GroupNum"] = group_num
    if plan_type:
        data["PlanType"] = plan_type
    return _post("/insplans", data=data)


def create_insurance_sub(plan_num, subscriber_pat_num, subscriber_id,
                         date_effective=None):
    """Create an insurance subscription (link plan to subscriber).

    Args:
        plan_num: Insurance plan number
        subscriber_pat_num: PatNum of the policyholder
        subscriber_id: Member ID / subscriber ID
        date_effective: Effective date (YYYY-MM-DD)
    """
    data = {
        "PlanNum": plan_num,
        "Subscriber": subscriber_pat_num,
        "SubscriberID": subscriber_id,
    }
    if date_effective:
        data["DateEffective"] = date_effective
    return _post("/inssubs", data=data)


def create_patient_plan(pat_num, ins_sub_num, ordinal=1, relationship="Self"):
    """Assign a patient to an insurance subscription.

    Args:
        pat_num: Patient number
        ins_sub_num: Insurance subscription number
        ordinal: 1=primary, 2=secondary
        relationship: Self, Spouse, Child, Other
    """
    data = {
        "PatNum": pat_num,
        "InsSubNum": ins_sub_num,
        "Ordinal": ordinal,
        "Relationship": relationship,
    }
    return _post("/patplans", data=data)


def get_benefits(plan_num):
    """Get benefit details for an insurance plan."""
    return _get("/benefits", params={"PlanNum": plan_num})


def verify_insurance(pat_plan_num):
    """Mark insurance as verified with today's date."""
    return _put("/insverifies", data={
        "VerifyType": "PatientEnrollment",
        "FKey": pat_plan_num,
        "DateLastVerified": datetime.now().strftime("%Y-%m-%d"),
    })


# ── Communication Log ────────────────────────────────────────────────


def create_commlog(pat_num, note, mode="Phone"):
    """Log a communication entry (e.g., phone call) to the patient's chart.

    Mode options: None, Email, Mail, Phone, InPerson, Text
    """
    # CommMode_ values: 0=None, 1=Email, 2=Mail, 3=Phone, 4=InPerson, 5=Text
    mode_map = {
        "None": 0, "Email": 1, "Mail": 2, "Phone": 3,
        "InPerson": 4, "Text": 5,
    }
    data = {
        "PatNum": pat_num,
        "Note": note,
        "Mode_": mode_map.get(mode, 3),
        "CommDateTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    return _post("/commlogs", data=data)


# ── Formatting Helpers ───────────────────────────────────────────────


def format_datetime_voice(dt_string):
    """Convert 'yyyy-MM-dd HH:mm:ss' to voice-friendly format.

    Example: '2026-02-26 09:00:00' → 'Thursday February 26th at 9 AM'
    """
    try:
        dt = datetime.strptime(dt_string, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        try:
            dt = datetime.strptime(dt_string, "%Y-%m-%dT%H:%M:%S")
        except (ValueError, TypeError):
            return dt_string or "unknown"

    day_name = dt.strftime("%A")
    month = dt.strftime("%B")
    day = dt.day
    h = dt.hour
    m = dt.minute
    period = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    time_str = f"{h12}:{m:02d} {period}" if m else f"{h12} {period}"

    return f"{day_name} {month} {day} at {time_str}"


def format_slot_voice(slot, providers_cache=None):
    """Format an appointment slot into a voice-friendly string.

    Args:
        slot: Dict with DateTimeStart, DateTimeEnd, ProvNum, OpNum
        providers_cache: Optional dict of ProvNum -> provider name
    """
    dt_str = slot.get("DateTimeStart", "")
    prov_num = slot.get("ProvNum")
    provider_name = ""

    if providers_cache and prov_num and prov_num in providers_cache:
        provider_name = providers_cache[prov_num]

    time_display = format_datetime_voice(dt_str)

    if provider_name:
        return f"{time_display} with {provider_name}"
    return time_display


# ── Mock Mode Override ───────────────────────────────────────────────
# When MOCK_MODE is enabled, replace all API functions with local SQLite
# equivalents.  This MUST be at the bottom so the imports shadow the real
# function definitions above.  format_datetime_voice and format_slot_voice
# are pure formatters and are NOT overridden.

if config.MOCK_MODE:
    from mock_opendental import (  # noqa: F811
        lookup_patient_by_phone,
        get_patient,
        create_patient,
        get_patient_appointments,
        get_appointment,
        get_available_slots,
        book_appointment,
        confirm_appointment,
        reschedule_appointment,
        cancel_appointment,
        get_providers,
        get_provider,
        get_operatories,
        get_appointment_types,
        get_recalls,
        create_commlog,
        get_recall_list,
        update_recall_status,
        get_appointments_date_range,
        append_appointment_note,
        get_patient_insurance,
        search_carriers,
        create_carrier,
        get_insurance_plan,
        search_insurance_plans,
        create_insurance_plan,
        create_insurance_sub,
        create_patient_plan,
        get_benefits,
        verify_insurance,
    )
    import mock_opendental_db
    mock_opendental_db.initialize()

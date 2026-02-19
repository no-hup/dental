"""SQLite database for mock OpenDental API.

Creates and seeds a local database with realistic dental office data.
Dates are always relative to today so the data never goes stale.
"""

import sqlite3
import logging
import random
from datetime import datetime, timedelta, date
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "mock_dental.db"

# ── Schema ───────────────────────────────────────────────────────────


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS patients (
    PatNum INTEGER PRIMARY KEY,
    LName TEXT NOT NULL,
    FName TEXT NOT NULL,
    Birthdate TEXT,
    Gender INTEGER DEFAULT 2,
    Email TEXT,
    HmPhone TEXT,
    WkPhone TEXT,
    WirelessPhone TEXT,
    Address TEXT,
    City TEXT,
    State TEXT,
    Zip TEXT,
    PriProv INTEGER,
    PatStatus INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS providers (
    ProvNum INTEGER PRIMARY KEY,
    LName TEXT NOT NULL,
    FName TEXT NOT NULL,
    Abbr TEXT,
    Specialty TEXT,
    IsHidden INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS operatories (
    OperatoryNum INTEGER PRIMARY KEY,
    OpName TEXT NOT NULL,
    ProvDentist INTEGER,
    ProvHygienist INTEGER,
    IsHidden INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS appointments (
    AptNum INTEGER PRIMARY KEY AUTOINCREMENT,
    PatNum INTEGER NOT NULL,
    ProvNum INTEGER,
    Op INTEGER,
    AptDateTime TEXT NOT NULL,
    AptStatus TEXT DEFAULT 'Scheduled',
    Pattern TEXT DEFAULT '/XX/',
    IsNewPatient TEXT DEFAULT 'false',
    Note TEXT,
    AppointmentTypeNum INTEGER,
    Confirmed TEXT DEFAULT 'None',
    FOREIGN KEY (PatNum) REFERENCES patients(PatNum)
);

CREATE TABLE IF NOT EXISTS appointment_types (
    AppointmentTypeNum INTEGER PRIMARY KEY,
    AppointmentTypeName TEXT NOT NULL,
    Pattern TEXT,
    DefaultMinutes INTEGER
);

CREATE TABLE IF NOT EXISTS recalls (
    RecallNum INTEGER PRIMARY KEY AUTOINCREMENT,
    PatNum INTEGER NOT NULL,
    DateDue TEXT,
    RecallType TEXT DEFAULT 'Prophy',
    FOREIGN KEY (PatNum) REFERENCES patients(PatNum)
);

CREATE TABLE IF NOT EXISTS commlogs (
    CommlogNum INTEGER PRIMARY KEY AUTOINCREMENT,
    PatNum INTEGER NOT NULL,
    Note TEXT,
    Mode_ INTEGER DEFAULT 3,
    CommDateTime TEXT,
    FOREIGN KEY (PatNum) REFERENCES patients(PatNum)
);

CREATE TABLE IF NOT EXISTS carriers (
    CarrierNum INTEGER PRIMARY KEY AUTOINCREMENT,
    CarrierName TEXT NOT NULL,
    Phone TEXT,
    Address TEXT,
    City TEXT,
    State TEXT,
    Zip TEXT,
    ElectID TEXT,
    NoSendElect INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS insplans (
    PlanNum INTEGER PRIMARY KEY AUTOINCREMENT,
    CarrierNum INTEGER NOT NULL,
    GroupName TEXT,
    GroupNum TEXT,
    PlanType TEXT DEFAULT '',
    DivisionNo TEXT,
    EmployerNum INTEGER DEFAULT 0,
    FOREIGN KEY (CarrierNum) REFERENCES carriers(CarrierNum)
);

CREATE TABLE IF NOT EXISTS inssubs (
    InsSubNum INTEGER PRIMARY KEY AUTOINCREMENT,
    PlanNum INTEGER NOT NULL,
    Subscriber INTEGER NOT NULL,
    SubscriberID TEXT,
    DateEffective TEXT,
    DateTerm TEXT,
    ReleaseInfo INTEGER DEFAULT 1,
    AssignBen INTEGER DEFAULT 1,
    FOREIGN KEY (PlanNum) REFERENCES insplans(PlanNum),
    FOREIGN KEY (Subscriber) REFERENCES patients(PatNum)
);

CREATE TABLE IF NOT EXISTS patplans (
    PatPlanNum INTEGER PRIMARY KEY AUTOINCREMENT,
    PatNum INTEGER NOT NULL,
    InsSubNum INTEGER NOT NULL,
    Ordinal INTEGER DEFAULT 1,
    Relationship TEXT DEFAULT 'Self',
    FOREIGN KEY (PatNum) REFERENCES patients(PatNum),
    FOREIGN KEY (InsSubNum) REFERENCES inssubs(InsSubNum)
);

CREATE TABLE IF NOT EXISTS benefits (
    BenefitNum INTEGER PRIMARY KEY AUTOINCREMENT,
    PlanNum INTEGER NOT NULL,
    BenefitType TEXT DEFAULT 'Limitations',
    CovCatNum INTEGER DEFAULT 0,
    Percent INTEGER DEFAULT -1,
    MonetaryAmt REAL DEFAULT -1,
    TimePeriod TEXT DEFAULT 'CalendarYear',
    QuantityQualifier TEXT DEFAULT 'None',
    Quantity INTEGER DEFAULT 0,
    CodeNum INTEGER DEFAULT 0,
    CoverageLevel TEXT DEFAULT 'None',
    FOREIGN KEY (PlanNum) REFERENCES insplans(PlanNum)
);

CREATE TABLE IF NOT EXISTS insverifies (
    InsVerifyNum INTEGER PRIMARY KEY AUTOINCREMENT,
    VerifyType TEXT NOT NULL,
    FKey INTEGER NOT NULL,
    DateLastVerified TEXT,
    DefNum INTEGER DEFAULT 0,
    Note TEXT,
    DateLastAssigned TEXT,
    DateTimeEntry TEXT
);

CREATE TABLE IF NOT EXISTS seed_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    seed_date TEXT NOT NULL
);
"""

# ── Seed Data ────────────────────────────────────────────────────────


def _seed_providers(cur):
    providers = [
        (1, "Mitchell", "Sarah", "Dr. Mitchell", "General"),
        (2, "Rodriguez", "James", "Dr. Rodriguez", "General"),
        (3, "Chen", "Emily", "Dr. Chen", "Orthodontics"),
        (4, "Thompson", "Lisa", "Lisa T.", "Hygienist"),
        (5, "Davis", "Rachel", "Rachel D.", "Hygienist"),
    ]
    cur.executemany(
        "INSERT INTO providers (ProvNum, LName, FName, Abbr, Specialty) VALUES (?,?,?,?,?)",
        providers,
    )


def _seed_operatories(cur):
    operatories = [
        (1, "Op 1", 1, 4),
        (2, "Op 2", 1, 4),
        (3, "Op 3", 2, 5),
        (4, "Op 4", 2, 5),
        (5, "Ortho Suite", 3, None),
        (6, "Hygiene A", 4, None),
        (7, "Hygiene B", 5, None),
    ]
    cur.executemany(
        "INSERT INTO operatories (OperatoryNum, OpName, ProvDentist, ProvHygienist) VALUES (?,?,?,?)",
        operatories,
    )


def _seed_appointment_types(cur):
    types = [
        (1, "New Patient Exam", "/XXXXXXXXXX/", 60),
        (2, "Periodic Exam", "/XX/", 20),
        (3, "Cleaning", "/XXXXXXXXXX/", 60),
        (4, "Filling", "/XXXXXX/", 30),
        (5, "Crown Prep", "/XXXXXXXXXXXXXXXX/", 90),
        (6, "Extraction", "/XXXXXXXXXX/", 60),
    ]
    cur.executemany(
        "INSERT INTO appointment_types (AppointmentTypeNum, AppointmentTypeName, Pattern, DefaultMinutes) VALUES (?,?,?,?)",
        types,
    )


def _seed_brian(cur, today):
    """Seed Brian West as PatNum=100."""
    cur.execute(
        "INSERT INTO patients (PatNum, LName, FName, Birthdate, Gender, Email, WirelessPhone, Address, City, State, Zip, PriProv) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (100, "West", "Brian", "1977-02-18", 0, "brian@example.com",
         "9184249378", "123 Main St", "Tulsa", "OK", "74103", 1),
    )

    # Brian's appointments
    apt1_dt = (today + timedelta(days=8)).strftime("%Y-%m-%d") + " 09:00:00"
    apt2_dt = (today + timedelta(days=15)).strftime("%Y-%m-%d") + " 14:00:00"

    cur.execute(
        "INSERT INTO appointments (AptNum, PatNum, ProvNum, Op, AptDateTime, Pattern, Note, AppointmentTypeNum) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (1001, 100, 4, 6, apt1_dt, "/XXXXXXXXXX/", "Cleaning/checkup", 3),
    )
    cur.execute(
        "INSERT INTO appointments (AptNum, PatNum, ProvNum, Op, AptDateTime, Pattern, Note, AppointmentTypeNum) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (1002, 100, 1, 1, apt2_dt, "/XXXXXXXXXXXXXXXX/", "Crown prep #14", 5),
    )

    # Brian's recall
    recall_due = (today + timedelta(days=10)).strftime("%Y-%m-%d")
    cur.execute(
        "INSERT INTO recalls (PatNum, DateDue, RecallType) VALUES (?,?,?)",
        (100, recall_due, "Prophy"),
    )


def _seed_brian_insurance(cur):
    """Seed Brian West with Delta Dental PPO insurance."""
    # Carrier: Delta Dental
    cur.execute(
        "INSERT INTO carriers (CarrierNum, CarrierName, Phone, Address, City, State, Zip, ElectID) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (1, "Delta Dental", "8005551234", "PO Box 9085", "Farmington Hills", "MI", "48333", "DELTAP"),
    )

    # Insurance Plan: Delta Dental PPO
    cur.execute(
        "INSERT INTO insplans (PlanNum, CarrierNum, GroupName, GroupNum, PlanType) "
        "VALUES (?,?,?,?,?)",
        (1, 1, "Premier PPO", "12345", "p"),
    )

    # Subscription: Brian is the subscriber
    cur.execute(
        "INSERT INTO inssubs (InsSubNum, PlanNum, Subscriber, SubscriberID, DateEffective) "
        "VALUES (?,?,?,?,?)",
        (1, 1, 100, "DEN123456", "2024-01-01"),
    )

    # Patient Plan: Brian linked to his own subscription, primary
    cur.execute(
        "INSERT INTO patplans (PatPlanNum, PatNum, InsSubNum, Ordinal, Relationship) "
        "VALUES (?,?,?,?,?)",
        (1, 100, 1, 1, "Self"),
    )

    # Benefits for Delta Dental PPO
    benefits = [
        (1, 1, "Limitations", 0, -1, 1500.0, "CalendarYear", "None", 0, 0, "Individual"),   # Annual max
        (2, 1, "Limitations", 0, -1, 50.0, "CalendarYear", "None", 0, 0, "Individual"),      # Deductible
        (3, 1, "CoInsurance", 1, 100, -1, "CalendarYear", "None", 0, 0, "None"),  # Preventive 100%
        (4, 1, "CoInsurance", 2, 80, -1, "CalendarYear", "None", 0, 0, "None"),   # Basic 80%
        (5, 1, "CoInsurance", 3, 50, -1, "CalendarYear", "None", 0, 0, "None"),   # Major 50%
    ]
    cur.executemany(
        "INSERT INTO benefits (BenefitNum, PlanNum, BenefitType, CovCatNum, Percent, MonetaryAmt, "
        "TimePeriod, QuantityQualifier, Quantity, CodeNum, CoverageLevel) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        benefits,
    )

    # Insurance verification (verified today)
    cur.execute(
        "INSERT INTO insverifies (InsVerifyNum, VerifyType, FKey, DateLastVerified, Note, DateTimeEntry) "
        "VALUES (?,?,?,?,?,?)",
        (1, "PatientEnrollment", 1, datetime.now().strftime("%Y-%m-%d"),
         "Verified via phone", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )


def _seed_filler_patients(cur):
    """Seed 10 fake patients (PatNum 200-209)."""
    first_names = ["Alice", "Bob", "Carol", "David", "Eva",
                   "Frank", "Grace", "Henry", "Iris", "Jack"]
    last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones",
                  "Garcia", "Miller", "Davis", "Wilson", "Moore"]

    for i in range(10):
        pat_num = 200 + i
        cur.execute(
            "INSERT INTO patients (PatNum, LName, FName, Birthdate, Gender, WirelessPhone, PriProv) "
            "VALUES (?,?,?,?,?,?,?)",
            (pat_num, last_names[i], first_names[i],
             f"{random.randint(1960,2000)}-{random.randint(1,12):02d}-{random.randint(1,28):02d}",
             random.choice([0, 1]),
             f"918555{random.randint(1000,9999)}",
             random.choice([1, 2])),
        )


def _seed_filler_appointments(cur, today):
    """Create 18-25 filler appointments over the next 14 business days."""
    # Collect business days
    business_days = []
    d = today + timedelta(days=1)
    while len(business_days) < 14:
        if d.weekday() < 5:  # Mon-Fri
            business_days.append(d)
        d += timedelta(days=1)

    # Provider -> operatory mapping
    prov_ops = {1: [1, 2], 2: [3, 4], 3: [5], 4: [6], 5: [7]}

    # Morning and afternoon start times (avoiding lunch 12-1)
    morning_times = ["08:00:00", "08:30:00", "09:00:00", "09:30:00",
                     "10:00:00", "10:30:00", "11:00:00"]
    afternoon_times = ["13:00:00", "13:30:00", "14:00:00", "14:30:00",
                       "15:00:00", "15:30:00", "16:00:00"]
    all_times = morning_times + afternoon_times

    num_filler = random.randint(18, 25)
    apt_type_choices = [
        (2, "/XX/", "Periodic exam"),
        (3, "/XXXXXXXXXX/", "Cleaning"),
        (4, "/XXXXXX/", "Filling"),
        (5, "/XXXXXXXXXXXXXXXX/", "Crown prep"),
        (6, "/XXXXXXXXXX/", "Extraction"),
    ]

    used_slots = set()  # (date_str, time_str, prov_num) to avoid double-booking

    for _ in range(num_filler):
        pat_num = random.choice(range(200, 210))
        prov_num = random.choice([1, 2, 3, 4, 5])
        day = random.choice(business_days)
        time_str = random.choice(all_times)
        apt_type_num, pattern, note = random.choice(apt_type_choices)
        ops = prov_ops[prov_num]
        op = random.choice(ops)

        slot_key = (day.strftime("%Y-%m-%d"), time_str, prov_num)
        if slot_key in used_slots:
            continue
        used_slots.add(slot_key)

        dt_str = f"{day.strftime('%Y-%m-%d')} {time_str}"
        cur.execute(
            "INSERT INTO appointments (PatNum, ProvNum, Op, AptDateTime, AptStatus, Pattern, Note, AppointmentTypeNum) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (pat_num, prov_num, op, dt_str, "Scheduled", pattern, note, apt_type_num),
        )


def _seed_outbound_confirmation_data(cur, today):
    """Seed unconfirmed appointments in the confirmation window (next 3 days)
    and recall entries with varying DateDue values for outbound testing."""

    # Unconfirmed appointments for filler patients in the next 1-3 days
    prov_ops = {1: [1, 2], 2: [3, 4], 4: [6], 5: [7]}
    confirmation_apts = [
        (200, 1, "09:00:00", "/XXXXXX/", "Filling", 4, 1),
        (201, 2, "10:30:00", "/XXXXXXXXXX/", "Cleaning", 3, 2),
        (202, 4, "14:00:00", "/XXXXXXXXXX/", "Cleaning", 3, 1),
        (203, 1, "15:30:00", "/XXXXXXXXXXXXXXXX/", "Crown prep", 5, 2),
        (204, 5, "08:30:00", "/XXXXXXXXXX/", "Cleaning", 3, 3),
        (205, 2, "11:00:00", "/XXXXXX/", "Filling", 4, 1),
    ]

    for pat_num, prov_num, time_str, pattern, note, apt_type, days_ahead in confirmation_apts:
        apt_day = today + timedelta(days=days_ahead)
        # Skip weekends
        while apt_day.weekday() >= 5:
            apt_day += timedelta(days=1)
        dt_str = f"{apt_day.strftime('%Y-%m-%d')} {time_str}"
        ops = prov_ops.get(prov_num, [1])
        cur.execute(
            "INSERT INTO appointments (PatNum, ProvNum, Op, AptDateTime, AptStatus, "
            "Pattern, Note, AppointmentTypeNum, Confirmed) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (pat_num, prov_num, ops[0], dt_str, "Scheduled", pattern,
             note, apt_type, "None"),  # Confirmed='None' = unconfirmed
        )

    # Recall entries for various filler patients with varying due dates
    recall_entries = [
        (201, today + timedelta(days=2), "Prophy"),      # Due in 2 days
        (203, today + timedelta(days=5), "Prophy"),      # Due in 5 days
        (205, today + timedelta(days=7), "Prophy"),      # Due in 7 days
        (206, today + timedelta(days=10), "Prophy"),     # Due in 10 days
        (208, today + timedelta(days=14), "PerioMaint"), # Due in 14 days
    ]

    for pat_num, due_date, recall_type in recall_entries:
        cur.execute(
            "INSERT INTO recalls (PatNum, DateDue, RecallType) VALUES (?,?,?)",
            (pat_num, due_date.strftime("%Y-%m-%d"), recall_type),
        )


# ── Database Lifecycle ───────────────────────────────────────────────


def _is_stale(conn):
    """Check if the seed data needs refreshing (dates in the past)."""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='seed_meta'")
    if not cur.fetchone():
        return True
    cur.execute("SELECT seed_date FROM seed_meta WHERE id=1")
    row = cur.fetchone()
    if not row:
        return True
    try:
        seed_date = datetime.strptime(row[0], "%Y-%m-%d").date()
        return seed_date < date.today()
    except (ValueError, TypeError):
        return True


def _drop_all(conn):
    """Drop all tables for a fresh re-seed."""
    cur = conn.cursor()
    tables = ["insverifies", "benefits", "patplans", "inssubs", "insplans", "carriers",
              "commlogs", "recalls", "appointments", "appointment_types",
              "operatories", "providers", "patients", "seed_meta"]
    for t in tables:
        cur.execute(f"DROP TABLE IF EXISTS {t}")
    conn.commit()


def _seed_all(conn):
    """Create schema and insert all seed data."""
    today = date.today()
    cur = conn.cursor()
    cur.executescript(SCHEMA_SQL)

    _seed_providers(cur)
    _seed_operatories(cur)
    _seed_appointment_types(cur)
    _seed_brian(cur, today)
    _seed_brian_insurance(cur)
    _seed_filler_patients(cur)
    _seed_filler_appointments(cur, today)
    _seed_outbound_confirmation_data(cur, today)

    cur.execute(
        "INSERT OR REPLACE INTO seed_meta (id, seed_date) VALUES (1, ?)",
        (today.strftime("%Y-%m-%d"),),
    )
    conn.commit()
    logger.info(f"Mock DB seeded for {today}")


def get_connection():
    """Get a SQLite connection, seeding/refreshing if needed."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    if _is_stale(conn):
        logger.info("Mock DB is stale or missing — re-seeding...")
        _drop_all(conn)
        _seed_all(conn)

    return conn


def initialize():
    """Ensure the database is ready. Called once at startup."""
    conn = get_connection()
    # Verify seed data
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM providers")
    prov_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM patients")
    pat_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM appointments")
    apt_count = cur.fetchone()[0]
    conn.close()
    logger.info(f"Mock DB ready: {prov_count} providers, {pat_count} patients, {apt_count} appointments")
    return prov_count

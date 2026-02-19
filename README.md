# Dental Voice AI Agent

A voice-powered dental office receptionist built on [SignalWire AI Agents](https://github.com/signalwire/signalwire-agents) and the [OpenDental API](https://www.opendental.com/site/apispecification.html). Patients call in and the AI handles appointment booking, confirmation, rescheduling, cancellation, and insurance management. An outbound agent proactively calls patients to confirm upcoming appointments and remind them about overdue recalls.

## Table of Contents

- [Architecture](#architecture)
- [Setup](#setup)
  - [Mock Mode](#mock-mode)
- [Inbound Agent](#inbound-agent)
  - [Caller Recognition and Identity Verification](#caller-recognition-and-identity-verification)
  - [Flow 1: New Patient Onboarding](#flow-1-new-patient-onboarding)
  - [Flow 2: Book Appointment](#flow-2-book-appointment)
  - [Flow 3: Confirm Appointment](#flow-3-confirm-appointment)
  - [Flow 4: Reschedule Appointment](#flow-4-reschedule-appointment)
  - [Flow 5: Cancel Appointment](#flow-5-cancel-appointment)
  - [Flow 6: Insurance](#flow-6-insurance)
  - [Error Recovery and Wrap Up](#error-recovery-and-wrap-up)
  - [Complete State Machine](#complete-inbound-state-machine)
- [Outbound Agent](#outbound-agent)
  - [Confirmation Runner](#confirmation-runner)
  - [Appointment Confirmation Flow](#appointment-confirmation-flow)
  - [Recall Reminder Flow](#recall-reminder-flow)
  - [Complete Outbound State Machine](#complete-outbound-state-machine)
- [State Machine Reference](#state-machine-reference)
  - [Inbound Steps](#inbound-steps)
  - [Outbound Steps](#outbound-steps)
- [SWAIG Tools Reference](#swaig-tools-reference)
  - [Inbound Tools (19)](#inbound-tools)
  - [Outbound Tools (8)](#outbound-tools)
- [OpenDental API Functions](#opendental-api-functions)
- [Configuration](#configuration)
- [Dashboard API](#dashboard-api)
- [Testing](#testing)

## Architecture

```
                     ┌─────────────────────────────────────────────────────┐
                     │                   agent.py                          │
Inbound              │                                                     │
Caller  ──▶  SignalWire  ──▶  DentalAgent (/swml)                          │
                     │              │                                      │
                     │              ├──▶ opendental_client.py ──▶ OpenDental API
                     │              │         │                            │
                     │              │         └── (or mock_opendental.py)  │
                     │              │                                      │
                     │              └──▶ state_store.py (SQLite)           │
                     │                                                     │
                     │  OutboundConfirmAgent (/outbound)                   │
                     │              │                                      │
                     │  confirmation_runner.py                             │
                     │     │  APScheduler / manual trigger                 │
                     │     │  Queries appointments + recalls               │
                     │     └──▶ SignalWire Calls API ──▶ outbound calls    │
                     │                                                     │
                     │  Dashboard API                                      │
                     │     GET  /api/confirmations                         │
                     │     POST /api/confirmations/run                     │
                     │     GET  /api/recalls                               │
                     │     GET  /api/calls                                 │
                     └─────────────────────────────────────────────────────┘
```

| File | Purpose |
|------|---------|
| `agent.py` | Main entry point. Defines `DentalAgent` (19 SWAIG tools, state machine, per-call config), registers `OutboundConfirmAgent`, dashboard endpoints, and the HTTP server. |
| `outbound_agent.py` | `OutboundConfirmAgent` — stripped-down agent for outbound confirmation and recall calls. 8 SWAIG tools, simpler state machine. |
| `confirmation_runner.py` | Scheduler that queries upcoming appointments and recalls, builds a call queue, and initiates outbound calls via the SignalWire Calls API. |
| `opendental_client.py` | All OpenDental API interactions. 30 API functions + 2 voice formatters. In mock mode, API functions are transparently replaced by SQLite equivalents. |
| `config.py` | Environment variable loader with validation. |
| `state_store.py` | SQLite store for transient per-call state (slot selections, booking progress) and call logs. |
| `mock_opendental_db.py` | SQLite schema and seed data for mock mode. 13 tables, auto-seeds providers, patients, appointments, insurance, recalls. |
| `mock_opendental.py` | 30 mock functions matching `opendental_client.py` signatures. Includes slot generation algorithm respecting working hours, lunch breaks, and existing bookings. |

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill in .env values
python agent.py
```

### Mock Mode

Set `MOCK_MODE=true` in `.env` to run entirely against a local SQLite database with no external dependencies. The mock pre-seeds:

- **Brian West** (PatNum 100) — phone `9184249378`, DOB `1977-02-18`, 2 upcoming appointments, recall due soon, Delta Dental PPO insurance on file
- **5 providers** — 3 dentists (Dr. Mitchell, Dr. Rodriguez, Dr. Chen) + 2 hygienists (Lisa Thompson, Rachel Davis)
- **7 operatories** — general, ortho, and hygiene rooms
- **6 appointment types** — New Patient Exam, Periodic Exam, Cleaning, Filling, Crown Prep, Extraction
- **18-25 filler appointments** — random bookings for 10 fake patients to make availability realistic
- **6 unconfirmed appointments** — for outbound confirmation queue testing
- **5 recall entries** — patients due for recall in the next 2-14 days
- **Insurance data** — Delta Dental PPO carrier, plan, subscription, and benefits for Brian West

The mock DB auto-refreshes daily so dates never go stale. Delete `mock_dental.db` to force a clean re-seed.

---

## Inbound Agent

The `DentalAgent` handles all inbound patient calls at the `/swml` endpoint.

### Caller Recognition and Identity Verification

Every inbound call hits `_per_call_config()` before the conversation starts. Returning callers are identified by phone number and must verify their identity via date of birth before proceeding.

```
                         ┌──────────────────┐
                         │   Inbound Call   │
                         └────────┬─────────┘
                                  │
                                  ▼
                    ┌─────────────────────────────┐
                    │ Extract caller phone number │
                    │ from SIP "from" header      │
                    └──────────────┬──────────────┘
                                   │
                                   ▼
                    ┌─────────────────────────────┐
                    │ lookup_patient_by_phone()   │
                    └──────────────┬──────────────┘
                                   │
                          ┌────────┴────────┐
                          │  Patient found? │
                          └────────┬────────┘
                           yes /       \ no
                              /         \
                             ▼           ▼
              ┌──────────────────┐  ┌───────────────────┐
              │ Returning Patient│  │   New Caller      │
              │                  │  │                   │
              │ - Load profile   │  │ - Set is_new=true │
              │ - Check recalls  │  │ - Route to        │
              │ - Greet by name  │  │   collect_patient │
              │ - Skip onboarding│  │                   │
              └────────┬─────────┘  └─────────┬─────────┘
                       │                      │
                       ▼                      ▼
              ┌────────────────┐     ┌────────────────┐
              │verify_identity │     │ collect_patient│
              │                │     └────────────────┘
              │"Can you confirm│
              │ your date of   │
              │ birth?"        │
              │                │
              │verify_identity_│
              │tool            │
              └────────┬───────┘
                       │
               match /     \ mismatch
                    /       \
                   ▼         ▼
          ┌────────────────┐  ┌──────────────────┐
          │ identify_intent│  │ verify_identity  │
          └────────────────┘  │ (retry)          │
                              └──────────────────┘
```

### Flow 1: New Patient Onboarding

New callers go through `gather_info` to collect their details before anything else.

```
┌─────────────┐     ┌──────────────────────────────────┐     ┌──────────────┐
│  greeting   │────▶│  collect_patient (gather_info)   │────▶│ save_patient │
│             │     │                                  │     │              │
│ "Thanks for │     │ Questions:                       │     │ Calls        │
│  calling!"  │     │  1. First name                   │     │ create_      │
└─────────────┘     │  2. Last name                    │     │ patient_tool │
                    │  3. Date of birth (confirm)      │     │              │
                    │  4. Phone number (confirm)       │     └──────┬───────┘
                    │  5. Email (optional)             │            │
                    └──────────────────────────────────┘   success / \ failure
                                                               /     \
                                                              ▼       ▼
                                                ┌─────────────────┐  ┌──────────────────┐
                                                │ identify_intent │  │ collect_patient  │
                                                │                 │  │ (retry)          │
                                                │ "How can I help │  └──────────────────┘
                                                │  you today?"    │
                                                └─────────────────┘
```

### Flow 2: Book Appointment

The main booking flow — collect preferences, search, present options, confirm, book.

```
┌──────────────────┐     ┌──────────────────────────────────┐     ┌──────────────┐
│ identify_intent  │────▶│ collect_appt_prefs (gather_info) │────▶│ search_slots │
│                  │     │                                  │     │              │
│ route_intent     │     │ Questions:                       │     │ search_      │
│ (intent="book")  │     │  1. Reason for visit             │     │ available_   │
└──────────────────┘     │  2. Preferred date (confirm)     │     │ slots        │
                         │  3. Morning / afternoon          │     └──────┬───────┘
                         │  4. Provider preference          │            │
                         └──────────────────────────────────┘    found / \ none
                                                                     /     \
                              ┌─────────────────────────────────────┘       ▼
                              │                                    ┌─────────────────┐
                              ▼                                    │ error_recovery  │
                    ┌──────────────────┐                           └───────┬─────────┘
                    │ present_options  │                                   │
                    │                  │                         ┌──────────▼──────────┐
                    │ "Option 1: Tue   │                         │ collect_appt_prefs  │
                    │  Feb 25 at 9 AM  │                         │ (restart search)    │
                    │  with Dr. M..."  │                         └─────────────────────┘
                    └────────┬─────────┘
                             │
                    ┌────────┴────────┐
             picked │  select_slot /  │ none
                    │  search_again   │ work
                    └────────┬────────┘
                  selected /     \ search_again
                          /       \
                         ▼         ▼
           ┌──────────────────┐  ┌──────────────────────────────────┐
           │ confirm_booking  │  │ collect_appt_prefs (new dates)   │
           │                  │  └──────────────────────────────────┘
           │ "Tuesday Feb 25  │
           │  at 9 AM with    │
           │  Dr. Mitchell.   │
           │  Book it?"       │
           └────────┬─────────┘
                    │
             yes /     \ no
                /       \
               ▼         ▼
 ┌───────────────────┐  ┌──────────────────┐
 │create_appointment │  │ present_options  │
 │                   │  │ (back to options)│
 │ book_appointment  │  └──────────────────┘
 │ "You're all set!" │
 └────────┬──────────┘
          │
          ▼
 ┌──────────────────┐
 │ wrap_up          │
 └──────────────────┘
```

### Flow 3: Confirm Appointment

```
┌──────────────────┐     ┌─────────────────────┐
│ identify_intent  │────▶│ lookup_appointments │
│                  │     │                     │
│ route_intent     │     │ get_patient_        │
│ (intent=         │     │ appointments        │
│  "confirm")      │     └─────────┬───────────┘
└──────────────────┘               │
                           ┌───────┴────────┐
                           │  How many?     │
                           └───────┬────────┘
                            1 /         \ 2+
                             /           \
                            ▼             ▼
          ┌────────────────────┐  ┌──────────────────────┐
          │ (auto-select)      │  │ select_appointment   │
          │                    │  │                      │
          │ Only 1 appointment │  │ "Which appointment   │
          │ — select it        │  │  did you mean?"      │
          │ automatically      │  │                      │
          └─────────┬──────────┘  │ select_appointment_  │
                    │             │ tool                 │
                    │             └──────────┬───────────┘
                    │                        │
                    └───────────┬────────────┘
                                │
                                ▼
                  ┌──────────────────────┐
                  │ confirm_appointment  │
                  │                      │
                  │ confirm_appointment_ │
                  │ tool                 │
                  │                      │
                  │ "Your appointment    │
                  │  is confirmed!"      │
                  └──────────┬───────────┘
                             │
                             ▼
                  ┌──────────────────┐
                  │ wrap_up          │
                  └──────────────────┘
```

### Flow 4: Reschedule Appointment

```
┌──────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│ identify_intent  │────▶│ lookup_appointments │────▶│ select_appointment  │
│                  │     │                     │     │ (if multiple)       │
│ route_intent     │     │ get_patient_        │     │                     │
│ (intent=         │     │ appointments        │     │ or auto-select      │
│  "reschedule")   │     └─────────────────────┘     │ if only 1           │
└──────────────────┘                                 └──────────┬──────────┘
                                                                │
                                                                ▼
                                              ┌─────────────────────────────────┐
                                              │ collect_new_prefs (gather_info) │
                                              │                                 │
                                              │ Questions:                      │
                                              │  1. New preferred date (confirm)│
                                              │  2. Morning / afternoon         │
                                              └───────────────┬─────────────────┘
                                                              │
                                                              ▼
                                              ┌──────────────────────────┐
                                              │ search_slots_resched     │
                                              │                          │
                                              │ search_available_slots   │
                                              └─────────────┬────────────┘
                                                    found /      \ none
                                                         /        \
                                                        ▼          ▼
                                      ┌────────────────────────┐  ┌─────────────────┐
                                      │ present_resched_options│  │ error_recovery  │
                                      │                        │  └─────────────────┘
                                      │ reschedule_            │
                                      │ appointment_tool       │
                                      └───────────┬────────────┘
                                                  │
                                                  ▼
                                      ┌──────────────────┐
                                      │ wrap_up          │
                                      └──────────────────┘
```

### Flow 5: Cancel Appointment

After cancelling, the agent checks for remaining appointments and offers to cancel more.

```
┌──────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│ identify_intent  │────▶│ lookup_appointments │────▶│ select_appointment  │
│                  │     │                     │     │ (if multiple)       │
│ route_intent     │     │ get_patient_        │     │                     │
│ (intent=         │     │ appointments        │     │ or auto-select      │
│  "cancel")       │     └─────────────────────┘     │ if only 1           │
└──────────────────┘                                 └──────────┬──────────┘
                                                                │
                                                                ▼
                                                  ┌──────────────────────────┐
                                                  │ confirm_cancel           │
                                                  │                          │
                                                  │ "Are you sure you want   │
                                                  │  to cancel?"             │
                                                  └─────────────┬────────────┘
                                                                │
                                                   yes /             \ no
                                                      /               \
                                                     ▼                 ▼
                                      ┌───────────────────────┐  ┌───────────────────┐
                                      │ cancel_appointment_   │  │ wrap_up           │
                                      │ tool                  │  │                   │
                                      │                       │  │ keep_appointment  │
                                      │ → check for remaining │  │ "No problem."     │
                                      │   appointments        │  └───────────────────┘
                                      └───────────┬───────────┘
                                                  │
                                        more /         \ none
                                            /           \
                                           ▼             ▼
                            ┌──────────────────────┐  ┌───────────────────┐
                            │ "Want to cancel      │  │ wrap_up           │
                            │  another?"           │  └───────────────────┘
                            └──────────────────────┘
```

### Flow 6: Insurance

Callers can check, add, or update their dental insurance information. The `save_insurance_tool` executes a 5-step OpenDental API chain: find/create carrier, find/create plan, create subscription, create patient plan, verify.

```
┌──────────────────┐     ┌─────────────────────┐
│ identify_intent  │────▶│ lookup_insurance    │
│                  │     │                     │
│ route_intent     │     │ lookup_insurance_   │
│ (intent=         │     │ tool                │
│  "insurance")    │     └─────────┬───────────┘
└──────────────────┘               │
                           found / \ not found
                                /     \
                               ▼       ▼
                 ┌──────────────┐  ┌──────────────────────────────────────┐
                 │read_insurance│  │ collect_insurance (gather_info)      │
                 │              │  │                                      │
                 │"You have     │  │ Questions:                           │
                 │ Delta Dental │  │  1. Carrier name                     │
                 │ PPO, member  │  │  2. Policyholder                     │
                 │ ID DEN123456"│  │  3. Relationship (Self/Spouse/etc.)  │
                 └──────┬───────┘  │  4. Member ID (confirm)              │
                        │          │  5. Group number (optional)          │
                   update│ no      │  6. Subscriber DOB                   │
                  yes /   \        │  7. Employer (optional)              │
                     /     \       └──────────────┬───────────────────────┘
                    ▼       ▼                     │
  ┌───────────────────┐  ┌────────┐               ▼
  │collect_insurance  │  │wrap_up │     ┌─────────────────────┐
  │(update existing)  │  └────────┘     │ verify_insurance    │
  └───────────────────┘                 │                     │
                                        │ save_insurance_tool │
                                        │ (5-step API chain)  │
                                        └─────────┬───────────┘
                                                  │
                                                  ▼
                                        ┌──────────────────┐
                                        │ save_insurance   │
                                        │                  │
                                        │ "Your Delta      │
                                        │  Dental is now   │
                                        │  on file!"       │
                                        └────────┬─────────┘
                                                 │
                                                 ▼
                                        ┌──────────────────┐
                                        │ wrap_up          │
                                        └──────────────────┘
```

**Insurance API Chain** (executed by `save_insurance_tool`):

```
1. GET /carriers?CarrierName=         →  find or POST /carriers            →  CarrierNum
2. GET /insplans?CarrierNum=          →  find or POST /insplans            →  PlanNum
3. POST /inssubs (PlanNum, PatNum, SubscriberID)                           →  InsSubNum
4. POST /patplans (PatNum, InsSubNum, Ordinal, Relationship)               →  PatPlanNum
5. PUT /insverifies (PatPlanNum, DateLastVerified=today)
```

### Error Recovery and Wrap Up

Any step that encounters a failure routes to `error_recovery`. Every flow ends at `wrap_up`.

```
┌────────────────────────┐          ┌────────────────────────┐
│   error_recovery       │          │   wrap_up              │
│                        │          │                        │
│ "No openings found.    │          │ "Is there anything     │
│  Want to try different │          │  else I can help       │
│  dates?"               │          │  you with?"            │
└───────────┬────────────┘          └───────────┬────────────┘
            │                                   │
  ┌─────────┴──────────┐             ┌──────────┴──────────┐
  │                    │             │                     │
search_again        restart       log_call             restart
  │                    │             │                     │
  ▼                    ▼             ▼                     ▼
collect_appt_prefs  identify_    End call            identify_
or collect_new_     intent                           intent
prefs
```

### Complete Inbound State Machine

```
                                    ┌──────────┐
                                    │ greeting │
                                    └────┬─────┘
                              new /      \ returning
                                 /        \
                                ▼          ▼
                  ┌────────────────┐  ┌──────────────────┐
                  │collect_patient │  │ verify_identity  │
                  │(gather_info)   │  │                  │
                  └───────┬────────┘  │ verify_identity_ │
                          │           │ tool (DOB check) │
                          ▼           └────────┬─────────┘
                  ┌──────────────┐             │
                  │ save_patient │             │
                  └───────┬──────┘             │
                          │                    │
                          └──────────┬─────────┘
                                     │
                                     ▼
                  ┌───────────────────────────────────┐
                  │         identify_intent           │◀─────────────────────┐
                  │                                   │                      │
                  │  route_intent                     │                      │
                  └───┬──────────┬──────────┬─────────┘                      │
                      │          │          │                                │
                    book    confirm/     insurance                           │
                      │    reschedule/     │                                 │
                      │     cancel         │                                 │
                      │          │         │                                 │
                      ▼          ▼         ▼                                 │
        ┌──────────────────┐ ┌────────────────┐ ┌────────────────┐           │
        │collect_appt_prefs│ │lookup_         │ │lookup_         │           │
        │(gather_info)     │ │appointments    │ │insurance       │           │
        └────────┬─────────┘ └───────┬────────┘ └───────┬────────┘           │
                 │                   │                  │                    │
                 ▼                   ▼                  │                    │
        ┌──────────────┐  ┌────────────────────┐        │                    │
        │ search_slots │  │ select_appointment │        │                    │
        └───────┬──────┘  └──┬──────┬──────────┘        │                    │
                │            │      │     │             │                    │
                ▼        confirm resched cancel         │                    │
        ┌──────────────┐     │      │     │             │                    │
        │present_      │     ▼      │     ▼             │                    │
        │options       │ ┌────────┐ │ ┌──────────────┐  │                    │
        └───────┬──────┘ │confirm_│ │ │confirm_cancel│  │                    │
                │        │appoint-│ │ └──────────────┘  │                    │
                ▼        │ment   │ │                    │                    │
        ┌──────────────┐ └───┬───┘ │                    │                    │
        │confirm_      │     │     ▼                    │                    │
        │booking       │     │ ┌──────────────┐         │                    │
        └───────┬──────┘     │ │collect_new_  │         │                    │
                │            │ │prefs (gather)│         │                    │
                ▼            │ └──────┬───────┘         │                    │
        ┌──────────────┐     │        │                 │                    │
        │create_       │     │        ▼                 │                    │
        │appointment   │     │ ┌────────────────┐       │                    │
        └───────┬──────┘     │ │search_slots_   │       │                    │
                │            │ │resched         │       │                    │
                │            │ └──────┬─────────┘       ├── read_insurance   │
                │            │        │                 │   │                │
                │            │        ▼                 │   ▼                │
                │            │ ┌────────────────────┐   │ collect_insurance  │
                │            │ │present_resched_    │   │ (gather_info)      │
                │            │ │options             │   │   │                │
                │            │ └──────┬─────────────┘   │   ▼                │
                │            │        │                 │ verify_insurance   │
                │            │        │                 │   │                │
                │            │        │                 │   ▼                │
                │            │        │                 │ save_insurance     │
                │            │        │                 │   │                │
                ▼            ▼        ▼                 ▼   ▼                │
              ┌─────────────────────────────────────────────────┐            │
              │                    wrap_up                      │── restart ─┘
              │                                                 │
              │  log_call → end call                            │
              └─────────────────────────────────────────────────┘

              ┌────────────────┐
              │ error_recovery │ (reachable from search steps)
              │                │
              │ search_again / │──▶ collect_appt_prefs / collect_new_prefs /
              │ restart        │    identify_intent
              └────────────────┘
```

---

## Outbound Agent

The `OutboundConfirmAgent` handles proactive outbound calls to patients at the `/outbound` endpoint. It confirms upcoming appointments and reminds patients about overdue recalls.

### Confirmation Runner

The `confirmation_runner.py` manages the outbound call queue:

```
┌─────────────────────────────────────────────────────────────────────┐
│  confirmation_runner.py                                             │
│                                                                     │
│  ┌────────────────────┐                                             │
│  │ APScheduler        │  Cron: "0 9 * * 1-5" (9 AM weekdays)        │
│  │ (or manual trigger │  POST /api/confirmations/run                │
│  │  via dashboard)    │                                             │
│  └─────────┬──────────┘                                             │
│            │                                                        │
│            ▼                                                        │
│  ┌───────────────────────────────────────────┐                      │
│  │ 1. Build confirmation queue               │                      │
│  │    GET /appointments (next N days)        │                      │
│  │    Filter: Confirmed != "Confirmed"       │                      │
│  └─────────┬─────────────────────────────────┘                      │
│            │                                                        │
│            ▼                                                        │
│  ┌───────────────────────────────────────────┐                      │
│  │ 2. Build recall queue                     │                      │
│  │    GET /recalls/List (next N days)        │                      │
│  └─────────┬─────────────────────────────────┘                      │
│            │                                                        │
│            ▼                                                        │
│  ┌───────────────────────────────────────────┐                      │
│  │ 3. For each entry (max concurrent: 2)     │                      │
│  │    POST SignalWire Calls API              │                      │
│  │    {"command":"dial", "params":{          │                      │
│  │      "to": patient_phone,                 │                      │
│  │      "url": "https://u:p@host/outbound    │                      │
│  │             ?call_type=confirmation       │                      │
│  │             &pat_num=100&apt_num=1001"    │                      │
│  │    }}                                     │                      │
│  └───────────────────────────────────────────┘                      │
└─────────────────────────────────────────────────────────────────────┘
```

The SWML URL includes basic auth credentials so SignalWire can authenticate when fetching the agent configuration. Query parameters (`call_type`, `pat_num`, `apt_num`, `recall_type`) inject context into the outbound agent's `_per_call_config()`.

In mock mode, calls are logged instead of actually initiated.

### Appointment Confirmation Flow

```
┌────────────────────────┐
│ greeting               │
│                        │
│ "Hi {name}, this is    │
│  {practice} calling    │
│  about your upcoming   │
│  appointment."         │
└───────────┬────────────┘
            │
            ▼
┌────────────────────────────────────────────┐
│ confirm_or_act                             │
│                                            │
│ "You have a {procedure} on {date} at       │
│  {time} with {provider}. Can you confirm?" │
└───────────┬────────────────────────────────┘
            │
            ├─── "Yes" ──▶ confirm_outbound ──────────┐
            │                                         │
            ├─── "Reschedule" ──────────────────┐     │
            │                                   │     │
            └─── "Cancel" ──────┐               │     │
                                │               │     │
                                ▼               │     │
                  ┌──────────────────┐          │     │
                  │ handle_cancel    │          │     │
                  │                  │          │     │
                  │ cancel_outbound  │          │     │
                  │ or confirm       │          │     │
                  │ instead          │          │     │
                  └────────┬─────────┘          │     │
                           │                    │     │
                           │                    ▼     │
                           │  ┌──────────────────────────────────┐
                           │  │ handle_reschedule (gather_info)  │
                           │  │                                  │
                           │  │ 1. "What date works better?"     │
                           │  │ 2. "Morning or afternoon?"       │
                           │  └───────────────┬──────────────────┘
                           │                  │
                           │                  ▼
                           │  ┌──────────────────────────────────┐
                           │  │ search_resched_slots             │
                           │  │                                  │
                           │  │ search_available_slots           │
                           │  └───────────────┬──────────────────┘
                           │                  │
                           │                  ▼
                           │  ┌──────────────────────────────────┐
                           │  │ present_resched_options          │
                           │  │                                  │
                           │  │ reschedule_outbound              │
                           │  └───────────────┬──────────────────┘
                           │                  │
                           └──────────────────┘
                                       │
                                       ▼
                          ┌───────────────────────┐
                          │ log_and_end           │
                          │                       │
                          │ log_outbound_call     │
                          │ "Thanks, have a       │
                          │  great day!"          │
                          └───────────────────────┘
```

### Recall Reminder Flow

For patients due for recall (cleaning, checkup) who haven't scheduled yet.

```
┌────────────────────────┐
│ greeting               │
│                        │
│ "Hi {name}, this is    │
│  {practice}. You're    │
│  due for your          │
│  {recall_type}."       │
└───────────┬────────────┘
            │
            ▼
┌──────────────────────────────────────────────┐
│ offer_scheduling                             │
│                                              │
│ "Would you like to schedule that now?"       │
└───────────┬──────────────────────────────────┘
            │
            ├──── "Yes" ────────────────────────────────────┐
            │                                               │
            └──── "No" ──▶ decline_recall ───┐              │
                                             │              │
                           "No problem,      │              │
                            we'll remind     │              │
                            you again."      │              │
                                             │              │
                                             │              ▼
                                             │  ┌─────────────────────────────┐
                                             │  │ collect_recall_prefs        │
                                             │  │ (gather_info)               │
                                             │  │                             │
                                             │  │ 1. Preferred date           │
                                             │  │ 2. Morning / afternoon      │
                                             │  └────────────┬────────────────┘
                                             │               │
                                             │               ▼
                                             │  ┌─────────────────────────────┐
                                             │  │ search_recall_slots         │
                                             │  │                             │
                                             │  │ search_available_slots      │
                                             │  └────────────┬────────────────┘
                                             │               │
                                             │               ▼
                                             │  ┌─────────────────────────────┐
                                             │  │ present_recall_options      │
                                             │  │                             │
                                             │  │ book_recall                 │
                                             │  └────────────┬────────────────┘
                                             │               │
                                             └───────────────┘
                                                      │
                                                      ▼
                                         ┌───────────────────────┐
                                         │ log_and_end           │
                                         │                       │
                                         │ log_outbound_call     │
                                         └───────────────────────┘
```

### Complete Outbound State Machine

```
                                    ┌──────────┐
                                    │ greeting │
                                    └────┬─────┘
                         confirmation /    \ recall
                                     /      \
                                    ▼        ▼
                     ┌────────────────┐  ┌──────────────────┐
                     │confirm_or_act  │  │ offer_scheduling │
                     └───┬────────────┘  └───┬──────────────┘
                         │                   │
           ┌─────────────┼───────────┐       ├── yes ──▶ collect_recall_prefs ─┐
           │             │           │       │          (gather)               │
        confirm     reschedule   cancel      │             │                   │
           │             │           │       │             ▼                   │
           ▼             │           ▼       │     search_recall_slots         │
  ┌─────────────┐        │   ┌──────────┐    │             │                   │
  │confirm_     │        │   │handle_   │    │             ▼                   │
  │outbound     │        │   │cancel    │    │     present_recall_options      │
  └──────┬──────┘        │   └────┬─────┘    │        book_recall              │
         │               │        │          │             │                   │
         │               ▼        │          └── no ──▶ decline_recall         │
         │   ┌──────────────────┐ │                        │                   │
         │   │handle_reschedule │ │                        │                   │
         │   │(gather)          │ │                        │                   │
         │   └────────┬─────────┘ │                        │                   │
         │            │           │                        │                   │
         │     search_resched_    │                        │                   │
         │     slots              │                        │                   │
         │            │           │                        │                   │
         │     present_resched_   │                        │                   │
         │     options            │                        │                   │
         │            │           │                        │                   │
         └────────────┴───────────┴────────────────────────┴───────────────────┘
                                       │
                                       ▼
                          ┌───────────────────────┐
                          │     log_and_end        │
                          │                        │
                          │ log_outbound_call      │
                          └────────────────────────┘

                          ┌───────────────────┐
                          │ unable_to_reach   │ (reachable from any step
                          │                   │  if voicemail/no answer)
                          │ → log_and_end     │
                          └───────────────────┘
```

---

## State Machine Reference

### Inbound Steps

| Step | Mode | Functions Available | Valid Next Steps |
|------|------|--------------------|-----------------|
| `greeting` | -- | none | `collect_patient`, `verify_identity` |
| `collect_patient` | gather_info | none | `save_patient` |
| `save_patient` | tool | `create_patient_tool` | `identify_intent` |
| `verify_identity` | tool | `verify_identity_tool` | `identify_intent` |
| `identify_intent` | tool | `route_intent` | `collect_appt_prefs`, `lookup_appointments`, `lookup_insurance` |
| `collect_appt_prefs` | gather_info | none | `search_slots` |
| `search_slots` | tool | `search_available_slots` | `present_options`, `error_recovery` |
| `present_options` | tool | `select_slot`, `search_again` | `confirm_booking`, `collect_appt_prefs` |
| `confirm_booking` | tool | `book_appointment`, `decline_booking` | `create_appointment`, `present_options` |
| `create_appointment` | -- | none | `wrap_up`, `identify_intent` |
| `lookup_appointments` | tool | `get_patient_appointments` | `select_appointment`, `wrap_up` |
| `select_appointment` | tool | `select_appointment_tool` | `confirm_appointment`, `collect_new_prefs`, `confirm_cancel` |
| `confirm_appointment` | tool | `confirm_appointment_tool` | `wrap_up` |
| `collect_new_prefs` | gather_info | none | `search_slots_resched` |
| `search_slots_resched` | tool | `search_available_slots` | `present_resched_options`, `error_recovery` |
| `present_resched_options` | tool | `reschedule_appointment_tool`, `search_again` | `wrap_up`, `collect_new_prefs` |
| `confirm_cancel` | tool | `cancel_appointment_tool`, `keep_appointment`, `get_patient_appointments` | `wrap_up`, `lookup_appointments`, `select_appointment` |
| `lookup_insurance` | tool | `lookup_insurance_tool` | `read_insurance`, `collect_insurance` |
| `read_insurance` | -- | none | `collect_insurance`, `wrap_up` |
| `collect_insurance` | gather_info | none | `verify_insurance` |
| `verify_insurance` | tool | `save_insurance_tool` | `save_insurance`, `error_recovery` |
| `save_insurance` | tool | `update_insurance_tool` | `wrap_up` |
| `error_recovery` | tool | `search_again`, `restart` | `collect_appt_prefs`, `collect_new_prefs`, `identify_intent` |
| `wrap_up` | tool | `log_call`, `restart` | `identify_intent` |

### Outbound Steps

| Step | Mode | Functions Available | Valid Next Steps |
|------|------|--------------------|-----------------|
| `greeting` | -- | none | `confirm_or_act`, `offer_scheduling` |
| `confirm_or_act` | tool | `confirm_outbound` | `handle_reschedule`, `handle_cancel`, `log_and_end` |
| `handle_cancel` | tool | `cancel_outbound`, `confirm_outbound` | `log_and_end` |
| `handle_reschedule` | gather_info | none | `search_resched_slots` |
| `search_resched_slots` | tool | `search_available_slots` | `present_resched_options`, `log_and_end` |
| `present_resched_options` | tool | `reschedule_outbound` | `log_and_end`, `handle_reschedule` |
| `offer_scheduling` | tool | `decline_recall` | `collect_recall_prefs`, `log_and_end` |
| `collect_recall_prefs` | gather_info | none | `search_recall_slots` |
| `search_recall_slots` | tool | `search_available_slots` | `present_recall_options`, `log_and_end` |
| `present_recall_options` | tool | `book_recall` | `log_and_end`, `collect_recall_prefs` |
| `unable_to_reach` | tool | `unable_to_reach_tool` | `log_and_end` |
| `log_and_end` | tool | `log_outbound_call` | -- |

---

## SWAIG Tools Reference

### Inbound Tools

| # | Tool | Parameters | What It Does |
|---|------|-----------|--------------|
| 1 | `route_intent` | `intent` (book/confirm/reschedule/cancel/insurance) | Routes to the correct flow |
| 2 | `create_patient_tool` | -- (reads gather data) | Creates patient in OpenDental |
| 3 | `search_available_slots` | -- (reads gather data) | Searches for openings, returns up to 5 |
| 4 | `select_slot` | `option_number` (1-5) | Caller picks a slot |
| 5 | `book_appointment` | -- (reads state) | Books the confirmed slot |
| 6 | `get_patient_appointments` | -- (reads profile) | Fetches upcoming appointments |
| 7 | `select_appointment_tool` | `appointment_number` | Picks which appointment to act on |
| 8 | `confirm_appointment_tool` | -- | Marks appointment as Confirmed |
| 9 | `reschedule_appointment_tool` | `option_number` | Moves appointment to new slot |
| 10 | `cancel_appointment_tool` | -- | Cancels (breaks) the appointment |
| 11 | `keep_appointment` | -- | Caller declines to cancel |
| 12 | `decline_booking` | -- | Go back to slot options |
| 13 | `search_again` | -- | Restart preference collection |
| 14 | `restart` | -- | Return to intent identification |
| 15 | `log_call` | `summary` | Logs call to OpenDental + local DB |
| 16 | `verify_identity_tool` | `date_of_birth` (YYYY-MM-DD) | Verifies caller identity via DOB check |
| 17 | `lookup_insurance_tool` | -- | Checks if patient has insurance on file |
| 18 | `save_insurance_tool` | -- (reads gather data) | Executes 5-step insurance save chain |
| 19 | `update_insurance_tool` | -- | Routes to collect_insurance to update existing info |

### Outbound Tools

| # | Tool | Parameters | What It Does |
|---|------|-----------|--------------|
| 1 | `confirm_outbound` | -- | Confirms appointment, appends note |
| 2 | `cancel_outbound` | -- | Cancels appointment after confirmation |
| 3 | `search_available_slots` | -- (reads gather data) | Searches for openings (reschedule or recall) |
| 4 | `reschedule_outbound` | `option_number` (1-5) | Reschedules to new slot |
| 5 | `book_recall` | `option_number` (1-5) | Books recall appointment |
| 6 | `decline_recall` | -- | Logs patient declining recall |
| 7 | `unable_to_reach_tool` | `reason` (voicemail/no_answer/wrong_number) | Logs failed contact attempt |
| 8 | `log_outbound_call` | `outcome`, `notes` | Logs call result to OpenDental + local DB |

---

## OpenDental API Functions

All functions in `opendental_client.py`. In mock mode, API functions are replaced by SQLite equivalents; formatters are never overridden.

### Patient

| Function | Endpoint | Method |
|----------|----------|--------|
| `lookup_patient_by_phone(phone)` | `/patients?Phone=` | GET |
| `get_patient(pat_num)` | `/patients/{PatNum}` | GET |
| `create_patient(...)` | `/patients` | POST |

### Appointments

| Function | Endpoint | Method |
|----------|----------|--------|
| `get_patient_appointments(pat_num, status)` | `/appointments?PatNum=&AptStatus=` | GET |
| `get_appointment(apt_num)` | `/appointments/{AptNum}` | GET |
| `get_available_slots(...)` | `/appointments/Slots` | GET |
| `book_appointment(...)` | `/appointments` | POST |
| `confirm_appointment(apt_num, confirm_val)` | `/appointments/{AptNum}/Confirm` | PUT |
| `reschedule_appointment(apt_num, ...)` | `/appointments/{AptNum}` | PUT |
| `cancel_appointment(apt_num, ...)` | `/appointments/{AptNum}/Break` | PUT |
| `get_appointments_date_range(start, end, status)` | `/appointments?dateStart=&dateEnd=` | GET |
| `append_appointment_note(apt_num, note)` | `/appointments/{AptNum}/Note` | PUT |

### Providers and Operatories

| Function | Endpoint | Method |
|----------|----------|--------|
| `get_providers(clinic_num)` | `/providers` | GET |
| `get_provider(prov_num)` | `/providers/{ProvNum}` | GET |
| `get_operatories(clinic_num)` | `/operatories` | GET |
| `get_appointment_types()` | `/appointmenttypes` | GET |

### Recalls

| Function | Endpoint | Method |
|----------|----------|--------|
| `get_recalls(pat_num)` | `/recalls?PatNum=` | GET |
| `get_recall_list(date_start, date_end)` | `/recalls/List` | GET |
| `update_recall_status(pat_num, ...)` | `/recalls/Status` | PUT |

### Insurance

| Function | Endpoint | Method |
|----------|----------|--------|
| `get_patient_insurance(pat_num)` | `/familymodules/{PatNum}/Insurance` | GET |
| `search_carriers(name)` | `/carriers?CarrierName=` | GET |
| `create_carrier(name, ...)` | `/carriers` | POST |
| `get_insurance_plan(plan_num)` | `/insplans/{PlanNum}` | GET |
| `search_insurance_plans(carrier_num)` | `/insplans?CarrierNum=` | GET |
| `create_insurance_plan(...)` | `/insplans` | POST |
| `create_insurance_sub(...)` | `/inssubs` | POST |
| `create_patient_plan(...)` | `/patplans` | POST |
| `get_benefits(plan_num)` | `/benefits?PlanNum=` | GET |
| `verify_insurance(pat_plan_num)` | `/insverifies` | PUT |

### Communication

| Function | Endpoint | Method |
|----------|----------|--------|
| `create_commlog(pat_num, note, mode)` | `/commlogs` | POST |

### Formatters (no API calls, not overridden in mock mode)

- `format_datetime_voice(dt_string)` -- `"2026-02-26 09:00:00"` -> `"Thursday February 26 at 9 AM"`
- `format_slot_voice(slot, providers_cache)` -- Slot dict -> `"Thursday February 26 at 9 AM with Dr. Mitchell"`

---

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MOCK_MODE` | No | `false` | Use local SQLite instead of real OpenDental API |
| `OPENDENTAL_BASE_URL` | No | `https://api.opendental.com/api/v1` | OpenDental API base URL |
| `OPENDENTAL_DEVELOPER_KEY` | Yes* | -- | OpenDental developer API key |
| `OPENDENTAL_CUSTOMER_KEY` | Yes* | -- | OpenDental customer API key |
| `SIGNALWIRE_PROJECT_ID` | Yes | -- | SignalWire project ID |
| `SIGNALWIRE_TOKEN` | Yes | -- | SignalWire API token |
| `SIGNALWIRE_SPACE` | Yes | -- | SignalWire space (e.g., `yourspace.signalwire.com`) |
| `SIGNALWIRE_PHONE_NUMBER` | Yes | -- | Inbound phone number |
| `DISPLAY_PHONE_NUMBER` | No | -- | Display-formatted phone number |
| `SWML_BASIC_AUTH_USER` | No | -- | Basic auth user for SWML webhook |
| `SWML_BASIC_AUTH_PASSWORD` | No | -- | Basic auth password for SWML webhook |
| `SWML_PROXY_URL_BASE` | No | -- | Proxy/tunnel URL (e.g., ngrok) |
| `PRACTICE_NAME` | No | `our dental office` | Practice name used in greetings |
| `AI_MODEL` | No | `gpt-oss-120b` | AI model for conversation |
| `AI_TOP_P` | No | `0.5` | Top-p sampling parameter |
| `AI_TEMPERATURE` | No | `0.5` | Temperature parameter |
| `HOST` | No | `0.0.0.0` | Server bind address |
| `PORT` | No | `3000` | Server port |
| `OUTBOUND_ENABLED` | No | `false` | Enable the outbound confirmation scheduler |
| `OUTBOUND_SCHEDULE` | No | `0 9 * * 1-5` | Cron expression for confirmations (default: 9 AM weekdays) |
| `CONFIRM_WINDOW_DAYS` | No | `3` | Days ahead to look for unconfirmed appointments |
| `RECALL_WINDOW_DAYS` | No | `14` | Days ahead to look for due recalls |
| `MAX_OUTBOUND_CONCURRENT` | No | `2` | Max simultaneous outbound calls |
| `OUTBOUND_CALLER_ID` | No | -- | Caller ID for outbound (defaults to `SIGNALWIRE_PHONE_NUMBER`) |

*Not required when `MOCK_MODE=true`

---

## Dashboard API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/phone` | GET | Get the inbound phone number |
| `/api/calls` | GET | List all call logs |
| `/api/confirmations` | GET | Get confirmation queue status, last run, results |
| `/api/confirmations/run` | POST | Manually trigger a confirmation run |
| `/api/recalls` | GET | List patients due for recall |

---

## Testing

Run the SWAIG flow test harness to verify all 27 tools across both agents:

```bash
./test_flow.sh           # run all tests
./test_flow.sh --debug   # verbose output showing swaig-test commands and responses
```

The test harness uses `swaig-test` with persistent call state (`--call-id`) and injected global data (`--custom-data`) to simulate complete conversation flows:

| Section | What It Tests |
|---------|--------------|
| 1 | `route_intent` -- all 5 intents |
| 2 | `verify_identity_tool` -- DOB match, mismatch, no DOB on file |
| 3 | `create_patient_tool` -- success, missing name |
| 4 | Booking flow -- search, select, book, guard checks |
| 5 | Confirm flow -- lookup, select, confirm |
| 6 | Reschedule flow -- lookup, select, search, reschedule |
| 7 | Cancel flow -- lookup, select, cancel, keep |
| 8 | Insurance flow -- lookup (found/not found), save, validation errors, update |
| 9 | `select_appointment_tool` -- multi-appointment selection |
| 10 | Utility tools -- decline_booking, search_again, restart, log_call |
| 11 | Outbound confirm + cancel |
| 12 | Outbound reschedule -- search, reschedule |
| 13 | Outbound recall -- search, book, decline |
| 14 | Outbound utilities -- unable_to_reach (all reasons), log_outbound_call |

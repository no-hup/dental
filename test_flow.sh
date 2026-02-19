
#!/usr/bin/env bash
# =============================================================================
# Dental AI SWAIG Flow Test Harness
#
# Tests all SWAIG functions for both inbound (DentalAgent) and outbound
# (OutboundConfirmAgent) agents using swaig-test with persistent call state.
#
# Usage:  ./test_flow.sh [--debug]
# =============================================================================

SWAIG="swaig-test"
INBOUND="agent.py"
OUTBOUND="outbound_agent.py"
PASS=0
FAIL=0
CALL_ID="test-$(date +%s)"
PREF_DATE=$(date -v+8d +%Y-%m-%d)
BRIAN_DOB="1977-02-18"
DEBUG=false

# Parse flags
for arg in "$@"; do
    case "$arg" in
        --debug|-d) DEBUG=true ;;
    esac
done

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
DIM='\033[2m'
NC='\033[0m'

# ── helpers ──────────────────────────────────────────────────────────────────

check() {
    local label="$1"
    local pattern="$2"
    local byte_len char_len pad
    byte_len=$(printf '%s' "$label" | wc -c)
    char_len=${#label}
    pad=$((57 + byte_len - char_len))
    printf "${CYAN}  %-${pad}s${NC}" "$label"
    if echo "$OUTPUT" | grep -qi "$pattern"; then
        printf "${GREEN}PASS${NC}\n"
        ((PASS++))
    else
        printf "${RED}FAIL${NC} — expected '%s'\n" "$pattern"
        echo "      Got: $(echo "$OUTPUT" | head -2)"
        ((FAIL++))
    fi
}

run() {
    if $DEBUG; then
        printf "\n${DIM}  ▸ swaig-test %s${NC}\n" "$*"
    fi
    OUTPUT=$("$SWAIG" "$@" 2>/dev/null) || true
    if $DEBUG; then
        echo "$OUTPUT" | while IFS= read -r line; do
            printf "${DIM}    %s${NC}\n" "$line"
        done
    fi
}

section() {
    printf "\n${YELLOW}━━ %s ━━${NC}\n" "$1"
}

# ── Global data payloads ─────────────────────────────────────────────────────

BRIAN_PROFILE='{"global_data":{"patient_profile":{"PatNum":100,"first_name":"Brian","last_name":"West","phone":"+19184249378","email":"brian@example.com","dob":"1977-02-18"},"is_new_caller":false,"caller_phone":"+19184249378"}}'

NEW_CALLER='{"global_data":{"patient_profile":null,"is_new_caller":true,"caller_phone":"+15551234567"}}'

PATIENT_ANSWERS='{"global_data":{"patient_profile":null,"is_new_caller":true,"caller_phone":"+15551234567","patient_answers":{"first_name":"Jane","last_name":"Doe","date_of_birth":"1990-05-15","phone_number":"5551234567","email":"jane@example.com"}}}'

APPT_PREFS='{"global_data":{"patient_profile":{"PatNum":100,"first_name":"Brian","last_name":"West","phone":"+19184249378"},"is_new_caller":false,"caller_phone":"+19184249378","appt_prefs_answers":{"reason":"cleaning","preferred_date":"'"$PREF_DATE"'","time_preference":"morning","provider_preference":"no_preference"}}}'

RESCHED_PREFS='{"global_data":{"patient_profile":{"PatNum":100,"first_name":"Brian","last_name":"West","phone":"+19184249378"},"is_new_caller":false,"caller_phone":"+19184249378","resched_prefs_answers":{"new_preferred_date":"'"$PREF_DATE"'","time_preference":"afternoon"}}}'

INSURANCE_ANSWERS='{"global_data":{"patient_profile":{"PatNum":100,"first_name":"Brian","last_name":"West","phone":"+19184249378"},"is_new_caller":false,"caller_phone":"+19184249378","insurance_answers":{"carrier_name":"Cigna","subscriber_name":"self","relationship":"Self","member_id":"CIG999999","group_number":"GRP456","subscriber_dob":"1977-02-18","employer":"Acme Corp"}}}'

OUTBOUND_CONFIRM='{"global_data":{"call_type":"confirmation","patient_profile":{"PatNum":100,"first_name":"Brian","last_name":"West"},"appointment":{"AptNum":1001,"datetime":"'"$PREF_DATE"' 09:00:00","ProvNum":4,"provider":"Lisa Thompson","time_display":"'"$PREF_DATE"' at 9 AM","note":"Cleaning/checkup"}}}'

OUTBOUND_RECALL='{"global_data":{"call_type":"recall","patient_profile":{"PatNum":100,"first_name":"Brian","last_name":"West"},"recall_info":{"recall_type":"Prophy"}}}'

# =============================================================================
printf "\n${YELLOW}╔══════════════════════════════════════════════════════════╗${NC}\n"
printf "${YELLOW}║         Dental AI SWAIG Flow Test Harness                ║${NC}\n"
printf "${YELLOW}╚══════════════════════════════════════════════════════════╝${NC}\n"
printf "  Call ID:   ${CYAN}%s${NC}\n" "$CALL_ID"
printf "  Pref date: ${CYAN}%s${NC}\n" "$PREF_DATE"

# =============================================================================
section "1. route_intent"
# =============================================================================

run "$INBOUND" --raw --call-id "${CALL_ID}-ri-book" --custom-data "$BRIAN_PROFILE" --exec route_intent --intent book
check "route_intent(book) → collect_appt_prefs" "collect_appt_prefs"

run "$INBOUND" --raw --call-id "${CALL_ID}-ri-confirm" --custom-data "$BRIAN_PROFILE" --exec route_intent --intent confirm
check "route_intent(confirm) → lookup_appointments" "lookup_appointments"

run "$INBOUND" --raw --call-id "${CALL_ID}-ri-resched" --custom-data "$BRIAN_PROFILE" --exec route_intent --intent reschedule
check "route_intent(reschedule) → lookup_appointments" "lookup_appointments"

run "$INBOUND" --raw --call-id "${CALL_ID}-ri-cancel" --custom-data "$BRIAN_PROFILE" --exec route_intent --intent cancel
check "route_intent(cancel) → lookup_appointments" "lookup_appointments"

run "$INBOUND" --raw --call-id "${CALL_ID}-ri-ins" --custom-data "$BRIAN_PROFILE" --exec route_intent --intent insurance
check "route_intent(insurance) → lookup_insurance" "lookup_insurance"

# =============================================================================
section "2. verify_identity_tool"
# =============================================================================

run "$INBOUND" --raw --call-id "${CALL_ID}-vid-ok" --custom-data "$BRIAN_PROFILE" --exec verify_identity_tool --date_of_birth "$BRIAN_DOB"
check "DOB match → verified" "verified\|Verified"
check "  → change_step: identify_intent" "identify_intent"

run "$INBOUND" --raw --call-id "${CALL_ID}-vid-bad" --custom-data "$BRIAN_PROFILE" --exec verify_identity_tool --date_of_birth "2000-01-01"
check "DOB mismatch → retry" "doesn't match\|try again"

# No DOB on file → passes anyway
NO_DOB_PROFILE='{"global_data":{"patient_profile":{"PatNum":100,"first_name":"Brian","last_name":"West","dob":""},"is_new_caller":false}}'
run "$INBOUND" --raw --call-id "${CALL_ID}-vid-nodob" --custom-data "$NO_DOB_PROFILE" --exec verify_identity_tool --date_of_birth "1990-01-01"
check "No DOB on file → passes" "verified\|Verified\|identify_intent"

# =============================================================================
section "3. create_patient_tool"
# =============================================================================

run "$INBOUND" --raw --call-id "${CALL_ID}-cp" --custom-data "$PATIENT_ANSWERS" --exec create_patient_tool
check "Create patient → success" "Patient created\|Welcome"
check "  → change_step: identify_intent" "identify_intent"

PATIENT_NO_NAME='{"global_data":{"patient_answers":{"first_name":"","last_name":""},"is_new_caller":true,"caller_phone":"+15551234567"}}'
run "$INBOUND" --raw --call-id "${CALL_ID}-cp-noname" --custom-data "$PATIENT_NO_NAME" --exec create_patient_tool
check "Missing name → error" "Missing name"
check "  → change_step: collect_patient" "collect_patient"

# =============================================================================
section "4. Booking Flow — search + select + book"
# =============================================================================

run "$INBOUND" --raw --call-id "${CALL_ID}-book" --custom-data "$APPT_PREFS" --exec search_available_slots
check "Search slots → found openings" "Found.*opening\|Option 1"
check "  → change_step: present_options" "present_options"

run "$INBOUND" --raw --call-id "${CALL_ID}-book" --exec select_slot --option_number 1
check "Select slot 1 → selected" "selected\|Selected"
check "  → change_step: confirm_booking" "confirm_booking"

run "$INBOUND" --raw --call-id "${CALL_ID}-book" --exec select_slot --option_number 99
check "Select slot 99 → invalid" "Invalid\|invalid"

run "$INBOUND" --raw --call-id "${CALL_ID}-book" --custom-data "$BRIAN_PROFILE" --exec book_appointment
check "Book appointment → booked" "booked\|Booked"
check "  → change_step: create_appointment" "create_appointment"

# No patient on file → error
run "$INBOUND" --raw --call-id "${CALL_ID}-book-nopat" --custom-data "$NEW_CALLER" --exec book_appointment
check "Book with no patient → error" "No patient"

# No slot selected → error
run "$INBOUND" --raw --call-id "${CALL_ID}-book-noslot" --custom-data "$BRIAN_PROFILE" --exec book_appointment
check "Book with no slot → error" "No slot"

# =============================================================================
section "5. Confirm Flow"
# =============================================================================

run "$INBOUND" --raw --call-id "${CALL_ID}-conf" --custom-data "$BRIAN_PROFILE" --exec route_intent --intent confirm
run "$INBOUND" --raw --call-id "${CALL_ID}-conf" --custom-data "$BRIAN_PROFILE" --exec get_patient_appointments
check "Get appointments → found" "Found.*appointment\|Appointment 1"

# Brian has multiple apts — must select one first
run "$INBOUND" --raw --call-id "${CALL_ID}-conf" --exec select_appointment_tool --appointment_number 1
check "Select apt for confirm" "Selected\|selected\|confirm_appointment"

run "$INBOUND" --raw --call-id "${CALL_ID}-conf" --exec confirm_appointment_tool
check "Confirm appointment → confirmed" "confirmed\|Confirmed"
check "  → change_step: wrap_up" "wrap_up"

run "$INBOUND" --raw --call-id "${CALL_ID}-conf-none" --exec confirm_appointment_tool
check "No apt selected → error" "No appointment"

# =============================================================================
section "6. Reschedule Flow"
# =============================================================================

run "$INBOUND" --raw --call-id "${CALL_ID}-resch" --custom-data "$BRIAN_PROFILE" --exec route_intent --intent reschedule
run "$INBOUND" --raw --call-id "${CALL_ID}-resch" --custom-data "$BRIAN_PROFILE" --exec get_patient_appointments

# Brian has multiple apts — must select one first
run "$INBOUND" --raw --call-id "${CALL_ID}-resch" --exec select_appointment_tool --appointment_number 1
check "Select apt for resched" "Selected\|selected\|collect_new_prefs"

run "$INBOUND" --raw --call-id "${CALL_ID}-resch" --custom-data "$RESCHED_PREFS" --exec search_available_slots
check "Resched search → found openings" "Found.*opening\|Option 1"
check "  → change_step: present_resched_options" "present_resched_options"

run "$INBOUND" --raw --call-id "${CALL_ID}-resch" --exec reschedule_appointment_tool --option_number 1
check "Reschedule → success" "rescheduled\|Rescheduled"
check "  → change_step: wrap_up" "wrap_up"

run "$INBOUND" --raw --call-id "${CALL_ID}-resch-none" --exec reschedule_appointment_tool --option_number 1
check "Resched no apt → error" "No appointment"

# =============================================================================
section "7. Cancel Flow"
# =============================================================================

run "$INBOUND" --raw --call-id "${CALL_ID}-canc" --custom-data "$BRIAN_PROFILE" --exec route_intent --intent cancel
run "$INBOUND" --raw --call-id "${CALL_ID}-canc" --custom-data "$BRIAN_PROFILE" --exec get_patient_appointments

# Brian has multiple apts — must select one first
run "$INBOUND" --raw --call-id "${CALL_ID}-canc" --exec select_appointment_tool --appointment_number 1
check "Select apt for cancel" "Selected\|selected\|confirm_cancel"

run "$INBOUND" --raw --call-id "${CALL_ID}-canc" --exec cancel_appointment_tool
check "Cancel appointment → cancelled" "cancelled\|Cancelled"
check "  → change_step: wrap_up" "wrap_up"

run "$INBOUND" --raw --call-id "${CALL_ID}-canc-none" --exec cancel_appointment_tool
check "Cancel no apt → error" "No appointment"

run "$INBOUND" --raw --call-id "${CALL_ID}-keep" --exec keep_appointment
check "Keep appointment → no problem" "No problem\|still on"
check "  → change_step: wrap_up" "wrap_up"

# =============================================================================
section "8. Insurance Flow"
# =============================================================================

# Brian has Delta Dental on file
run "$INBOUND" --raw --call-id "${CALL_ID}-ins" --custom-data "$BRIAN_PROFILE" --exec lookup_insurance_tool
check "Lookup insurance → found" "Insurance found\|Delta Dental"
check "  → change_step: read_insurance" "read_insurance"

# Filler patient with no insurance
NO_INS='{"global_data":{"patient_profile":{"PatNum":200,"first_name":"Alice","last_name":"Johnson"},"is_new_caller":false}}'
run "$INBOUND" --raw --call-id "${CALL_ID}-ins-empty" --custom-data "$NO_INS" --exec lookup_insurance_tool
check "No insurance → collect" "No insurance\|collect"
check "  → change_step: collect_insurance" "collect_insurance"

# No patient → error
run "$INBOUND" --raw --call-id "${CALL_ID}-ins-nopat" --custom-data "$NEW_CALLER" --exec lookup_insurance_tool
check "Lookup ins no patient → error" "No patient"

# Save new insurance (Cigna)
run "$INBOUND" --raw --call-id "${CALL_ID}-ins-save" --custom-data "$INSURANCE_ANSWERS" --exec save_insurance_tool
check "Save insurance → success" "Insurance saved\|saved"
check "  → change_step: save_insurance" "save_insurance"

# Save missing carrier
INS_NO_CARRIER='{"global_data":{"patient_profile":{"PatNum":100},"insurance_answers":{"carrier_name":"","member_id":"123"}}}'
run "$INBOUND" --raw --call-id "${CALL_ID}-ins-nocarr" --custom-data "$INS_NO_CARRIER" --exec save_insurance_tool
check "Missing carrier → error" "Missing carrier"

# Save missing member ID
INS_NO_MEMBER='{"global_data":{"patient_profile":{"PatNum":100},"insurance_answers":{"carrier_name":"Cigna","member_id":""}}}'
run "$INBOUND" --raw --call-id "${CALL_ID}-ins-nomem" --custom-data "$INS_NO_MEMBER" --exec save_insurance_tool
check "Missing member ID → error" "Missing member"

# Update insurance → redirect
run "$INBOUND" --raw --call-id "${CALL_ID}-ins-upd" --exec update_insurance_tool
check "Update insurance → collect_insurance" "collect_insurance"

# =============================================================================
section "9. Select Appointment (multi-appointment)"
# =============================================================================

run "$INBOUND" --raw --call-id "${CALL_ID}-selapt" --custom-data "$BRIAN_PROFILE" --exec route_intent --intent confirm
run "$INBOUND" --raw --call-id "${CALL_ID}-selapt" --custom-data "$BRIAN_PROFILE" --exec get_patient_appointments

run "$INBOUND" --raw --call-id "${CALL_ID}-selapt" --exec select_appointment_tool --appointment_number 1
check "Select apt 1 → selected" "Selected\|selected"

run "$INBOUND" --raw --call-id "${CALL_ID}-selapt" --exec select_appointment_tool --appointment_number 99
check "Select apt 99 → invalid" "Invalid\|invalid"

# No appointments loaded → error
run "$INBOUND" --raw --call-id "${CALL_ID}-selapt-empty" --exec select_appointment_tool --appointment_number 1
check "No apts loaded → invalid" "Invalid\|invalid\|No"

# =============================================================================
section "10. Utility Tools"
# =============================================================================

run "$INBOUND" --raw --call-id "${CALL_ID}-util" --exec decline_booking
check "decline_booking → present_options" "present_options"

run "$INBOUND" --raw --call-id "${CALL_ID}-ri-book" --exec search_again
check "search_again (book) → collect_appt_prefs" "collect_appt_prefs"

run "$INBOUND" --raw --call-id "${CALL_ID}-ri-resched" --exec search_again
check "search_again (resched) → collect_new_prefs" "collect_new_prefs"

run "$INBOUND" --raw --call-id "${CALL_ID}-util2" --exec restart
check "restart → identify_intent" "identify_intent"

run "$INBOUND" --raw --call-id "${CALL_ID}-book" --custom-data "$BRIAN_PROFILE" --exec log_call --summary "Test call - booked cleaning"
check "log_call → logged" "logged\|Logged"

# No patient → still logs
run "$INBOUND" --raw --call-id "${CALL_ID}-log-nopat" --custom-data "$NEW_CALLER" --exec log_call --summary "Anonymous test call"
check "log_call no patient → logged" "logged\|Logged"

# ═════════════════════════════════════════════════════════════════════════════
printf "\n${YELLOW}╔══════════════════════════════════════════════════════════╗${NC}\n"
printf "${YELLOW}║         Outbound Agent Tests                             ║${NC}\n"
printf "${YELLOW}╚══════════════════════════════════════════════════════════╝${NC}\n"

# =============================================================================
section "11. Outbound — Confirm + Cancel"
# =============================================================================

run "$OUTBOUND" --raw --call-id "${CALL_ID}-ob-conf" --custom-data "$OUTBOUND_CONFIRM" --exec confirm_outbound
check "confirm_outbound → confirmed" "confirmed\|Confirmed"
check "  → change_step: log_and_end" "log_and_end"

run "$OUTBOUND" --raw --call-id "${CALL_ID}-ob-canc" --custom-data "$OUTBOUND_CONFIRM" --exec cancel_outbound
check "cancel_outbound → cancelled" "cancelled\|Cancelled"
check "  → change_step: log_and_end" "log_and_end"

# =============================================================================
section "12. Outbound — Reschedule"
# =============================================================================

OB_RESCHED_PREFS='{"global_data":{"call_type":"confirmation","patient_profile":{"PatNum":100,"first_name":"Brian","last_name":"West"},"appointment":{"AptNum":1001,"ProvNum":4},"resched_prefs_answers":{"new_preferred_date":"'"$PREF_DATE"'","time_preference":"morning"}}}'

run "$OUTBOUND" --raw --call-id "${CALL_ID}-ob-resch" --custom-data "$OB_RESCHED_PREFS" --exec search_available_slots
check "Outbound search slots → found" "Found.*opening\|Option 1"

run "$OUTBOUND" --raw --call-id "${CALL_ID}-ob-resch" --custom-data "$OUTBOUND_CONFIRM" --exec reschedule_outbound --option_number 1
check "reschedule_outbound → rescheduled" "rescheduled\|Rescheduled"
check "  → change_step: log_and_end" "log_and_end"

# Invalid slot
run "$OUTBOUND" --raw --call-id "${CALL_ID}-ob-resch-bad" --exec reschedule_outbound --option_number 99
check "Outbound resched slot 99 → invalid" "Invalid\|invalid"

# =============================================================================
section "13. Outbound — Recall"
# =============================================================================

OB_RECALL_PREFS='{"global_data":{"call_type":"recall","patient_profile":{"PatNum":100,"first_name":"Brian","last_name":"West"},"recall_info":{"recall_type":"Prophy"},"recall_prefs_answers":{"preferred_date":"'"$PREF_DATE"'","time_preference":"morning"}}}'

run "$OUTBOUND" --raw --call-id "${CALL_ID}-ob-recall" --custom-data "$OB_RECALL_PREFS" --exec search_available_slots
check "Recall search slots → found" "Found.*opening\|Option 1"

run "$OUTBOUND" --raw --call-id "${CALL_ID}-ob-recall" --custom-data "$OUTBOUND_RECALL" --exec book_recall --option_number 1
check "book_recall → booked" "booked\|appointment"
check "  → change_step: log_and_end" "log_and_end"

run "$OUTBOUND" --raw --call-id "${CALL_ID}-ob-decline" --custom-data "$OUTBOUND_RECALL" --exec decline_recall
check "decline_recall → declined" "No problem\|remind"
check "  → change_step: log_and_end" "log_and_end"

# Invalid slot
run "$OUTBOUND" --raw --call-id "${CALL_ID}-ob-recall-bad" --exec book_recall --option_number 99
check "Book recall slot 99 → invalid" "Invalid\|invalid"

# =============================================================================
section "14. Outbound — Unable to Reach + Logging"
# =============================================================================

run "$OUTBOUND" --raw --call-id "${CALL_ID}-ob-vm" --exec unable_to_reach_tool --reason voicemail
check "unable_to_reach (voicemail)" "voicemail\|logged"
check "  → change_step: log_and_end" "log_and_end"

run "$OUTBOUND" --raw --call-id "${CALL_ID}-ob-na" --exec unable_to_reach_tool --reason no_answer
check "unable_to_reach (no_answer)" "no_answer\|logged"
check "  → change_step: log_and_end" "log_and_end"

run "$OUTBOUND" --raw --call-id "${CALL_ID}-ob-wn" --exec unable_to_reach_tool --reason wrong_number
check "unable_to_reach (wrong_number)" "wrong_number\|logged"
check "  → change_step: log_and_end" "log_and_end"

run "$OUTBOUND" --raw --call-id "${CALL_ID}-ob-log" --custom-data "$OUTBOUND_CONFIRM" --exec log_outbound_call --outcome confirmed --notes "Patient confirmed, no issues"
check "log_outbound_call → logged" "logged\|Logged\|Goodbye"

run "$OUTBOUND" --raw --call-id "${CALL_ID}-ob-log2" --custom-data "$OUTBOUND_RECALL" --exec log_outbound_call --outcome recall_declined
check "log_outbound_call (no notes) → logged" "logged\|Logged\|Goodbye"

# =============================================================================
# Summary
# =============================================================================
printf "\n${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
TOTAL=$((PASS + FAIL))
printf "  Total:  %d\n" "$TOTAL"
printf "  ${GREEN}Passed: %d${NC}\n" "$PASS"
printf "  ${RED}Failed: %d${NC}\n" "$FAIL"
if [ "$FAIL" -eq 0 ]; then
    printf "\n${GREEN}All tests passed!${NC}\n\n"
else
    printf "\n${RED}%d test(s) failed.${NC}\n\n" "$FAIL"
    exit 1
fi

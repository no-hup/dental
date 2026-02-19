#!/usr/bin/env python3
"""Outbound Confirmation Runner — Scheduler for proactive patient calls.

Queries upcoming appointments and recall lists, builds a call queue,
and initiates outbound calls via SignalWire REST API. In MOCK_MODE,
prints actions instead of making real calls.

Can be run standalone or integrated into the main agent server.
"""

import logging
import time
import threading
from datetime import datetime, timedelta
from urllib.parse import quote as url_quote

import requests

import config
import opendental_client as od

logger = logging.getLogger(__name__)


class ConfirmationRunner:
    """Manages the outbound confirmation queue and call scheduling."""

    def __init__(self):
        self.is_running = False
        self._last_run = None
        self._last_queue = []
        self._call_results = []

    def build_confirmation_queue(self):
        """Query upcoming appointments that need confirmation.

        Returns list of dicts with appointment + patient info.
        """
        today = datetime.now().date()
        start = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        end = (today + timedelta(days=config.CONFIRM_WINDOW_DAYS)).strftime("%Y-%m-%d")

        logger.info(f"Querying appointments: {start} to {end}")

        appointments = od.get_appointments_date_range(start, end, status="Scheduled")
        if not appointments:
            return []

        queue = []
        for apt in appointments:
            # Skip already confirmed
            confirmed = apt.get("Confirmed", "None")
            if confirmed == "Confirmed":
                continue

            pat_num = apt.get("PatNum")
            apt_num = apt.get("AptNum")

            # Get patient phone
            phone = apt.get("WirelessPhone") or apt.get("HmPhone")
            if not phone:
                patient = od.get_patient(pat_num)
                if patient:
                    phone = patient.get("WirelessPhone") or patient.get("HmPhone") or patient.get("WkPhone")

            if not phone:
                logger.warning(f"No phone for PatNum={pat_num}, skipping")
                continue

            first_name = apt.get("FName", "")
            last_name = apt.get("LName", "")
            prov_num = apt.get("ProvNum")
            apt_dt = apt.get("AptDateTime", "")
            note = apt.get("Note", "")

            queue.append({
                "type": "confirmation",
                "pat_num": pat_num,
                "apt_num": apt_num,
                "phone": phone,
                "first_name": first_name,
                "last_name": last_name,
                "prov_num": prov_num,
                "apt_datetime": apt_dt,
                "note": note,
            })

        return queue

    def build_recall_queue(self):
        """Query patients due for recall.

        Returns list of dicts with recall + patient info.
        """
        today = datetime.now().date()
        start = today.strftime("%Y-%m-%d")
        end = (today + timedelta(days=config.RECALL_WINDOW_DAYS)).strftime("%Y-%m-%d")

        logger.info(f"Querying recalls: {start} to {end}")

        recalls = od.get_recall_list(start, end)
        if not recalls:
            return []

        queue = []
        for recall in recalls:
            pat_num = recall.get("PatNum")
            phone = recall.get("WirelessPhone") or recall.get("HmPhone")
            if not phone:
                patient = od.get_patient(pat_num)
                if patient:
                    phone = patient.get("WirelessPhone") or patient.get("HmPhone") or patient.get("WkPhone")

            if not phone:
                continue

            queue.append({
                "type": "recall",
                "pat_num": pat_num,
                "phone": phone,
                "first_name": recall.get("FName", ""),
                "last_name": recall.get("LName", ""),
                "recall_type": recall.get("RecallType", "Prophy"),
                "date_due": recall.get("DateDue", ""),
            })

        return queue

    def _build_swml_url(self, entry):
        """Build the SWML webhook URL with embedded basic auth and query params."""
        call_type = entry.get("type", "confirmation")

        base_url = config.SWML_PROXY_URL_BASE or f"http://{config.HOST}:{config.PORT}"
        base_url = base_url.rstrip("/")

        params = f"call_type={call_type}&pat_num={entry.get('pat_num', '')}"
        if call_type == "confirmation":
            params += f"&apt_num={entry.get('apt_num', '')}"
        elif call_type == "recall":
            params += f"&recall_type={url_quote(entry.get('recall_type', 'Prophy'))}"

        # Embed basic auth credentials into the URL so SignalWire can
        # authenticate when fetching SWML from our server.
        if config.SWML_BASIC_AUTH_USER and config.SWML_BASIC_AUTH_PASSWORD:
            user = url_quote(config.SWML_BASIC_AUTH_USER, safe="")
            pwd = url_quote(config.SWML_BASIC_AUTH_PASSWORD, safe="")
            # Insert user:pass@ after the scheme://
            if "://" in base_url:
                scheme, rest = base_url.split("://", 1)
                base_url = f"{scheme}://{user}:{pwd}@{rest}"

        return f"{base_url}/outbound?{params}"

    def _initiate_call(self, entry):
        """Initiate an outbound call via the SignalWire Calls API.

        Uses POST /api/calling/calls with the "dial" command.
        In MOCK_MODE, logs the call instead of making real calls.
        """
        phone = entry.get("phone", "")
        name = f"{entry.get('first_name', '')} {entry.get('last_name', '')}".strip()
        call_type = entry.get("type", "confirmation")

        swml_url = self._build_swml_url(entry)

        if config.MOCK_MODE:
            logger.info(
                f"[MOCK] Would call {name} at {phone} "
                f"(type={call_type}, url={swml_url})"
            )
            self._call_results.append({
                "name": name,
                "phone": phone,
                "type": call_type,
                "status": "mock_logged",
                "timestamp": datetime.now().isoformat(),
                **entry,
            })
            return {"status": "mock", "message": f"Mock call to {name} at {phone}"}

        # Format phone for E.164
        if not phone.startswith("+"):
            phone = f"+1{phone}"

        # Format caller ID for E.164
        caller_id = config.OUTBOUND_CALLER_ID
        if caller_id and not caller_id.startswith("+"):
            caller_id = f"+1{caller_id}"

        try:
            api_url = f"https://{config.SIGNALWIRE_SPACE}/api/calling/calls"

            payload = {
                "command": "dial",
                "params": {
                    "from": caller_id,
                    "to": phone,
                    "caller_id": caller_id,
                    "url": swml_url,
                },
            }

            resp = requests.post(
                api_url,
                json=payload,
                auth=(config.SIGNALWIRE_PROJECT_ID, config.SIGNALWIRE_TOKEN),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=15,
            )
            resp.raise_for_status()
            result = resp.json()

            call_id = result.get("id", "")
            logger.info(f"Initiated outbound call to {name} at {phone}: {call_id}")
            self._call_results.append({
                "name": name,
                "phone": phone,
                "type": call_type,
                "status": "initiated",
                "call_id": call_id,
                "timestamp": datetime.now().isoformat(),
                **entry,
            })
            return {"status": "ok", "call_id": call_id}

        except Exception as e:
            logger.error(f"Failed to initiate call to {name}: {e}")
            self._call_results.append({
                "name": name,
                "phone": phone,
                "type": call_type,
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
                **entry,
            })
            return {"status": "error", "error": str(e)}

    def run(self):
        """Execute a confirmation run.

        1. Build confirmation queue (upcoming unconfirmed appointments)
        2. Build recall queue (patients due for recall)
        3. Process queue with concurrency limit
        """
        self.is_running = True
        self._last_run = datetime.now().isoformat()
        self._call_results = []

        logger.info("=== Starting confirmation run ===")

        # Build queues
        confirm_queue = self.build_confirmation_queue()
        recall_queue = self.build_recall_queue()

        full_queue = confirm_queue + recall_queue
        self._last_queue = full_queue

        logger.info(
            f"Queue built: {len(confirm_queue)} confirmations, "
            f"{len(recall_queue)} recalls, {len(full_queue)} total"
        )

        if not full_queue:
            logger.info("No calls to make")
            self.is_running = False
            return {"confirmations": 0, "recalls": 0, "total": 0}

        # Process queue with concurrency limit
        max_concurrent = config.MAX_OUTBOUND_CONCURRENT
        active_threads = []

        for entry in full_queue:
            # Wait if at concurrency limit
            while len(active_threads) >= max_concurrent:
                active_threads = [t for t in active_threads if t.is_alive()]
                if len(active_threads) >= max_concurrent:
                    time.sleep(1)

            thread = threading.Thread(
                target=self._initiate_call,
                args=(entry,),
                daemon=True,
            )
            thread.start()
            active_threads.append(thread)

            # Small delay between calls
            time.sleep(0.5)

        # Wait for all calls to complete
        for t in active_threads:
            t.join(timeout=30)

        logger.info(
            f"=== Confirmation run complete: {len(self._call_results)} calls processed ==="
        )
        self.is_running = False

        return {
            "confirmations": len(confirm_queue),
            "recalls": len(recall_queue),
            "total": len(full_queue),
            "results": self._call_results,
        }

    def get_status(self):
        """Get current status for dashboard API."""
        return {
            "is_running": self.is_running,
            "last_run": self._last_run,
            "queue_size": len(self._last_queue),
            "results": self._call_results,
            "schedule": config.OUTBOUND_SCHEDULE,
            "enabled": config.OUTBOUND_ENABLED,
        }

    def get_queue(self):
        """Get the current/last queue for dashboard API."""
        return self._last_queue


# Singleton instance
runner = ConfirmationRunner()


def start_scheduler():
    """Start the APScheduler cron job if OUTBOUND_ENABLED."""
    if not config.OUTBOUND_ENABLED:
        logger.info("Outbound confirmation disabled (OUTBOUND_ENABLED=false)")
        return None

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.warning(
            "APScheduler not installed. Install with: pip install apscheduler\n"
            "Outbound scheduling disabled. Use /api/confirmations/run for manual triggers."
        )
        return None

    scheduler = BackgroundScheduler()

    # Parse cron expression
    parts = config.OUTBOUND_SCHEDULE.split()
    if len(parts) == 5:
        trigger = CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
        )
    else:
        # Default: 9 AM weekdays
        trigger = CronTrigger(hour=9, minute=0, day_of_week="mon-fri")

    scheduler.add_job(runner.run, trigger, id="confirmation_run")
    scheduler.start()

    logger.info(f"Outbound scheduler started: {config.OUTBOUND_SCHEDULE}")
    return scheduler

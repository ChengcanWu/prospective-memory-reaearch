#!/usr/bin/env python3
"""Deterministic, no-LLM probes for one failure family of the intention store.

These are the cheap stand-in for a full PM-Bench week: each case is a tiny
typed vignette (cancel / reschedule / leftover / TIME-DUE / upsert).
Run after analyzing a score report; fix code until this script exits 0.

  python scripts/probe_intention_store.py
  python scripts/probe_intention_store.py --family update
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))

from pm_memory.common import build_compact_messages, extract_time_str
from pm_memory.intention_store import DueSlot, Intention, IntentionStoreBackend


def _store() -> IntentionStoreBackend:
    return IntentionStoreBackend(
        use_llm_update=False,
        use_llm_extract=False,
        use_llm_done=False,
        use_llm_match=False,
    )


def _intent(**kwargs) -> Intention:
    due = kwargs.pop("due", DueSlot(day="Tuesday"))
    return Intention(intent_id=kwargs.pop("intent_id", "i1"), due=due, **kwargs)


def case_cancel_does_not_kill_unrelated() -> str | None:
    """v0: cancel notice wiped every pending nearby. Apply only the named row."""
    s = _store()
    s.intentions["coop"] = _intent(
        intent_id="coop",
        action="Pay the co-op dues",
        due=DueSlot(day="Wednesday"),
    )
    s.intentions["asthma"] = _intent(
        intent_id="asthma",
        action="Take asthma medication",
        due=DueSlot(day="Wednesday", time="11:00"),
    )
    s._judge_index_to_id = {1: "coop", 2: "asthma"}
    s._apply_update_patches(
        [{"n": 1, "action": "cancel", "rationale": "scene voided co-op dues"}],
        day="Wednesday",
        time_str="",
    )
    if s.intentions["coop"].status != "canceled":
        return "coop should be canceled"
    if s.intentions["asthma"].status != "pending":
        return f"asthma was {s.intentions['asthma'].status}, expected pending"
    return None


def case_cue_firing_cancel_is_blocked() -> str | None:
    """Cue firing is event_due, not cancel; shield drops the cancel patch."""
    s = _store()
    s.intentions["key"] = _intent(
        intent_id="key",
        action="Pick up the room key",
        due=DueSlot(day="Tuesday"),
        event_cue="the conference room screen flashes your room assignment",
    )
    s._judge_index_to_id = {1: "key"}
    s._apply_update_patches(
        [{"n": 1, "action": "cancel", "rationale": "cue appeared"}],
        day="Tuesday",
        time_str="",
        event_due_ids={"key"},
    )
    if s.intentions["key"].status != "pending":
        return f"cue-firing row was {s.intentions['key'].status}, expected pending"
    if not any(
        skip.get("reason") == "cue_firing_not_cancel"
        for skip in s._update_skipped
    ):
        return "expected cue_firing_not_cancel skip"
    return None


def case_reschedule_rewrites_due_time() -> str | None:
    """v2: manager check-in moved to 15:55 must keep pending with new time."""
    s = _store()
    s.intentions["mgr"] = _intent(
        intent_id="mgr",
        action="Check in with your manager",
        due=DueSlot(day="Tuesday", time="14:00"),
    )
    s._judge_index_to_id = {1: "mgr"}
    s._apply_update_patches(
        [
            {
                "n": 1,
                "action": "reschedule",
                "new_time": "15:55",
                "new_day": "Tuesday",
                "rationale": "timing shifted",
            }
        ],
        day="Tuesday",
        time_str="",
    )
    got = s.intentions["mgr"]
    if got.status != "pending":
        return f"status={got.status}"
    if got.due.time != "15:55":
        return f"due.time={got.due.time!r}, expected 15:55"
    if got.due.day.lower() != "tuesday":
        return f"due.day={got.due.day!r}, expected Tuesday"
    return None


def case_day_change_does_not_cancel_pending() -> str | None:
    """v5: leftover sweep must not cancel still-open tasks at day change."""
    s = _store()
    s.intentions["tue"] = _intent(
        intent_id="tue",
        action="Check in with your manager",
        due=DueSlot(day="Tuesday", time="15:55"),
    )
    s.intentions["wed"] = _intent(
        intent_id="wed",
        action="Carry the prescription receipt",
        due=DueSlot(day="Wednesday"),
        event_cue="you notice the lab drop box",
    )
    messages = [
        {
            "role": "user",
            "content": "=== Wednesday ===\nToday's loose plan:\n- Take antibiotic at breakfast",
        }
    ]
    s._maybe_seed_daily(day="Wednesday")
    s._maybe_seed_day_plan(messages, day="Wednesday", time_str="")
    if s.intentions["tue"].status != "pending":
        return f"Tuesday leftover was {s.intentions['tue'].status}, expected pending"
    if s.intentions["wed"].status != "pending":
        return f"Wednesday due was {s.intentions['wed'].status}, expected pending"
    if not s._is_active_on_day(s.intentions["tue"], "Wednesday"):
        return "overdue Tuesday due should still inject on Wednesday"
    if not s._is_active_on_day(s.intentions["wed"], "Wednesday"):
        return "Wednesday due should inject on Wednesday"
    future = _intent(
        intent_id="fri",
        action="Carry the return label",
        due=DueSlot(day="Friday"),
        event_cue="doorbell camera flash",
    )
    if s._is_active_on_day(future, "Wednesday"):
        return "future Friday due must not inject on Wednesday"
    return None


def case_time_due_needs_trusted_clock() -> str | None:
    s = _store()
    s.intentions["a"] = _intent(
        intent_id="a",
        action="Take asthma medication",
        due=DueSlot(day="Monday", time="11:00"),
    )
    pending = list(s.intentions.values())
    if s._filter_time_due(pending, ""):
        return "no clock ⇒ no TIME-DUE"
    hits = s._filter_time_due(pending, "11:00")
    if [i.intent_id for i in hits] != ["a"]:
        return f"11:00 hits={hits}"
    if s._filter_time_due(pending, "11:01"):
        return "11:01 must not match 11:00 (tolerance 0)"
    return None


def case_unmatched_clock_is_today_pending() -> str | None:
    """Clock rows that are not TIME-DUE stay visible; choose still decides."""
    s = _store()
    mgr = _intent(
        intent_id="mgr",
        action="Check in with your manager",
        due=DueSlot(day="Tuesday", time="15:55"),
    )
    text = s._format_injection(
        time_hits=[],
        event_hits=[],
        channel_hits=[],
        channel_needed=[],
        today_pending=[mgr],
        day="Tuesday",
        time_str="15:20",
    )
    if "TIME-DUE" in text and "[TIME-DUE]" in text:
        return "15:20 must not TIME-DUE a 15:55 row"
    if "TIME-WAIT" in text:
        return "unmatched clock must not be hard-gated as TIME-WAIT"
    if "TODAY pending" not in text or "15:55" not in text:
        return "unmatched clock row should remain TODAY pending"
    return None


def case_narrative_hhmm_is_not_clock() -> str | None:
    text = "Remind yourself to take asthma medication at 11:00 after the meeting."
    if extract_time_str(text):
        return f"narrative at 11:00 leaked as clock: {extract_time_str(text)!r}"
    ok = extract_time_str("Time: 11:00 | Stopwatch: 00:12")
    if ok != "11:00":
        return f"system Time: line not parsed, got {ok!r}"
    return None


def case_asthma_two_slots_not_merged() -> str | None:
    """v1: 0.72 upsert merged 11:00 and 21:00 into one row."""
    s = _store()
    s._extract_from_text(
        "- Take asthma medication at 11:00\n- Take asthma medication at 21:00",
        day="Monday",
    )
    times = sorted(
        i.due.time
        for i in s.intentions.values()
        if i.status == "pending" and "asthma" in i.action.lower()
    )
    if times != ["11:00", "21:00"]:
        return f"asthma times={times}, expected ['11:00', '21:00']"
    return None


def case_duplicate_inserts_not_merged() -> str | None:
    """v4.2: identical bullets must both stay; no action-overlap upsert."""
    s = _store()
    s._extract_from_text(
        "- Pick up the dry cleaning when the text arrives\n"
        "- Pick up the dry cleaning when the text arrives",
        day="Monday",
    )
    n = sum(
        1
        for i in s.intentions.values()
        if i.status == "pending" and "dry cleaning" in i.action.lower()
    )
    if n != 2:
        return f"expected 2 dry-cleaning rows, got {n}"
    return None


def case_done_marks_by_n_not_overlap() -> str | None:
    """Overlap ≥ 0.4 would mark both asthma slots; n=1 must only close 11:00."""
    s = _store()
    s.intentions["a11"] = _intent(
        intent_id="a11",
        action="Take asthma medication",
        due=DueSlot(day="Monday", time="11:00"),
    )
    s.intentions["a21"] = _intent(
        intent_id="a21",
        action="Take asthma medication",
        due=DueSlot(day="Monday", time="21:00"),
    )
    s._judge_index_to_id = {1: "a11", 2: "a21"}
    hits = s._apply_done_ns([1])
    if hits != 1:
        return f"hits={hits}"
    if s.intentions["a11"].status != "done":
        return "11:00 should be done"
    if s.intentions["a21"].status != "pending":
        return f"21:00 was {s.intentions['a21'].status}; overlap would have killed it"
    return None


def case_parse_strips_think_tags() -> str | None:
    data = IntentionStoreBackend._try_parse_judge_json(
        "<think>Let me analyze the scene.</think>\n{\"updates\": []}"
    )
    if data != {"updates": []}:
        return f"think-wrapped JSON not parsed: {data!r}"
    return None


def case_parse_json_in_prose() -> str | None:
    data = IntentionStoreBackend._try_parse_judge_json(
        "Sure, here you go:\n```json\n{\"done\": [1, 2]}\n```\n"
    )
    if data != {"done": [1, 2]}:
        return f"fenced JSON not parsed: {data!r}"
    return None


def case_done_empty_labels_skips() -> str | None:
    s = _store()
    s.intentions["a"] = _intent(
        intent_id="a",
        action="Take asthma medication",
        due=DueSlot(day="Monday", time="11:00"),
    )
    n = s._mark_done_by_choice([], day="Monday")
    if n != 0:
        return f"empty labels marked {n}"
    if s.intentions["a"].status != "pending":
        return "empty labels should not mark done"
    return None


def case_event_pending_section_visible() -> str | None:
    """v4.5: event-cued today pending must not be buried only in TODAY pending."""
    s = _store()
    receipt = _intent(
        intent_id="receipt",
        action="Carry the prescription receipt",
        due=DueSlot(day="Wednesday"),
        event_cue="you notice the lab drop box",
    )
    asthma = _intent(
        intent_id="asthma",
        action="Take asthma medication",
        due=DueSlot(day="Wednesday", time="11:00"),
    )
    s.intentions[receipt.intent_id] = receipt
    s.intentions[asthma.intent_id] = asthma
    text = s._format_injection(
        time_hits=[],
        event_hits=[],
        channel_hits=[],
        channel_needed=[],
        today_pending=[receipt, asthma],
        day="Wednesday",
        time_str="",
    )
    if "EVENT pending" not in text:
        return "missing EVENT pending section"
    if "[EVENT]" not in text or "Carry the prescription receipt" not in text:
        return "event-cued row not tagged EVENT"
    if "EVENT-CUED" in text:
        return "must not stamp EVENT-CUED"
    # unmatched clock row is a soft TODAY pending, not a TIME-WAIT gate
    if "TIME-WAIT" in text:
        return "unmatched clock must not be TIME-WAIT"
    if "TODAY pending" not in text or "Take asthma medication" not in text:
        return "asthma without TIME-DUE should stay TODAY pending"
    return None


def case_event_plan_bullet_has_no_due() -> str | None:
    """Planting day must not become due.day for event-only plan bullets."""
    s = _store()
    s._extract_from_text(
        "- Adjust the prep plan when the calendar room shift appears",
        day="Tuesday",
    )
    rows = [i for i in s.intentions.values() if "prep plan" in i.action.lower()]
    if len(rows) != 1:
        return f"rows={len(rows)}"
    got = rows[0]
    if got.due.day:
        return f"event-only due.day={got.due.day!r}, expected empty"
    if got.due.time:
        return f"unexpected due.time={got.due.time!r}"
    if "calendar room shift" not in (got.event_cue or "").lower():
        return f"event_cue={got.event_cue!r}"
    text = s._format_injection(
        time_hits=[],
        event_hits=[],
        channel_hits=[],
        channel_needed=[],
        today_pending=[got],
        day="Tuesday",
        time_str="",
    )
    if "due=" in text:
        return f"injection still labeled due: {text}"
    if "[EVENT]" not in text:
        return "event-only row should still be EVENT pending"
    return None


def case_cross_day_on_clause_keeps_due_day() -> str | None:
    """On Wednesday + when-clause is a real calendar due, not the planting day."""
    s = _store()
    s._extract_from_text(
        "On Wednesday, Email the room change note when you notice the lab cubby.",
        day="Tuesday",
    )
    rows = [
        i for i in s.intentions.values() if "room change" in i.action.lower()
    ]
    if len(rows) != 1:
        return f"rows={len(rows)} {[i.action for i in s.intentions.values()]}"
    got = rows[0]
    if (got.due.day or "").lower() != "wednesday":
        return f"due.day={got.due.day!r}, expected Wednesday"
    if "lab cubby" not in (got.event_cue or "").lower():
        return f"event_cue={got.event_cue!r}"
    return None


def case_extract_item_strips_planting_day() -> str | None:
    """LLM extract must not keep TODAY / planting weekday on event-only rows."""
    s = _store()
    same = s._intention_from_extract_item(
        {
            "action": "Take antibiotic",
            "due_day": "Tuesday",
            "due_time": None,
            "event_cue": "breakfast",
            "watch": [],
        },
        today="Tuesday",
    )
    if same.due.day:
        return f"planting-day event due.day={same.due.day!r}"
    today_token = s._intention_from_extract_item(
        {
            "action": "Collect the dry cleaning",
            "due_day": "TODAY",
            "due_time": None,
            "event_cue": "confirmation email",
            "watch": [],
        },
        today="Friday",
    )
    if today_token.due.day:
        return f"TODAY token became due.day={today_token.due.day!r}"
    named = s._intention_from_extract_item(
        {
            "action": "Email the room change note",
            "due_day": "Wednesday",
            "due_time": None,
            "event_cue": "notice the lab cubby",
            "watch": [],
        },
        today="Tuesday",
    )
    if (named.due.day or "").lower() != "wednesday":
        return f"named weekday dropped: {named.due.day!r}"
    timed = s._intention_from_extract_item(
        {
            "action": "Take asthma medication",
            "due_day": None,
            "due_time": "11:00",
            "event_cue": None,
            "watch": [],
        },
        today="Monday",
    )
    if (timed.due.day or "").lower() != "monday" or timed.due.time != "11:00":
        return f"clock task due={timed.due.day!r} {timed.due.time!r}"
    return None


def case_event_no_due_survives_leftover() -> str | None:
    """Empty due.day is not a calendar due; leftover must not invent planting day."""
    s = _store()
    s.intentions["evt"] = _intent(
        intent_id="evt",
        action="Adjust the prep plan",
        due=DueSlot(day="", time=""),
        event_cue="the calendar room shift appears",
    )
    messages = [
        {
            "role": "user",
            "content": "=== Wednesday ===\nToday's loose plan:\n- Take antibiotic at breakfast",
        }
    ]
    s._maybe_seed_daily(day="Wednesday")
    s._maybe_seed_day_plan(messages, day="Wednesday", time_str="")
    if s.intentions["evt"].status != "pending":
        return f"undated event leftover-canceled: {s.intentions['evt'].status}"
    return None


def case_daily_event_meds_have_no_due_day() -> str | None:
    s = _store()
    s._maybe_seed_daily(day="Tuesday")
    breakfast = [
        i for i in s.intentions.values() if (i.event_cue or "").lower() == "breakfast"
    ]
    if len(breakfast) != 1:
        return f"breakfast rows={len(breakfast)}"
    if breakfast[0].due.day:
        return f"antibiotic breakfast due.day={breakfast[0].due.day!r}"
    asthma = [
        i
        for i in s.intentions.values()
        if i.due.time == "11:00" and "asthma" in i.action.lower()
    ]
    if len(asthma) != 1:
        return f"asthma 11:00 rows={len(asthma)}"
    if (asthma[0].due.day or "").lower() != "tuesday":
        return f"asthma due.day={asthma[0].due.day!r}, expected Tuesday"
    return None


def case_filter_trace_drops_future_not_event() -> str | None:
    """Calendar hides future due.day; event/channel are grouped, not dropped."""
    s = _store()
    future = _intent(
        intent_id="fri",
        action="Carry the return label",
        due=DueSlot(day="Friday"),
        event_cue="doorbell camera flash",
    )
    asth = _intent(
        intent_id="a11",
        action="Take asthma medication",
        due=DueSlot(day="Wednesday", time="11:00"),
    )
    later = _intent(
        intent_id="a21",
        action="Take asthma medication",
        due=DueSlot(day="Wednesday", time="21:00"),
    )
    evt = _intent(
        intent_id="rec",
        action="Carry the prescription receipt",
        due=DueSlot(day="Wednesday"),
        event_cue="you notice the lab drop box",
        watch=["course_portal"],
    )
    pending = [future, asth, later, evt]
    s.intentions = {i.intent_id: i for i in pending}
    today = [i for i in pending if s._is_active_on_day(i, "Wednesday")]
    time_hits = s._filter_time_due(today, "11:00")
    needed = s._watch_needed(today, [])
    trace = s._build_filter_trace(
        pending=pending,
        today_pending=today,
        time_hits=time_hits,
        channel_needed=needed,
        day="Wednesday",
        step="s4",
        time_str="11:00",
        messages=[],
        extracted=[],
        extract_added=0,
    )
    dropped = {r["id"] for r in trace["drop_future_due_day"]}
    if dropped != {"fri"}:
        return f"drop_future={dropped}, expected {{fri}}"
    if {r["id"] for r in trace["time_due"]} != {"a11"}:
        return f"time_due={[r['id'] for r in trace['time_due']]}"
    if {r["id"] for r in trace["time_not_due"]} != {"a21"}:
        return f"time_not_due={[r['id'] for r in trace['time_not_due']]}"
    if "rec" not in {r["id"] for r in trace["event_group"]}:
        return "event row missing from event_group"
    if "rec" in dropped:
        return "event row was code-dropped"
    text = s._format_filter_trace(trace)
    if "不筛掉" not in text:
        return "trace text should say event/channel are not dropped"
    if "Carry the return label" not in text or "筛掉未来" not in text:
        return f"missing calendar drop in text: {text[:400]}"
    return None


def case_match_filter_drops_unmatched_event() -> str | None:
    """Scene Judge labels: unmatched event dropped; unqueried watch kept."""
    s = _store()
    fire = _intent(
        intent_id="fire",
        action="Carry the prescription receipt",
        due=DueSlot(day="Wednesday"),
        event_cue="you notice the lab drop box",
    )
    wait = _intent(
        intent_id="wait",
        action="Carry the laundry soap",
        due=DueSlot(day="Wednesday"),
        event_cue="notice the laundry room cart",
    )
    email = _intent(
        intent_id="email",
        action="Forward the vendor reply",
        due=DueSlot(day="Wednesday"),
        event_cue="",
        watch=["email"],
    )
    hold = _intent(
        intent_id="hold",
        action="Collect the reserve reading",
        due=DueSlot(day="Wednesday"),
        event_cue="",
        watch=["library_hold"],
    )
    pending = [fire, wait, email, hold]
    split = s._apply_match_labels(
        pending,
        event_due_ids={"fire"},
        channel_due_ids=set(),
        queried={"library_hold"},
    )
    kept = {i.intent_id for i in split["kept"]}
    if "wait" in kept:
        return "unmatched event should be dropped"
    if "fire" not in kept:
        return "matched event should remain"
    if "email" not in kept:
        return "unqueried watch should remain for CHECK"
    if "hold" in kept:
        return "queried watch that is not channel_due should drop"
    text = s._format_injection(
        time_hits=[],
        event_hits=split["event_due"],
        channel_hits=split["channel_due"],
        channel_needed=["email"],
        today_pending=split["kept"],
        day="Wednesday",
        time_str="",
        match_filtered=True,
    )
    if "Carry the laundry soap" in text:
        return "dropped event leaked into choose injection"
    if "EVENT due" not in text:
        return "matched event should be EVENT due"
    if "EVENT-CUED" in text:
        return "must not stamp EVENT-CUED"
    if "Forward the vendor reply" not in text:
        return "channel wait row missing from injection"
    if "MUST query_state" in text:
        return "must not force business-channel query_state"
    needed = s._watch_needed(split["kept"], [])
    if needed != ["email"]:
        return f"CHECK should be email wait only, got {needed}"
    # Match off: vignette may contain the cue; still no due stamp / no drop.
    off = s._match_event_channel(
        pending,
        observation="You notice the lab drop box by the cubby.",
        day="Wednesday",
        time_str="",
        messages=[],
    )
    if off["mode"] != "off":
        return f"probe default match mode={off['mode']!r}, expected off"
    if [i.intent_id for i in off["kept"]] != [i.intent_id for i in pending]:
        return "match off should keep all today pending"
    if off["event_due"] or off["channel_due"]:
        return "match off must not stamp EVENT/CHANNEL due (no substring cover)"
    # Hallucinated channel_due without this-step State → wait, not due.
    fake = s._apply_match_labels(
        [email],
        event_due_ids=set(),
        channel_due_ids={"email"},
        queried=set(),
    )
    if fake["channel_due"]:
        return "no State must not stamp CHANNEL-DUE"
    if "email" not in {i.intent_id for i in fake["kept"]}:
        return "no State wait must stay so choose can query"
    if "email" not in {i.intent_id for i in fake["channel_wait"]}:
        return "no State should be channel_wait"
    return None


def case_shared_cue_fanout_and_group() -> str | None:
    """One judge hit due-stamps every stored row watching the same cue."""
    s = _store()
    slip = _intent(
        intent_id="slip",
        action="Drop off the sample slip",
        due=DueSlot(day="Wednesday"),
        event_cue="the lab drop box is unlocked",
    )
    receipt = _intent(
        intent_id="receipt",
        action="Carry the prescription receipt",
        due=DueSlot(day="Wednesday"),
        event_cue="you notice the lab drop box",
    )
    cubby = _intent(
        intent_id="handout",
        action="Pick up the handout packet",
        due=DueSlot(day="Wednesday"),
        event_cue="it shows up in the lab cubby",
    )
    note = _intent(
        intent_id="note",
        action="Email the room change note",
        due=DueSlot(day="Wednesday"),
        event_cue="notice the lab cubby",
    )
    soap = _intent(
        intent_id="soap",
        action="Carry the laundry soap",
        due=DueSlot(day="Wednesday"),
        event_cue="notice the laundry room cart",
    )
    pending = [slip, receipt, cubby, note, soap]
    expanded = s._expand_event_due_ids(pending, {"slip"})
    if expanded != {"slip", "receipt"}:
        return f"drop-box fanout={expanded}, expected slip+receipt"
    none = s._expand_event_due_ids(pending, set())
    if none:
        return f"empty judge hit must not scan cues, got {none}"
    cubby_hit = s._expand_event_due_ids(pending, {"handout"})
    if cubby_hit != {"handout", "note"}:
        return f"cubby fanout={cubby_hit}, expected handout+note"
    split = s._apply_match_labels(
        pending,
        event_due_ids=expanded,
        channel_due_ids=set(),
        queried=set(),
    )
    due_ids = {i.intent_id for i in split["event_due"]}
    if due_ids != {"slip", "receipt"}:
        return f"event_due after fanout={due_ids}"
    if "soap" in {i.intent_id for i in split["kept"]}:
        return "unrelated laundry cue should drop"
    text = s._format_injection(
        time_hits=[],
        event_hits=split["event_due"],
        channel_hits=[],
        channel_needed=[],
        today_pending=split["kept"],
        day="Wednesday",
        time_str="11:50",
        match_filtered=True,
    )
    if "EVENT-CUED" in text:
        return "must not stamp EVENT-CUED"
    if "EVENT due" not in text:
        return "shared cue should inject EVENT due"
    if "[lab drop box]" not in text:
        return f"missing shared-cue group header: {text}"
    if "Drop off the sample slip" not in text or "Carry the prescription receipt" not in text:
        return "both drop-box actions must appear"
    if "ALL matching" not in text:
        return "injection must tell choose to do every matching handle"
    if "Pick up the handout packet" in text or "Email the room change note" in text:
        return "cubby rows leaked into drop-box due block"
    pending_text = s._format_injection(
        time_hits=[],
        event_hits=[],
        channel_hits=[],
        channel_needed=[],
        today_pending=[slip, receipt, soap],
        day="Wednesday",
        time_str="",
    )
    if "[lab drop box]" not in pending_text:
        return f"EVENT pending should still group shared cues: {pending_text}"
    if "do ALL rows that share that cue" not in pending_text:
        return "EVENT pending header should say do all shared-cue rows"
    return None


def case_shared_cue_rejects_generic_unigram() -> str | None:
    """'email' alone must not glue two different mail cues."""
    s = _store()
    vendor = _intent(
        intent_id="vendor",
        action="Forward the vendor reply",
        due=DueSlot(day="Tuesday"),
        event_cue="the email lands",
    )
    confirm = _intent(
        intent_id="confirm",
        action="Save the receipt",
        due=DueSlot(day="Tuesday"),
        event_cue="the confirmation email arrives",
    )
    expanded = s._expand_event_due_ids([vendor, confirm], {"vendor"})
    if expanded != {"vendor"}:
        return f"email unigram fanout={expanded}, expected vendor only"
    return None


def case_menu_paraphrase_still_injected() -> str | None:
    """v4: 0.34 menu overlap used to drop paraphrased pending; choose aligns now."""
    s = _store()
    filt = _intent(
        intent_id="filter",
        action="Pick up the replacement filter",
        due=DueSlot(day="Tuesday"),
        event_cue="the follow-up text arrives",
    )
    s.intentions[filt.intent_id] = filt
    menu_label = "Collect the HVAC filter from the hardware store"
    score = s._overlap_score(menu_label, filt.action)
    if score >= 0.34:
        return f"fixture too similar to menu (overlap={score:.2f}); need < 0.34"
    text = s._format_injection(
        time_hits=[],
        event_hits=[],
        channel_hits=[],
        channel_needed=[],
        today_pending=[filt],
        day="Tuesday",
        time_str="",
    )
    if "Pick up the replacement filter" not in text:
        return "paraphrased today pending was not injected"
    if "menu-aligned" in text.lower():
        return "old menu-aligned gate label still present"
    return None


def case_compact_strips_day_plan() -> str | None:
    """Intention compact prompt keeps weekday, drops the stale morning list."""
    messages = [
        {"role": "system", "content": "You are taking a prospective memory evaluation."},
        {
            "role": "user",
            "content": "Regular tasks for every day:\n- Take antibiotic at breakfast.",
        },
        {
            "role": "user",
            "content": (
                "=== Monday ===\n"
                "Today's loose plan:\n"
                "- Return the library book when the return slot is open."
            ),
        },
        {
            "role": "user",
            "content": (
                "The library return slot is open as you walk by.\n"
                "A) Make a note\n"
                "Step action menu:\n"
                "- task_3: Return the library book."
            ),
        },
    ]
    kept = build_compact_messages(messages, include_day_plan=True)
    plan_msgs = [m["content"] for m in kept if "loose plan" in m.get("content", "")]
    if not plan_msgs:
        return "include_day_plan=True should keep the morning list"
    stripped = build_compact_messages(messages, include_day_plan=False)
    joined = "\n".join(m.get("content") or "" for m in stripped)
    header = next(
        (m["content"] for m in stripped if m.get("content", "").startswith("=== ")),
        "",
    )
    if "return slot" in header.lower():
        return "stale plan when-clause still in day header"
    if "=== Monday ===" not in joined:
        return "weekday header was dropped"
    if "Regular tasks for every day" not in joined:
        return "standing daily tasks should stay"
    if "The library return slot is open" not in joined:
        return "current vignette must remain"
    return None


CASES = {
    "update": [
        ("cancel_precision", case_cancel_does_not_kill_unrelated),
        ("cue_firing_not_cancel", case_cue_firing_cancel_is_blocked),
        ("reschedule_time", case_reschedule_rewrites_due_time),
        ("day_change_keeps_pending", case_day_change_does_not_cancel_pending),
        ("parse_think", case_parse_strips_think_tags),
        ("parse_fence", case_parse_json_in_prose),
        ("compact_strips_plan", case_compact_strips_day_plan),
    ],
    "time": [
        ("time_due_exact", case_time_due_needs_trusted_clock),
        ("clock_stays_pending", case_unmatched_clock_is_today_pending),
        ("no_narrative_clock", case_narrative_hhmm_is_not_clock),
        ("asthma_slots", case_asthma_two_slots_not_merged),
        ("no_insert_dedup", case_duplicate_inserts_not_merged),
        ("daily_event_no_due", case_daily_event_meds_have_no_due_day),
        ("filter_trace", case_filter_trace_drops_future_not_event),
    ],
    "cross_day": [
        ("day_change_keeps_pending", case_day_change_does_not_cancel_pending),
        ("event_pending_section", case_event_pending_section_visible),
        ("shared_cue_fanout", case_shared_cue_fanout_and_group),
        ("cross_day_on_clause", case_cross_day_on_clause_keeps_due_day),
        ("event_no_due_leftover", case_event_no_due_survives_leftover),
    ],
    "event": [
        ("menu_paraphrase_injected", case_menu_paraphrase_still_injected),
        ("event_pending_section", case_event_pending_section_visible),
        ("event_plan_no_due", case_event_plan_bullet_has_no_due),
        ("extract_strips_plant_day", case_extract_item_strips_planting_day),
        ("event_no_due_leftover", case_event_no_due_survives_leftover),
        ("daily_event_no_due", case_daily_event_meds_have_no_due_day),
        ("cross_day_on_clause", case_cross_day_on_clause_keeps_due_day),
        ("filter_trace", case_filter_trace_drops_future_not_event),
        ("match_event_channel", case_match_filter_drops_unmatched_event),
        ("shared_cue_fanout", case_shared_cue_fanout_and_group),
        ("shared_cue_unigram", case_shared_cue_rejects_generic_unigram),
        ("cue_firing_not_cancel", case_cue_firing_cancel_is_blocked),
    ],
    "false_alarm": [
        ("menu_paraphrase_injected", case_menu_paraphrase_still_injected),
        ("done_by_n", case_done_marks_by_n_not_overlap),
    ],
    "done": [
        ("done_by_n", case_done_marks_by_n_not_overlap),
        ("done_skip_empty", case_done_empty_labels_skips),
    ],
}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--family",
        choices=["all", *CASES.keys()],
        default="all",
        help="Only run probes for this failure family (from analyze_intention_run)",
    )
    args = p.parse_args()
    selected = []
    if args.family == "all":
        seen = set()
        for group in CASES.values():
            for name, fn in group:
                if name not in seen:
                    selected.append((name, fn))
                    seen.add(name)
    else:
        selected = list(CASES[args.family])

    failed = 0
    for name, fn in selected:
        err = fn()
        if err:
            print(f"FAIL {name}: {err}")
            failed += 1
        else:
            print(f"ok   {name}")
    if failed:
        print(f"{failed}/{len(selected)} failed")
        return 1
    print(f"{len(selected)} probes passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

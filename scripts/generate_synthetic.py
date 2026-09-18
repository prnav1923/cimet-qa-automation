"""Generates every file in data/synthetic/ per SYNTHETIC-DATA.md.

Deterministic: random.seed(42) plus a fixed call order means re-running this
script produces byte-identical output files. All data here is fabricated —
no real names, addresses, emails, phone numbers, or retailer names.
"""

import hashlib
import json
import random
from pathlib import Path

from pydub import AudioSegment
from pydub.generators import Sine

SYN_DIR = Path("data/synthetic")
TRANSCRIPTS_DIR = SYN_DIR / "transcripts"
AUDIO_DIR = SYN_DIR / "audio"

AGENT = "AGENT"
CUSTOMER = "CUSTOMER"
AGENT_N = 0
CUSTOMER_N = 1

RETAILER_ID = "RTL_001"
RETAILER_NAME = "Aurora Energy"

# ---------------------------------------------------------------------------
# Check library text (verbatim scripts for Type A checks)
# ---------------------------------------------------------------------------

TXT_DISCLAIMER = "This call is being recorded for quality and compliance purposes."
TXT_ACCOUNT_HOLDER = "Can I confirm I'm speaking with the account holder listed on the bill?"
TXT_DMO_V1 = (
    "Just so you know, we'll compare this plan's cost to the government "
    "benchmark price for energy in your area."
)
TXT_DMO_V2 = (
    "This plan's estimated annual cost is compared against the Default "
    "Market Offer set by the Australian Energy Regulator for your "
    "distribution zone."
)
TXT_COOLING_OFF = (
    "You have a ten business day cooling-off period during which you can "
    "cancel this agreement at no cost."
)
TXT_TERMS = "We'll email you the full terms and conditions along with your welcome pack."

# A paraphrase of the DMO v2 wording that scores ~0.72-0.76 partial_ratio
# against TXT_DMO_V2 (rapidfuzz-checked at authoring time) -- lands between
# fail_at (0.60) and pass_at (0.85), i.e. LOW_CONFIDENCE.
TXT_DMO_MUMBLE = (
    "This plan's yearly cost is checked against that Default Market Offer "
    "thing set by the regulator for your area."
)

# ---------------------------------------------------------------------------
# Check library rows (15 rows: 14 checks, DMO has 2 versions)
# ---------------------------------------------------------------------------

CHECKS = [
    {
        "check_id": "CHK_A_DISCLAIMER", "version": 1, "type": "A",
        "description": "Recording disclaimer read",
        "is_critical": True, "weight": 3.0,
        "effective_from": "2025-01-01", "effective_to": None,
        "expected_script_text": TXT_DISCLAIMER,
        "pass_at": 0.85, "fail_at": 0.60, "min_word_confidence": 0.55,
    },
    {
        "check_id": "CHK_A_ACCOUNT_HOLDER", "version": 1, "type": "A",
        "description": "Account holder confirmed",
        "is_critical": True, "weight": 3.0,
        "effective_from": "2025-01-01", "effective_to": None,
        "expected_script_text": TXT_ACCOUNT_HOLDER,
        "pass_at": 0.85, "fail_at": 0.60, "min_word_confidence": 0.55,
    },
    {
        "check_id": "CHK_A_DMO", "version": 1, "type": "A",
        "description": "DMO reference price read verbatim",
        "is_critical": True, "weight": 3.0,
        "effective_from": "2025-01-01", "effective_to": "2026-07-01",
        "expected_script_text": TXT_DMO_V1,
        "pass_at": 0.85, "fail_at": 0.60, "min_word_confidence": 0.55,
        "provenance": {"expected_script_text": "drafted — CIMET did not supply v1 wording"},
    },
    {
        "check_id": "CHK_A_DMO", "version": 2, "type": "A",
        "description": "DMO reference price read verbatim",
        "is_critical": True, "weight": 3.0,
        "effective_from": "2026-07-01", "effective_to": None,
        "expected_script_text": TXT_DMO_V2,
        "pass_at": 0.85, "fail_at": 0.60, "min_word_confidence": 0.55,
    },
    {
        "check_id": "CHK_A_COOLING_OFF", "version": 1, "type": "A",
        "description": "Cooling-off rights stated",
        "is_critical": True, "weight": 3.0,
        "effective_from": "2025-01-01", "effective_to": None,
        "expected_script_text": TXT_COOLING_OFF,
        "pass_at": 0.85, "fail_at": 0.60, "min_word_confidence": 0.55,
    },
    {
        "check_id": "CHK_A_TERMS", "version": 1, "type": "A",
        "description": "T&Cs delivery explained",
        "is_critical": False, "weight": 1.0,
        "effective_from": "2025-01-01", "effective_to": None,
        "expected_script_text": TXT_TERMS,
        "pass_at": 0.85, "fail_at": 0.60, "min_word_confidence": 0.55,
    },
    {
        "check_id": "CHK_B_PEAK_RATE", "version": 1, "type": "B",
        "description": "Peak rate quoted matches plan",
        "is_critical": True, "weight": 3.0,
        "effective_from": "2025-01-01", "effective_to": None,
        "plan_field": "peak_rate_c_per_kwh", "comparator": "rate", "tolerance": 0.05,
    },
    {
        "check_id": "CHK_B_DAILY_SUPPLY", "version": 1, "type": "B",
        "description": "Daily supply charge matches plan",
        "is_critical": True, "weight": 3.0,
        "effective_from": "2025-01-01", "effective_to": None,
        "plan_field": "daily_supply_c", "comparator": "rate", "tolerance": 0.05,
    },
    {
        "check_id": "CHK_B_EMAIL", "version": 1, "type": "B",
        "description": "Email read back matches CRM",
        "is_critical": True, "weight": 3.0,
        "effective_from": "2025-01-01", "effective_to": None,
        "crm_field": "email", "comparator": "email", "tolerance": 0.0,
    },
    {
        "check_id": "CHK_B_ADDRESS", "version": 1, "type": "B",
        "description": "Supply address matches CRM",
        "is_critical": True, "weight": 3.0,
        "effective_from": "2025-01-01", "effective_to": None,
        "crm_field": "supply_address", "comparator": "address", "tolerance": 0.0,
    },
    {
        "check_id": "CHK_B_DOB", "version": 1, "type": "B",
        "description": "DOB confirmed matches CRM",
        "is_critical": True, "weight": 3.0,
        "effective_from": "2025-01-01", "effective_to": None,
        "crm_field": "dob", "comparator": "date", "tolerance": 0.0,
    },
    {
        "check_id": "CHK_B_NMI", "version": 1, "type": "B",
        "description": "NMI confirmed matches CRM",
        "is_critical": True, "weight": 3.0,
        "effective_from": "2025-01-01", "effective_to": None,
        "crm_field": "nmi", "comparator": "text", "tolerance": 0.0,
    },
    {
        "check_id": "CHK_C_DEAD_AIR", "version": 1, "type": "C",
        "description": "No dead air over 30s",
        "is_critical": False, "weight": 1.0,
        "effective_from": "2025-01-01", "effective_to": None,
        "params": {"max_dead_air_s": 30},
    },
    {
        "check_id": "CHK_C_INTERRUPTIONS", "version": 1, "type": "C",
        "description": "Agent interruptions under 5",
        "is_critical": False, "weight": 1.0,
        "effective_from": "2025-01-01", "effective_to": None,
        "params": {"max_interruptions": 5},
    },
    {
        "check_id": "CHK_C_TALK_RATIO", "version": 1, "type": "C",
        "description": "Agent talk ratio under 75%",
        "is_critical": False, "weight": 1.0,
        "effective_from": "2025-01-01", "effective_to": None,
        "params": {"max_agent_talk_ratio": 0.75},
    },
]

CRITICAL_CHECK_IDS = sorted({c["check_id"] for c in CHECKS if c["is_critical"]})

# ---------------------------------------------------------------------------
# Rate card
# ---------------------------------------------------------------------------

RATE_CARD = [
    {"plan_id": "PLAN_A", "name": "Aurora Saver", "peak_rate_c_per_kwh": 31.9,
     "daily_supply_c": 98.5, "discount_pct": 0},
    {"plan_id": "PLAN_B", "name": "Aurora Flex", "peak_rate_c_per_kwh": 28.6,
     "daily_supply_c": 104.2, "discount_pct": 5},
    {"plan_id": "PLAN_C", "name": "Aurora Green", "peak_rate_c_per_kwh": 34.1,
     "daily_supply_c": 96.0, "discount_pct": 0},
    {"plan_id": "PLAN_D", "name": "Aurora Fixed 12", "peak_rate_c_per_kwh": 30.2,
     "daily_supply_c": 101.7, "discount_pct": 3},
]
PLANS_BY_ID = {p["plan_id"]: p for p in RATE_CARD}


# ---------------------------------------------------------------------------
# Word / turn synthesis
# ---------------------------------------------------------------------------

def _clean(tok: str) -> str:
    return tok.strip(".,?!:;\"'()").lower()


def speak(text: str, start: float, speaker_num: int, low_conf_idxs=()):
    """Split punctuated display text into word dicts with sequential timestamps.

    Returns (words, end_time).
    """
    tokens = text.split()
    words = []
    t = start
    for i, tok in enumerate(tokens):
        clean = _clean(tok)
        dur = round(random.uniform(0.16, 0.42) + len(clean) * 0.018, 3)
        w_start = round(t, 3)
        w_end = round(w_start + dur, 3)
        if i in low_conf_idxs:
            conf = round(random.uniform(0.30, 0.50), 2)
        else:
            conf = round(random.uniform(0.90, 0.99), 2)
        spk_conf = round(random.uniform(0.28, 0.58), 2)
        words.append({
            "text": clean,
            "punctuated": tok,
            "start": w_start,
            "end": w_end,
            "confidence": conf,
            "speaker": speaker_num,
            "speaker_confidence": spk_conf,
        })
        t = w_end + round(random.uniform(0.03, 0.10), 3)
    return words, t


def raw_tokens(tokens_with_conf, start: float, speaker_num: int):
    """tokens_with_conf: list of (display_text, confidence|None). Used for
    literally-injected tokens (fragmented numbers, card digits) that don't
    come from splitting a natural sentence."""
    words = []
    t = start
    for tok, conf in tokens_with_conf:
        dur = round(random.uniform(0.18, 0.40), 3)
        w_start = round(t, 3)
        w_end = round(w_start + dur, 3)
        c = conf if conf is not None else round(random.uniform(0.90, 0.99), 2)
        spk_conf = round(random.uniform(0.28, 0.58), 2)
        words.append({
            "text": tok.lower(),
            "punctuated": tok,
            "start": w_start,
            "end": w_end,
            "confidence": c,
            "speaker": speaker_num,
            "speaker_confidence": spk_conf,
        })
        t = w_end + round(random.uniform(0.03, 0.10), 3)
    return words, t


def mk_turn(speaker_label: str, words: list) -> dict:
    text = " ".join(w["punctuated"] for w in words)
    start = min(w["start"] for w in words)
    end = max(w["end"] for w in words)
    conf = round(sum(w["confidence"] for w in words) / len(words), 3)
    return {
        "speaker": speaker_label,
        "text": text,
        "start": start,
        "end": end,
        "confidence": conf,
        "words": words,
    }


# ---------------------------------------------------------------------------
# Filler banks (generic phone-sales chatter, reused with light variation)
# ---------------------------------------------------------------------------

OPENERS = [
    (AGENT, "Hi there, thanks for holding, how are you doing today?"),
    (CUSTOMER, "Yeah not bad thanks, bit busy but good."),
]

CALL_INTRO = [
    (AGENT, "Good to hear. So I'm just calling about the energy plan you enquired about."),
    (CUSTOMER, "Oh right, yeah, go ahead."),
]

SMALL_TALK = [
    (AGENT, "Uh, sorry, one sec, let me just pull up your details here."),
    (CUSTOMER, "No worries, take your time."),
    (AGENT, "Okay, got it, thanks for bearing with me."),
    (CUSTOMER, "That's alright."),
]

PLAN_INTRO = [
    (AGENT, "So looking at your usage, we reckon this plan would suit you pretty well."),
    (CUSTOMER, "Okay sounds good."),
    (AGENT, "Great, so let me just run through a few details with you first."),
]

CLOSING = [
    (AGENT, "Alright, I think that covers everything from my end."),
    (CUSTOMER, "Yep sounds good, thanks."),
    (AGENT, "Great, thanks so much for your time today, have a good one."),
    (CUSTOMER, "You too, bye."),
]

MISHEAR_REPEAT = [
    (CUSTOMER, "Sorry, could you say that again?"),
    (AGENT, "No worries, I said the daily supply charge is part of your plan too."),
    (CUSTOMER, "Ah okay got it, thanks."),
]

FALSE_START = [
    (AGENT, "So the, uh, sorry, let me start that again — the plan includes a few things."),
    (CUSTOMER, "Sure."),
]


def add_pair(turns: list, pair: tuple, t: float) -> float:
    label, text = pair
    speaker_num = AGENT_N if label == AGENT else CUSTOMER_N
    words, end = speak(text, t, speaker_num)
    turns.append(mk_turn(label, words))
    return end + round(random.uniform(0.3, 1.1), 3)


def add_bank(turns: list, bank: list, t: float) -> float:
    for pair in bank:
        t = add_pair(turns, pair, t)
    return t


# ---------------------------------------------------------------------------
# Scenario transcript builder
# ---------------------------------------------------------------------------

def resolve_dmo_text(call_date: str) -> str:
    return TXT_DMO_V2 if call_date >= "2026-07-01" else TXT_DMO_V1


def build_transcript(cfg: dict) -> dict:
    turns = []
    t = 0.0

    t = add_bank(turns, OPENERS, t)

    # Disclaimer
    if cfg["disclaimer"] == "skip":
        pass
    else:
        low = cfg.get("disclaimer_low_conf_idx")
        words, t2 = speak(TXT_DISCLAIMER, t, AGENT_N, low_conf_idxs={low} if low is not None else ())
        turns.append(mk_turn(AGENT, words))
        t = t2 + round(random.uniform(0.4, 1.0), 3)

    t = add_bank(turns, CALL_INTRO, t)
    t = add_bank(turns, SMALL_TALK, t)

    # Account holder
    words, t2 = speak(TXT_ACCOUNT_HOLDER, t, AGENT_N)
    turns.append(mk_turn(AGENT, words))
    t = t2 + round(random.uniform(0.3, 0.8), 3)
    t = add_pair(turns, (CUSTOMER, "Yep, that's me."), t)

    # Address confirm
    t = add_pair(turns, (AGENT, "Can you confirm the supply address for me?"), t)
    words, t2 = speak(cfg["address_spoken"], t, CUSTOMER_N)
    turns.append(mk_turn(CUSTOMER, words))
    t = t2 + round(random.uniform(0.3, 0.9), 3)

    # DOB confirm
    t = add_pair(turns, (AGENT, "And just for security, can I get your date of birth?"), t)
    words, t2 = speak(cfg["dob_spoken"], t, CUSTOMER_N)
    turns.append(mk_turn(CUSTOMER, words))
    t = t2 + round(random.uniform(0.3, 0.9), 3)

    # NMI confirm
    t = add_pair(turns, (AGENT, "Great, and I've got your NMI here as well, just confirming that's correct."), t)
    words, t2 = speak(cfg["nmi_spoken"], t, CUSTOMER_N)
    turns.append(mk_turn(CUSTOMER, words))
    t = t2 + round(random.uniform(0.3, 0.9), 3)

    t = add_bank(turns, PLAN_INTRO, t)

    if cfg.get("mishear_repeat"):
        t = add_bank(turns, FALSE_START, t)

    # DMO
    dmo_mode = cfg["dmo"]
    if dmo_mode == "verbatim":
        dmo_text = resolve_dmo_text(cfg["call_date"])
    elif dmo_mode == "paraphrase":
        dmo_text = TXT_DMO_MUMBLE
    elif dmo_mode == "wrong_version":
        dmo_text = TXT_DMO_V2
    else:
        raise ValueError(dmo_mode)
    words, t2 = speak(dmo_text, t, AGENT_N)
    turns.append(mk_turn(AGENT, words))
    t = t2 + round(random.uniform(0.4, 1.0), 3)

    # Card number injection (before rate, mid-call)
    if cfg.get("card_number"):
        t = add_pair(turns, (AGENT, "And how would you like to pay for the connection fee?"), t)
        words, t2 = raw_tokens(
            [("Sure,", None), ("it's", None), ("4111", None), ("1111", None),
             ("1111", None), ("1111", None)],
            t, CUSTOMER_N,
        )
        turns.append(mk_turn(CUSTOMER, words))
        t = t2 + round(random.uniform(0.4, 1.0), 3)

    # Peak rate quote
    t = add_pair(turns, (AGENT, "So your peak usage rate on this plan works out to"), t)
    rate_mode = cfg["rate_mode"]
    if rate_mode == "normal":
        words, t2 = speak(cfg["rate_spoken"] + ".", t, AGENT_N)
        turns.append(mk_turn(AGENT, words))
        t = t2
    elif rate_mode == "fragmented_ok":
        words, t2 = raw_tokens(
            [("31", 0.93), ("percent", 0.71), ("9¢", 0.68), ("per", 0.95),
             ("kilowatt", 0.92), ("hour.", 0.94)],
            t, AGENT_N,
        )
        turns.append(mk_turn(AGENT, words))
        t = t2
    elif rate_mode == "fragmented_garbled":
        words, t2 = raw_tokens(
            [("thirty", 0.55), ("one", 0.41), ("ish", 0.33), ("cents", 0.58),
             ("or", 0.44), ("something", 0.39)],
            t, AGENT_N,
        )
        turns.append(mk_turn(AGENT, words))
        t = t2
    else:
        raise ValueError(rate_mode)
    t = t + round(random.uniform(0.3, 0.9), 3)

    # Dead air injection right after the rate beat
    if cfg.get("dead_air_s"):
        t = t + cfg["dead_air_s"]

    # Daily supply charge
    t = add_pair(turns, (AGENT, "And the daily supply charge is"), t)
    words, t2 = speak(cfg["daily_supply_spoken"] + ".", t, AGENT_N)
    turns.append(mk_turn(AGENT, words))
    t = t2 + round(random.uniform(0.3, 0.8), 3)
    t = add_pair(turns, (CUSTOMER, "Okay that sounds fine."), t)

    if cfg.get("mishear_repeat"):
        t = add_bank(turns, MISHEAR_REPEAT, t)

    # Email confirm
    t = add_pair(turns, (AGENT, "Can I just read back your email to confirm we've got it right?"), t)
    words, t2 = speak(cfg["email_spoken"], t, AGENT_N)
    turns.append(mk_turn(AGENT, words))
    t = t2 + round(random.uniform(0.3, 0.8), 3)
    t = add_pair(turns, (CUSTOMER, "Yep that's right."), t)

    # Cooling off
    low = cfg.get("cooling_off_low_conf_idx")
    words, t2 = speak(TXT_COOLING_OFF, t, AGENT_N, low_conf_idxs={low} if low is not None else ())
    turns.append(mk_turn(AGENT, words))
    t = t2 + round(random.uniform(0.4, 1.0), 3)

    # Terms
    words, t2 = speak(TXT_TERMS, t, AGENT_N)
    turns.append(mk_turn(AGENT, words))
    t = t2 + round(random.uniform(0.3, 0.8), 3)

    # Heavy crosstalk block (lead 11 only)
    if cfg.get("interruptions", 0) > 0:
        for i in range(cfg["interruptions"]):
            speaker_label = CUSTOMER if i % 2 == 0 else AGENT
            speaker_num = CUSTOMER_N if i % 2 == 0 else AGENT_N
            prev_end = turns[-1]["end"]  # overlap guaranteed relative to the actual previous turn
            overlap_start = round(max(0.0, prev_end - random.uniform(0.3, 1.0)), 3)
            words, t2 = speak("Sorry, sorry, can I just, hang on, let me just say something here.",
                               overlap_start, speaker_num)
            turns.append(mk_turn(speaker_label, words))
            t = t2 + round(random.uniform(0.1, 0.4), 3)

    t = add_bank(turns, CLOSING, t)

    # Deliberately out-of-order timestamp pair, injected mid-turn. Mirrors
    # the real observed anomaly (one word ending at 14.24, the next starting
    # at 13.515 -- a ~0.725s local inversion) but applied as a relative
    # offset wherever the chosen turn naturally falls, not the literal
    # absolute values, and each word's own start < end stays valid -- only
    # the cross-word sequence inverts. Turn-level start/end are re-derived
    # from min/max so the turn itself stays well-formed.
    if cfg.get("out_of_order_pair"):
        for turn in turns:
            if turn["speaker"] == AGENT and len(turn["words"]) >= 4:
                w0, w1 = turn["words"][2], turn["words"][3]
                w1_dur = round(w1["end"] - w1["start"], 3)
                new_w0_end = round(w0["end"] + 0.1, 3)
                new_w1_start = round(new_w0_end - 0.725, 3)
                w0["end"] = new_w0_end
                w1["start"] = new_w1_start
                w1["end"] = round(new_w1_start + w1_dur, 3)
                turn["start"] = min(w["start"] for w in turn["words"])
                turn["end"] = max(w["end"] for w in turn["words"])
                break

    audio_duration = round(max(w["end"] for turn in turns for w in turn["words"]) + 2.0, 1)

    return {
        "lead_id": cfg["lead_id"],
        "source": "synthetic",
        "has_word_timings": True,
        "has_speakers": True,
        "audio_duration": audio_duration,
        "turns": turns,
    }


# ---------------------------------------------------------------------------
# Lead scenarios
# ---------------------------------------------------------------------------

SCENARIOS = [
    {  # 1 — worked example
        "lead_id": "LEAD_3613790", "call_date": "2026-09-02",
        "agent_id": "AGT_A", "team_lead_id": "TL_1", "campaign": "affiliate",
        "plan_id": "PLAN_A",
        "crm": {"email": "j.smith@example.com",
                "supply_address": "12 Rundle Street, Adelaide SA 5000",
                "dob": "1984-03-17", "nmi": "2001234567",
                "fuel_type": "electricity", "concession": False,
                "life_support": False, "move_in_date": "2026-09-15"},
        "disclaimer": "verbatim", "dmo": "verbatim",
        "address_spoken": "Yep, twelve Rundle Street, Adelaide, South Australia, 5000.",
        "dob_spoken": "The seventeenth of March, nineteen eighty four.",
        "nmi_spoken": "2001234567",
        "rate_mode": "normal", "rate_spoken": "twenty eight point six cents per kilowatt hour",
        "daily_supply_spoken": "ninety eight point five cents a day",
        "email_spoken": "J dot smith at exampel dot com, is that right?",
        "cooling_off_low_conf_idx": 12,
        "dead_air_s": 47.0,
        "out_of_order_pair": True,
        "notes": "rate mismatch (said 28.6, plan is PLAN_A=31.9), email typo, 47s dead air, "
                 "one low-confidence word in cooling-off span, one out-of-order timestamp pair",
        "expected_gate": "HELD",
        "expected_critical": {
            "CHK_A_DISCLAIMER": "PASS", "CHK_A_ACCOUNT_HOLDER": "PASS",
            "CHK_A_DMO": "PASS", "CHK_A_COOLING_OFF": "LOW_CONFIDENCE",
            "CHK_B_PEAK_RATE": "FAIL", "CHK_B_DAILY_SUPPLY": "PASS",
            "CHK_B_EMAIL": "FAIL", "CHK_B_ADDRESS": "PASS",
            "CHK_B_DOB": "PASS", "CHK_B_NMI": "PASS",
        },
    },
    {  # 2 — fully clean
        "lead_id": "LEAD_3613791", "call_date": "2026-09-05",
        "agent_id": "AGT_B", "team_lead_id": "TL_1", "campaign": "owned_site",
        "plan_id": "PLAN_C",
        "crm": {"email": "a.nguyen@example.com",
                "supply_address": "44 Grote Street, Adelaide SA 5000",
                "dob": "1991-11-02", "nmi": "2004455667",
                "fuel_type": "electricity", "concession": False,
                "life_support": False, "move_in_date": "2026-09-20"},
        "disclaimer": "verbatim", "dmo": "verbatim",
        "address_spoken": "Sure, forty four Grote Street, Adelaide, South Australia, 5000.",
        "dob_spoken": "The second of November, nineteen ninety one.",
        "nmi_spoken": "2004455667",
        "rate_mode": "normal", "rate_spoken": "thirty four point one cents per kilowatt hour",
        "daily_supply_spoken": "ninety six cents a day",
        "email_spoken": "A dot nguyen at example dot com, is that right?",
        "mishear_repeat": True,
        "notes": "fully clean, all green, high confidence throughout",
        "expected_gate": "AUTO_SUBMIT",
        "expected_critical": {cid: "PASS" for cid in CRITICAL_CHECK_IDS},
    },
    {  # 3 — clean and in the deterministic 5% sample
        "lead_id": "LEAD_3613800", "call_date": "2026-09-06",
        "agent_id": "AGT_C", "team_lead_id": "TL_2", "campaign": "paid_search",
        "plan_id": "PLAN_D",
        "crm": {"email": "r.patel@example.com",
                "supply_address": "9 Currie Street, Adelaide SA 5000",
                "dob": "1979-02-14", "nmi": "2007788990",
                "fuel_type": "electricity", "concession": False,
                "life_support": False, "move_in_date": "2026-09-25"},
        "disclaimer": "verbatim", "dmo": "verbatim",
        "address_spoken": "Yes, nine Currie Street, Adelaide, South Australia, 5000.",
        "dob_spoken": "The fourteenth of February, nineteen seventy nine.",
        "nmi_spoken": "2007788990",
        "rate_mode": "normal", "rate_spoken": "thirty point two cents per kilowatt hour",
        "daily_supply_spoken": "one hundred and one point seven cents a day",
        "email_spoken": "R dot patel at example dot com, is that right?",
        "notes": "clean and lands in the deterministic 5% sample bucket",
        "expected_gate": "AUTO_SUBMIT", "expected_sampled": True,
        "expected_critical": {cid: "PASS" for cid in CRITICAL_CHECK_IDS},
    },
    {  # 4 — mumbled DMO
        "lead_id": "LEAD_3613792", "call_date": "2026-09-07",
        "agent_id": "AGT_D", "team_lead_id": "TL_2", "campaign": "inbound",
        "plan_id": "PLAN_B",
        "crm": {"email": "m.owusu@example.com",
                "supply_address": "3 King William Road, Adelaide SA 5000",
                "dob": "1988-08-08", "nmi": "2003322110",
                "fuel_type": "electricity", "concession": False,
                "life_support": False, "move_in_date": "2026-09-18"},
        "disclaimer": "verbatim", "dmo": "paraphrase",
        "address_spoken": "Three King William Road, Adelaide, South Australia, 5000.",
        "dob_spoken": "The eighth of August, nineteen eighty eight.",
        "nmi_spoken": "2003322110",
        "rate_mode": "normal", "rate_spoken": "twenty eight point six cents per kilowatt hour",
        "daily_supply_spoken": "one hundred and four point two cents a day",
        "email_spoken": "M dot owusu at example dot com, is that right?",
        "notes": "DMO line paraphrased/mumbled, ~0.72-0.76 similarity -> LOW_CONFIDENCE",
        "expected_gate": "QA_REVIEW",
        "expected_critical": {
            **{cid: "PASS" for cid in CRITICAL_CHECK_IDS},
            "CHK_A_DMO": "LOW_CONFIDENCE",
        },
    },
    {  # 5 — disclaimer never read
        "lead_id": "LEAD_3613793", "call_date": "2026-09-08",
        "agent_id": "AGT_A", "team_lead_id": "TL_1", "campaign": "affiliate",
        "plan_id": "PLAN_A",
        "crm": {"email": "s.khan@example.com",
                "supply_address": "77 Hindley Street, Adelaide SA 5000",
                "dob": "1995-05-30", "nmi": "2009911223",
                "fuel_type": "electricity", "concession": False,
                "life_support": False, "move_in_date": "2026-09-22"},
        "disclaimer": "skip", "dmo": "verbatim",
        "address_spoken": "Seventy seven Hindley Street, Adelaide, South Australia, 5000.",
        "dob_spoken": "The thirtieth of May, nineteen ninety five.",
        "nmi_spoken": "2009911223",
        "rate_mode": "normal", "rate_spoken": "thirty one point nine cents per kilowatt hour",
        "daily_supply_spoken": "ninety eight point five cents a day",
        "email_spoken": "S dot khan at example dot com, is that right?",
        "notes": "recording disclaimer never read -> critical FAIL",
        "expected_gate": "HELD",
        "expected_critical": {
            **{cid: "PASS" for cid in CRITICAL_CHECK_IDS},
            "CHK_A_DISCLAIMER": "FAIL",
        },
    },
    {  # 6 — old call, resolves DMO v1, passes
        "lead_id": "LEAD_3613794", "call_date": "2026-05-10",
        "agent_id": "AGT_B", "team_lead_id": "TL_1", "campaign": "owned_site",
        "plan_id": "PLAN_C",
        "crm": {"email": "l.tran@example.com",
                "supply_address": "21 Flinders Street, Adelaide SA 5000",
                "dob": "1982-12-01", "nmi": "2002233445",
                "fuel_type": "electricity", "concession": False,
                "life_support": False, "move_in_date": "2026-05-20"},
        "disclaimer": "verbatim", "dmo": "verbatim",
        "address_spoken": "Twenty one Flinders Street, Adelaide, South Australia, 5000.",
        "dob_spoken": "The first of December, nineteen eighty two.",
        "nmi_spoken": "2002233445",
        "rate_mode": "normal", "rate_spoken": "thirty four point one cents per kilowatt hour",
        "daily_supply_spoken": "ninety six cents a day",
        "email_spoken": "L dot tran at example dot com, is that right?",
        "notes": "old call before DMO cutover, reads v1 wording verbatim -> resolves v1, PASS",
        "expected_gate": "AUTO_SUBMIT",
        "expected_critical": {cid: "PASS" for cid in CRITICAL_CHECK_IDS},
    },
    {  # 7 — old call, reads new wording, fails v1
        "lead_id": "LEAD_3613795", "call_date": "2026-03-01",
        "agent_id": "AGT_C", "team_lead_id": "TL_2", "campaign": "paid_search",
        "plan_id": "PLAN_C",
        "crm": {"email": "d.wilson@example.com",
                "supply_address": "5 North Terrace, Adelaide SA 5000",
                "dob": "1975-07-19", "nmi": "2005566778",
                "fuel_type": "electricity", "concession": False,
                "life_support": False, "move_in_date": "2026-03-12"},
        "disclaimer": "verbatim", "dmo": "wrong_version",
        "address_spoken": "Five North Terrace, Adelaide, South Australia, 5000.",
        "dob_spoken": "The nineteenth of July, nineteen seventy five.",
        "nmi_spoken": "2005566778",
        "rate_mode": "normal", "rate_spoken": "thirty four point one cents per kilowatt hour",
        "daily_supply_spoken": "ninety six cents a day",
        "email_spoken": "D dot wilson at example dot com, is that right?",
        "notes": "old call, agent reads the not-yet-live v2 DMO wording -> fails against v1",
        "expected_gate": "HELD",
        "expected_critical": {
            **{cid: "PASS" for cid in CRITICAL_CHECK_IDS},
            "CHK_A_DMO": "FAIL",
        },
    },
    {  # 8 — card number spoken mid-call
        "lead_id": "LEAD_3613796", "call_date": "2026-09-09",
        "agent_id": "AGT_D", "team_lead_id": "TL_2", "campaign": "inbound",
        "plan_id": "PLAN_D",
        "crm": {"email": "p.jones@example.com",
                "supply_address": "60 Wakefield Street, Adelaide SA 5000",
                "dob": "1993-01-25", "nmi": "2008877665",
                "fuel_type": "electricity", "concession": False,
                "life_support": False, "move_in_date": "2026-09-19"},
        "disclaimer": "verbatim", "dmo": "verbatim", "card_number": True,
        "address_spoken": "Sixty Wakefield Street, Adelaide, South Australia, 5000.",
        "dob_spoken": "The twenty fifth of January, nineteen ninety three.",
        "nmi_spoken": "2008877665",
        "rate_mode": "normal", "rate_spoken": "thirty point two cents per kilowatt hour",
        "daily_supply_spoken": "one hundred and one point seven cents a day",
        "email_spoken": "P dot jones at example dot com, is that right?",
        "notes": "card number spoken mid-call -> guardrail HELD (P4 regex, not a scored check)",
        "expected_gate": "HELD",
        "expected_critical": {cid: "PASS" for cid in CRITICAL_CHECK_IDS},
    },
    {  # 9 — address St vs Street, must normalise to PASS
        "lead_id": "LEAD_3613797", "call_date": "2026-09-10",
        "agent_id": "AGT_A", "team_lead_id": "TL_1", "campaign": "affiliate",
        "plan_id": "PLAN_A",
        "crm": {"email": "e.chen@example.com",
                "supply_address": "12 Rundle Street, Adelaide SA 5000",
                "dob": "1986-04-04", "nmi": "2001199887",
                "fuel_type": "electricity", "concession": False,
                "life_support": False, "move_in_date": "2026-09-21"},
        "disclaimer": "verbatim", "dmo": "verbatim",
        "address_spoken": "Yep, that's twelve Rundle St, Adelaide, South Australia, 5000.",
        "dob_spoken": "The fourth of April, nineteen eighty six.",
        "nmi_spoken": "2001199887",
        "rate_mode": "normal", "rate_spoken": "thirty one point nine cents per kilowatt hour",
        "daily_supply_spoken": "ninety eight point five cents a day",
        "email_spoken": "E dot chen at example dot com, is that right?",
        "notes": "address spoken as 'St' vs CRM 'Street' -> must normalise, not string-mismatch",
        "expected_gate": "AUTO_SUBMIT",
        "expected_critical": {cid: "PASS" for cid in CRITICAL_CHECK_IDS},
    },
    {  # 10 — DOB mismatch
        "lead_id": "LEAD_3613798", "call_date": "2026-09-11",
        "agent_id": "AGT_B", "team_lead_id": "TL_1", "campaign": "owned_site",
        "plan_id": "PLAN_B",
        "crm": {"email": "h.oconnor@example.com",
                "supply_address": "88 Pulteney Street, Adelaide SA 5000",
                "dob": "1990-06-21", "nmi": "2006611992",
                "fuel_type": "electricity", "concession": False,
                "life_support": False, "move_in_date": "2026-09-23"},
        "disclaimer": "verbatim", "dmo": "verbatim",
        "address_spoken": "Eighty eight Pulteney Street, Adelaide, South Australia, 5000.",
        "dob_spoken": "The twenty first of June, nineteen ninety two.",
        "nmi_spoken": "2006611992",
        "rate_mode": "normal", "rate_spoken": "twenty eight point six cents per kilowatt hour",
        "daily_supply_spoken": "one hundred and four point two cents a day",
        "email_spoken": "H dot oconnor at example dot com, is that right?",
        "notes": "DOB spoken as 1992, CRM says 1990 -> clear mismatch",
        "expected_gate": "HELD",
        "expected_critical": {
            **{cid: "PASS" for cid in CRITICAL_CHECK_IDS},
            "CHK_B_DOB": "FAIL",
        },
    },
    {  # 11 — heavy crosstalk, non-critical only
        "lead_id": "LEAD_3613799", "call_date": "2026-09-12",
        "agent_id": "AGT_C", "team_lead_id": "TL_2", "campaign": "paid_search",
        "plan_id": "PLAN_C",
        "crm": {"email": "f.dimitriou@example.com",
                "supply_address": "15 Gouger Street, Adelaide SA 5000",
                "dob": "1984-10-10", "nmi": "2004433221",
                "fuel_type": "electricity", "concession": False,
                "life_support": False, "move_in_date": "2026-09-24"},
        "disclaimer": "verbatim", "dmo": "verbatim", "interruptions": 9,
        "address_spoken": "Fifteen Gouger Street, Adelaide, South Australia, 5000.",
        "dob_spoken": "The tenth of October, nineteen eighty four.",
        "nmi_spoken": "2004433221",
        "rate_mode": "normal", "rate_spoken": "thirty four point one cents per kilowatt hour",
        "daily_supply_spoken": "ninety six cents a day",
        "email_spoken": "F dot dimitriou at example dot com, is that right?",
        "notes": "9 overlapping turns, non-critical CHK_C_INTERRUPTIONS fails, gate unaffected",
        "expected_gate": "AUTO_SUBMIT",
        "expected_critical": {cid: "PASS" for cid in CRITICAL_CHECK_IDS},
    },
    {  # 12 — correct rate, wrong plan
        "lead_id": "LEAD_3613801", "call_date": "2026-09-13",
        "agent_id": "AGT_D", "team_lead_id": "TL_2", "campaign": "inbound",
        "plan_id": "PLAN_A",
        "crm": {"email": "b.singh@example.com",
                "supply_address": "40 Angas Street, Adelaide SA 5000",
                "dob": "1980-09-09", "nmi": "2005500112",
                "fuel_type": "electricity", "concession": False,
                "life_support": False, "move_in_date": "2026-09-26"},
        "disclaimer": "verbatim", "dmo": "verbatim",
        "address_spoken": "Forty Angas Street, Adelaide, South Australia, 5000.",
        "dob_spoken": "The ninth of September, nineteen eighty.",
        "nmi_spoken": "2005500112",
        "rate_mode": "normal", "rate_spoken": "twenty eight point six cents per kilowatt hour",
        "daily_supply_spoken": "ninety eight point five cents a day",
        "email_spoken": "B dot singh at example dot com, is that right?",
        "notes": "rate quoted correctly (28.6) but for PLAN_B, not the lead's actual PLAN_A (31.9)",
        "expected_gate": "HELD",
        "expected_critical": {
            **{cid: "PASS" for cid in CRITICAL_CHECK_IDS},
            "CHK_B_PEAK_RATE": "FAIL",
        },
    },
    {  # 13 — fragmented rate, reassembles cleanly
        "lead_id": "LEAD_3613802", "call_date": "2026-09-14",
        "agent_id": "AGT_A", "team_lead_id": "TL_1", "campaign": "affiliate",
        "plan_id": "PLAN_A",
        "crm": {"email": "k.morris@example.com",
                "supply_address": "18 South Terrace, Adelaide SA 5000",
                "dob": "1987-02-17", "nmi": "2001122334",
                "fuel_type": "electricity", "concession": False,
                "life_support": False, "move_in_date": "2026-09-27"},
        "disclaimer": "verbatim", "dmo": "verbatim",
        "address_spoken": "Eighteen South Terrace, Adelaide, South Australia, 5000.",
        "dob_spoken": "The seventeenth of February, nineteen eighty seven.",
        "nmi_spoken": "2001122334",
        "rate_mode": "fragmented_ok",
        "daily_supply_spoken": "ninety eight point five cents a day",
        "email_spoken": "K dot morris at example dot com, is that right?",
        "notes": "rate fragments as '31'/'percent'/'9¢' (real observed Deepgram quirk) -> "
                 "reassembles to 31.9, matches PLAN_A",
        "expected_gate": "AUTO_SUBMIT",
        "expected_critical": {cid: "PASS" for cid in CRITICAL_CHECK_IDS},
    },
    {  # 14 — fragmented rate, unreassemblable
        "lead_id": "LEAD_3613803", "call_date": "2026-09-15",
        "agent_id": "AGT_B", "team_lead_id": "TL_1", "campaign": "owned_site",
        "plan_id": "PLAN_B",
        "crm": {"email": "n.papadopoulos@example.com",
                "supply_address": "27 Waymouth Street, Adelaide SA 5000",
                "dob": "1992-03-03", "nmi": "2003344556",
                "fuel_type": "electricity", "concession": False,
                "life_support": False, "move_in_date": "2026-09-28"},
        "disclaimer": "verbatim", "dmo": "verbatim",
        "address_spoken": "Twenty seven Waymouth Street, Adelaide, South Australia, 5000.",
        "dob_spoken": "The third of March, nineteen ninety two.",
        "nmi_spoken": "2003344556",
        "rate_mode": "fragmented_garbled",
        "daily_supply_spoken": "one hundred and four point two cents a day",
        "email_spoken": "N dot papadopoulos at example dot com, is that right?",
        "notes": "rate tokens too garbled to reassemble confidently -> LOW_CONFIDENCE",
        "expected_gate": "QA_REVIEW",
        "expected_critical": {
            **{cid: "PASS" for cid in CRITICAL_CHECK_IDS},
            "CHK_B_PEAK_RATE": "LOW_CONFIDENCE",
        },
    },
]

LEAD_ID_ORDER = [s["lead_id"] for s in SCENARIOS]
assert len(LEAD_ID_ORDER) == 14
assert len(set(LEAD_ID_ORDER)) == 14


def is_sampled(lead_id: str, rate_pct: int = 5) -> bool:
    h = hashlib.md5(lead_id.encode()).hexdigest()
    return int(h, 16) % 100 < rate_pct


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def write_checks():
    write_json(SYN_DIR / "checks_retailer1.json", {
        "retailer_id": RETAILER_ID,
        "retailer_name": RETAILER_NAME,
        "checks": CHECKS,
    })


def write_rate_card():
    write_json(SYN_DIR / "rate_card.json", RATE_CARD)


def write_leads_and_transcripts():
    leads = []
    transcripts = {}
    for cfg in SCENARIOS:
        transcript = build_transcript(cfg)
        transcripts[cfg["lead_id"]] = transcript
        write_json(TRANSCRIPTS_DIR / f"{cfg['lead_id']}.json", transcript)

        leads.append({
            "lead_id": cfg["lead_id"],
            "retailer_id": RETAILER_ID,
            "call_date": cfg["call_date"],
            "agent_id": cfg["agent_id"],
            "team_lead_id": cfg["team_lead_id"],
            "campaign": cfg["campaign"],
            "last_completed_step": "plan_selection",
            "recording_path": f"data/synthetic/audio/{cfg['lead_id']}.mp3",
            "plan_id": cfg["plan_id"],
            "crm_fields": cfg["crm"],
        })
    write_json(SYN_DIR / "leads.json", leads)
    return transcripts


def write_lead_nots():
    """Plain-text, no-timings transcript for the worked-example call, to
    prove the alignment-fallback path (P6)."""
    cfg = SCENARIOS[0]
    transcript = build_transcript(cfg)
    lines = [t["text"] for t in transcript["turns"]]
    path = TRANSCRIPTS_DIR / "LEAD_NOTS.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write(" ".join(lines))
        f.write("\n")


def write_auditor_labels():
    labels = [
        {"lead_id": "LEAD_3613790", "check_id": "CHK_B_PEAK_RATE", "status": "FAIL", "auditor_id": "AUD_1"},
        {"lead_id": "LEAD_3613790", "check_id": "CHK_A_DISCLAIMER", "status": "PASS", "auditor_id": "AUD_1"},
        # Deliberate disagreement: the human auditor passed the disclaimer
        # check on a call where it was never actually read.
        {"lead_id": "LEAD_3613793", "check_id": "CHK_A_DISCLAIMER", "status": "PASS", "auditor_id": "AUD_2"},
        {"lead_id": "LEAD_3613794", "check_id": "CHK_A_DMO", "status": "PASS", "auditor_id": "AUD_1"},
        {"lead_id": "LEAD_3613797", "check_id": "CHK_B_ADDRESS", "status": "PASS", "auditor_id": "AUD_2"},
        {"lead_id": "LEAD_3613798", "check_id": "CHK_B_DOB", "status": "FAIL", "auditor_id": "AUD_1"},
        {"lead_id": "LEAD_3613801", "check_id": "CHK_B_PEAK_RATE", "status": "FAIL", "auditor_id": "AUD_2"},
    ]
    write_json(SYN_DIR / "auditor_labels.json", labels)


def write_expected_outcomes():
    outcomes = []
    for cfg in SCENARIOS:
        outcomes.append({
            "lead_id": cfg["lead_id"],
            "gate_status": cfg["expected_gate"],
            "sampled": cfg.get("expected_sampled", is_sampled(cfg["lead_id"])),
            "critical_checks": cfg["expected_critical"],
            "notes": cfg["notes"],
        })
    write_json(SYN_DIR / "expected_outcomes.json", outcomes)


def write_payload_shape():
    write_json(SYN_DIR / "payload_shape.json", {
        "lead_id": "LEAD_3613790", "retailer_id": RETAILER_ID,
        "scored_at": "2026-09-19T14:02:11Z", "gate_status": "HELD",
        "score_with_fatals": 0.0, "score_without_fatals": 0.82,
        "check_library_version": "2026-07-01",
        "results": [
            {
                "check_id": "CHK_B_PEAK_RATE", "check_version": 1,
                "status": "FAIL", "confidence": 0.94, "is_critical": True,
                "evidence": {
                    "transcript_line": "so your peak usage rate on this plan works out to "
                                        "twenty eight point six cents per kilowatt hour",
                    "start_ts": 40.0, "end_ts": 46.5, "asr_confidence": 0.91,
                },
                "expected": "31.9", "actual": "28.6",
            },
        ],
    })


def write_audio(transcripts: dict):
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    for lead_id, transcript in transcripts.items():
        duration_ms = int(transcript["audio_duration"] * 1000)
        segment = AudioSegment.silent(duration=duration_ms, frame_rate=8000)
        segment.export(AUDIO_DIR / f"{lead_id}.mp3", format="mp3", bitrate="32k")


def main():
    random.seed(42)
    write_checks()
    write_rate_card()
    transcripts = write_leads_and_transcripts()
    write_lead_nots()
    write_auditor_labels()
    write_expected_outcomes()
    write_payload_shape()
    write_audio(transcripts)

    print(f"Wrote {len(CHECKS)} check rows ({len(CRITICAL_CHECK_IDS)} unique critical check ids)")
    print(f"Wrote {len(SCENARIOS)} leads + transcripts + audio placeholders")


if __name__ == "__main__":
    main()

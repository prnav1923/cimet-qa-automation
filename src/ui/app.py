"""Review UI. Streamlit. Master-detail: pick a lead (sidebar or a queue tab),
see its scorecard, click a check, see the transcript evidence immediately.

No dashboards, charts, accuracy metrics, or audio playback here -- those are
explicitly out of scope for this view.
"""

import sys
from pathlib import Path

# `streamlit run src/ui/app.py` does not put the repo root on sys.path (only
# the script's own directory), so the `from src...` imports below fail with
# ModuleNotFoundError unless we add it ourselves, before those imports run.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st

from src.db import (
    get_connection,
    get_overrides_for_lead,
    init_db,
    insert_check_result,
    insert_decision,
    insert_lead,
    delete_check_results_for_lead,
)
from src.engine import load_all_checks, load_all_leads, resolve_checks, score_check
from src.gate import apply_override, gate, has_card_number, is_sampled, mask_card_numbers
from src.models import CheckResult, Lead, Transcript

STATUS_PILL = {
    "PASS": "🟢 PASS", "FAIL": "🔴 FAIL",
    "LOW_CONFIDENCE": "🟡 LOW_CONFIDENCE", "NOT_APPLICABLE": "⚪ NOT_APPLICABLE",
}
GATE_BADGE = {
    "HELD": "🔴 HELD", "QA_REVIEW": "🟡 QA_REVIEW", "AUTO_SUBMIT": "🟢 AUTO_SUBMIT",
}
NO_CHECKLIST_BADGE = "⚪ NO CHECKLIST"


@st.cache_resource
def get_db_conn():
    init_db()
    return get_connection()


@st.cache_data
def load_checks_and_leads():
    """Both check libraries and both lead sources (synthetic + CIMET's real
    transcript, via data/cimet/leads_cimet.json + checks_cimet.json) --
    exactly what engine.py and gate.py --all score against."""
    return load_all_checks(), load_all_leads()


def score_and_gate(checks: list, lead: Lead, conn) -> tuple[list[CheckResult], object]:
    """Fresh score + gate. No decision (None) when no checks resolve for
    this lead's retailer -- that's a distinct state from a clean
    AUTO_SUBMIT, not the same thing."""
    resolved = resolve_checks(checks, lead.retailer_id, lead.call_date)
    results = [score_check(c, lead, conn) for c in resolved]
    decision = gate(results, lead) if resolved else None
    return results, decision


def persist_lead(conn, lead: Lead, results: list[CheckResult], decision) -> None:
    insert_lead(conn, lead)
    delete_check_results_for_lead(conn, lead.lead_id)
    for r in results:
        insert_check_result(conn, r)
    if decision is not None:
        insert_decision(conn, decision)


def gate_badge(decision) -> str:
    if decision is None:
        return NO_CHECKLIST_BADGE
    badge = GATE_BADGE[decision.gate_status]
    if decision.sampled:
        badge += " 📋"
    return badge


def format_ts(result: CheckResult) -> str:
    if result.start_ts is not None:
        m, s = divmod(int(result.start_ts), 60)
        return f"🎧 {m:02d}:{s:02d}"
    if result.estimated_ts is not None:
        m, s = divmod(int(result.estimated_ts), 60)
        return f"≈{m:02d}:{s:02d} (estimated — no audio supplied)"
    return "—"


def get_context_window(transcript: Transcript, result: CheckResult, pad: int = 2):
    """Turns surrounding the check's evidence instant, plus the index of the
    hit turn within that window. Works for both measured and estimated
    timing, since both live in the same numeric start/end fields on Turn."""
    ts = result.start_ts if result.start_ts is not None else result.estimated_ts
    if ts is None or transcript is None:
        return [], None

    turns = transcript.sorted_turns()
    hit_idx = None
    for i, t in enumerate(turns):
        if t.start <= ts <= t.end:
            hit_idx = i
            break
    if hit_idx is None:
        hit_idx = min(range(len(turns)), key=lambda i: abs(turns[i].start - ts))

    lo, hi = max(0, hit_idx - pad), min(len(turns), hit_idx + pad + 1)
    return turns[lo:hi], hit_idx - lo


def render_evidence(transcript: Transcript, result: CheckResult) -> None:
    if result.status == "NOT_APPLICABLE" and result.start_ts is None and result.estimated_ts is None:
        st.info(f"Not evaluable — {result.detail}")
        return

    window, hit_rel_idx = get_context_window(transcript, result)
    if not window:
        st.info("No transcript evidence available for this check.")
        return

    is_estimated = result.start_ts is None and result.estimated_ts is not None
    if is_estimated:
        st.caption("⚠️ estimated — no audio supplied")

    for i, turn in enumerate(window):
        text = mask_card_numbers(turn.text)
        if i == hit_rel_idx:
            st.markdown(
                f"<div style='background:#fff3b0;color:#111;padding:8px;"
                f"border-radius:4px;margin:2px 0'><b>{turn.speaker}</b> "
                f"({format_ts(result)}): {text}</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"<div style='opacity:0.55;padding:4px 8px'>{turn.speaker}: {text}</div>",
                unsafe_allow_html=True,
            )

    if result.expected is not None or result.actual is not None:
        st.caption(f"expected: {result.expected}  |  actual: {result.actual}")


def render_override_panel(conn, lead: Lead, result: CheckResult) -> None:
    history = [o for o in get_overrides_for_lead(conn, lead.lead_id) if o["check_id"] == result.check_id]
    if history:
        st.caption("Override history:")
        for o in history:
            st.caption(f"— {o['old_status']} → {o['new_status']} by {o['actor']} ({o['reason']})")

    with st.form(key=f"override_{lead.lead_id}_{result.check_id}", clear_on_submit=True):
        new_status = st.selectbox(
            "New status", ["PASS", "FAIL", "LOW_CONFIDENCE", "NOT_APPLICABLE"],
            key=f"status_{lead.lead_id}_{result.check_id}",
        )
        actor = st.text_input("Actor", key=f"actor_{lead.lead_id}_{result.check_id}")
        reason = st.text_area("Reason (mandatory)", key=f"reason_{lead.lead_id}_{result.check_id}")
        if st.form_submit_button("Submit override"):
            try:
                apply_override(conn, lead.lead_id, result.check_id, actor=actor, new_status=new_status, reason=reason)
                st.success("Override logged.")
                # No explicit st.rerun() here: form submission already
                # triggers Streamlit's natural rerun, and calling it again
                # from inside the handler double-executes this block on
                # some runtimes -- confirmed as a real duplicate-row bug
                # during testing, not a hypothetical one.
            except ValueError as e:
                st.error(str(e))


def render_scorecard_row(conn, lead: Lead, result: CheckResult) -> None:
    critical_marker = "🔴 critical" if result.is_critical else "non-critical"
    cols = st.columns([2, 4, 2, 1, 1])
    cols[0].markdown(STATUS_PILL[result.status])
    cols[1].markdown(f"**{result.check_id}** — {result.detail or '(no detail)'}")
    cols[2].markdown(critical_marker)
    cols[3].markdown(f"{result.confidence:.2f}")
    selected = st.session_state.get("selected_check") == (lead.lead_id, result.check_id)
    # No st.rerun() needed: the button click itself is already the rerun,
    # and the evidence panel (rendered further down in this same pass) reads
    # session_state after this assignment -- an extra explicit rerun here
    # would just re-trigger this handler, same risk as the override bug.
    if cols[4].button("Evidence →" if not selected else "● shown", key=f"ev_{lead.lead_id}_{result.check_id}"):
        st.session_state["selected_check"] = (lead.lead_id, result.check_id)

    with st.expander("Override", expanded=False):
        render_override_panel(conn, lead, result)


def render_header(lead: Lead, results: list[CheckResult], decision) -> None:
    st.subheader(lead.lead_id)
    call_date_note = " (placeholder — unknown)" if "call_date" in lead.provenance else ""
    st.caption(f"call date: {lead.call_date}{call_date_note}  |  retailer: {lead.retailer_id}")

    if decision is None:
        st.warning(NO_CHECKLIST_BADGE + " — no check library loaded for this retailer yet.")
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Gate status", GATE_BADGE[decision.gate_status])
    c2.metric("Score (with fatals)", f"{decision.score_with_fatals:.0%}")
    c3.metric("Score (without fatals)", f"{decision.score_without_fatals:.0%}")
    if decision.sampled:
        st.caption("📋 in the 5% QA sample — a copy is queued for review even though this lead auto-submits.")
    st.caption(f"reason: {decision.reason}")

    if has_card_number(lead):
        st.error("🔒 Card-number guardrail triggered — number redacted in every view below.")

    with st.expander("Check versions resolved for this call date"):
        for r in results:
            st.caption(f"{r.check_id} — v{r.check_version}")


def render_lead_detail(conn, checks: list, lead: Lead) -> None:
    results, decision = score_and_gate(checks, lead, conn)
    persist_lead(conn, lead, results, decision)

    render_header(lead, results, decision)
    if not results:
        return

    left, right = st.columns([3, 2])
    with left:
        st.markdown("#### Scorecard")
        for r in results:
            render_scorecard_row(conn, lead, r)

    with right:
        st.markdown("#### Evidence")
        selected = st.session_state.get("selected_check")
        if selected and selected[0] == lead.lead_id:
            result = next((r for r in results if r.check_id == selected[1]), None)
            if result is not None:
                st.caption(f"{result.check_id} — {STATUS_PILL[result.status]}")
                render_evidence(lead.transcript, result)
        else:
            st.info("Click ``Evidence →`` on a check to see the transcript that produced it.")


def main():
    st.set_page_config(page_title="CIMET QA Review", layout="wide")
    conn = get_db_conn()
    checks, leads = load_checks_and_leads()
    st.session_state.setdefault("current_lead_id", None)
    st.session_state.setdefault("selected_check", None)

    # Pre-compute gate badges for the sidebar/tabs. Type B calls are cached
    # by prompt hash (llm_cache), so this only costs real API calls once per
    # lead/check -- reruns after that hit the cache.
    scored = {lead.lead_id: score_and_gate(checks, lead, conn) for lead in leads}
    leads_by_id = {lead.lead_id: lead for lead in leads}

    st.sidebar.header("Leads")
    for lead in leads:
        _, decision = scored[lead.lead_id]
        label = f"{gate_badge(decision)}  {lead.lead_id}"
        if st.sidebar.button(label, key=f"side_{lead.lead_id}", use_container_width=True):
            st.session_state["current_lead_id"] = lead.lead_id
            st.session_state["selected_check"] = None

    st.title("CIMET QA Review")

    tab_tl, tab_qa, tab_sample = st.tabs([
        "TL queue (held)", "QA queue (low confidence)", "QA sample",
    ])

    def _queue_tab(predicate):
        matches = [l for l in leads if predicate(scored[l.lead_id][1])]
        if not matches:
            st.caption("Nothing here.")
        for lead in matches:
            if st.button(f"{gate_badge(scored[lead.lead_id][1])}  {lead.lead_id}", key=f"tab_{lead.lead_id}_{id(predicate)}"):
                st.session_state["current_lead_id"] = lead.lead_id
                st.session_state["selected_check"] = None

    with tab_tl:
        _queue_tab(lambda d: d is not None and d.gate_status == "HELD")
    with tab_qa:
        _queue_tab(lambda d: d is not None and d.gate_status == "QA_REVIEW")
    with tab_sample:
        _queue_tab(lambda d: d is not None and d.gate_status == "AUTO_SUBMIT" and d.sampled)

    st.divider()

    current_id = st.session_state["current_lead_id"]
    if current_id is None:
        st.info("Select a lead from the sidebar or a queue tab above.")
        return

    render_lead_detail(conn, checks, leads_by_id[current_id])


if __name__ == "__main__":
    main()

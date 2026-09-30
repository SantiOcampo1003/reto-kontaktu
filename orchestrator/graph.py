from typing import List, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from orchestrator import business_rules, dates, llm_extraction, order_builder, orders, output, repository


class GraphState(TypedDict, total=False):
    event: dict
    organization_ok: bool
    replay: Optional[dict]
    label: str
    reason: str
    confidence: float
    orders: List[dict]
    should_record_event: bool
    should_record_call_history: bool


def build_graph(connection, config, model):
    organization_id = config["campana"]["organization_id"]

    def check_organization(state):
        return {"organization_ok": state["event"]["organization_id"] == organization_id}

    def route_organization(state):
        return "ok" if state["organization_ok"] else "other_org"

    def reject_organization(state):
        return {
            "label": "no_aplica",
            "reason": "evento de otra organizacion",
            "confidence": 1.0,
            "orders": [],
            "should_record_event": False,
            "should_record_call_history": False,
        }

    def check_idempotency(state):
        event = state["event"]
        return {"replay": repository.find_processed_event(connection, event["idempotency_key"])}

    def route_after_idempotency(state):
        if state["replay"]:
            return "replay"
        return "message" if state["event"]["type"] == "message.received" else "call"

    def handle_replay(state):
        return {
            "label": state["replay"]["label"],
            "reason": "evento reentregado, se repite la decision original",
            "confidence": 1.0,
            "orders": [],
            "should_record_event": False,
            "should_record_call_history": False,
        }

    def handle_message(state):
        event = state["event"]
        contact_id = event["lead"]["contact_id"]
        built_orders = []
        for reminder in repository.pending_reminders(connection, contact_id):
            built_orders.append(orders.cancel_reminder(
                event["event_id"], event["idempotency_key"],
                reminder["reminder_id"], "el lead respondio por whatsapp",
            ))
            repository.cancel_reminder(connection, reminder["reminder_id"])
        return {
            "label": "no_aplica",
            "reason": "mensaje entrante del lead",
            "confidence": 1.0,
            "orders": built_orders,
            "should_record_event": True,
            "should_record_call_history": False,
        }

    def resolve_call(state):
        event = state["event"]
        contact_id = event["lead"]["contact_id"]
        entry_id = event["campaign"]["entry_id"]

        already_dnc = repository.is_on_dnc(connection, contact_id)
        attempts_so_far = repository.count_attempts(connection, contact_id)
        max_attempts = config["reintentos"]["max_intentos"]

        try:
            decision = business_rules.classify_call(event, attempts_so_far, max_attempts)
        except business_rules.NeedsTranscript:
            signals = llm_extraction.extract_signals(event, config, model)
            if repository.is_whatsapp_blocked(connection, contact_id):
                signals.rechaza_whatsapp = True  # N1: un rechazo pasado se queda para siempre
            dropped_calls_so_far = repository.count_dropped_calls(connection, contact_id)
            decision = business_rules.classify_from_signals(signals, dropped_calls_so_far)

        occurred_at = dates.to_madrid(dates.parse_iso(event["occurred_at"]), config)
        status = business_rules.STATUS_BY_LABEL[decision["label"]]

        built_orders = [orders.close_call(
            event["event_id"], event["idempotency_key"], entry_id, status,
            decision["label"], decision["reason"], decision["confidence"],
            event["telephony"]["duration_seconds"],
        )]
        if not already_dnc:  # N2: una baja de una llamada anterior no recibe ninguna orden mas
            built_orders += order_builder.build_action_orders(
                decision["action"], event, decision, occurred_at, config, connection,
            )

        return {
            "label": decision["label"],
            "reason": decision["reason"],
            "confidence": decision["confidence"],
            "orders": built_orders,
            "should_record_event": True,
            "should_record_call_history": True,
        }

    def finalize(state):
        event = state["event"]
        built_orders = state.get("orders", [])
        order_ids = [o["orden_id"] for o in built_orders]

        if state["should_record_event"]:
            repository.record_processed_event(
                connection, event["idempotency_key"], event["event_id"],
                state["label"], order_ids,
            )
        if state["should_record_call_history"]:
            repository.record_call(
                connection, event["lead"]["contact_id"], event["idempotency_key"],
                event["occurred_at"], state["label"],
                {"reason": state["reason"], "confidence": state["confidence"]},
            )

        output.append_orders(built_orders)
        output.append_decision({
            "event_id": event["event_id"],
            "call_id": event.get("telephony", {}).get("call_id"),
            "etiqueta": state["label"],
            "motivo": state["reason"],
            "confianza": state["confidence"],
            "ordenes": order_ids,
        })
        return {}

    graph = StateGraph(GraphState)
    graph.add_node("check_organization", check_organization)
    graph.add_node("reject_organization", reject_organization)
    graph.add_node("check_idempotency", check_idempotency)
    graph.add_node("handle_replay", handle_replay)
    graph.add_node("handle_message", handle_message)
    graph.add_node("resolve_call", resolve_call)
    graph.add_node("finalize", finalize)

    graph.add_edge(START, "check_organization")
    graph.add_conditional_edges("check_organization", route_organization, {
        "ok": "check_idempotency",
        "other_org": "reject_organization",
    })
    graph.add_conditional_edges("check_idempotency", route_after_idempotency, {
        "replay": "handle_replay",
        "message": "handle_message",
        "call": "resolve_call",
    })
    graph.add_edge("reject_organization", "finalize")
    graph.add_edge("handle_replay", "finalize")
    graph.add_edge("handle_message", "finalize")
    graph.add_edge("resolve_call", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile()

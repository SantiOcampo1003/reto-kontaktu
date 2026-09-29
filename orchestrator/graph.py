from datetime import timedelta
from typing import List, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from orchestrator import business_rules, dates, orders, output, repository


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


def build_graph(connection, config):
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
        phone = event["lead"]["phone"]
        call_id = event["telephony"]["call_id"]

        attempts_so_far = repository.count_attempts(connection, contact_id)
        max_attempts = config["reintentos"]["max_intentos"]
        decision = business_rules.classify_call(event, attempts_so_far, max_attempts)

        occurred_at = dates.to_madrid(dates.parse_iso(event["occurred_at"]), config)
        status = business_rules.STATUS_BY_LABEL[decision["label"]]

        built_orders = [orders.close_call(
            event["event_id"], event["idempotency_key"], entry_id, status,
            decision["label"], decision["reason"], decision["confidence"],
            event["telephony"]["duration_seconds"],
        )]

        action = decision["action"]

        if action == "confirm_visit":
            appointment = event["agent_outcome"]["appointment"]
            start = dates.to_madrid(dates.parse_iso(appointment["start_time"]), config)
            margin = config["tareas"]["confirmar_visita_margen_horas"]
            built_orders.append(orders.create_task(
                event["event_id"], event["idempotency_key"], contact_id,
                "confirmar_visita_direccion", "Confirmar direccion de la visita",
                start - timedelta(hours=margin), call_id=call_id,
            ))

        elif action == "retry_general":
            not_before = dates.schedule_after(
                occurred_at, config["reintentos"]["separacion_minima_horas"] * 60, config,
            )
            built_orders.append(orders.schedule_call(
                event["event_id"], event["idempotency_key"], entry_id, phone,
                not_before, decision["reason"],
            ))

        elif action == "retry_busy":
            not_before = dates.schedule_after_range(
                occurred_at,
                config["reintentos"]["ocupado_minutos_min"],
                config["reintentos"]["ocupado_minutos_max"],
                config,
            )
            built_orders.append(orders.schedule_call(
                event["event_id"], event["idempotency_key"], entry_id, phone,
                not_before, decision["reason"],
            ))

        elif action == "backup_channel":
            if not repository.is_whatsapp_blocked(connection, contact_id):
                built_orders.append(orders.send_whatsapp_template(
                    event["event_id"], event["idempotency_key"],
                    event["organization_id"], phone, "primer_toque_respaldo",
                ))

        elif action == "review_task":
            due_at = occurred_at + timedelta(days=config["tareas"]["vencimiento_por_defecto_dias"])
            built_orders.append(orders.create_task(
                event["event_id"], event["idempotency_key"], contact_id,
                "revisar_llamada", "Revisar llamada fuera de catalogo",
                due_at, call_id=call_id, detail=decision["reason"],
            ))

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

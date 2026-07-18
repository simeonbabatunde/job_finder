from langgraph.graph import StateGraph, END
from app.agent.state import AgentState
from app.agent.nodes import parse_resume, search_jobs, analyze_fit, submit_application, apply_browser
from app.services.agent_run_control import (
    CANCELED_STATUS,
    canceled_agent_state,
    is_agent_run_cancel_requested,
)


def is_canceled_state(state: AgentState) -> bool:
    return state.get("application_status") == CANCELED_STATUS


def cancellation_requested(state: AgentState) -> bool:
    return is_canceled_state(state) or is_agent_run_cancel_requested(state.get("agent_run_id"))


def cancelable(node):
    async def wrapped(state: AgentState):
        if cancellation_requested(state):
            return canceled_agent_state(state.get("logs", []))

        result = await node(state)
        logs = result.get("logs", state.get("logs", []))

        if is_agent_run_cancel_requested(state.get("agent_run_id")):
            return {**result, **canceled_agent_state(logs)}

        return result

    return wrapped


def create_graph():
    workflow = StateGraph(AgentState)

    workflow.add_node("parse_resume", cancelable(parse_resume))
    workflow.add_node("search_jobs", cancelable(search_jobs))
    workflow.add_node("analyze_fit", cancelable(analyze_fit))
    workflow.add_node("submit_application", cancelable(submit_application))
    workflow.add_node("apply_browser", cancelable(apply_browser))

    workflow.set_entry_point("parse_resume")
    workflow.add_edge("parse_resume", "search_jobs")
    workflow.add_edge("search_jobs", "analyze_fit")
    workflow.add_edge("analyze_fit", "submit_application")

    def should_continue(state):
        if is_canceled_state(state):
            return END
        if state.get("auto_apply") and state.get("applications_submitted"):
            return "apply_browser"
        return END

    workflow.add_conditional_edges(
        "submit_application",
        should_continue,
        {
            "apply_browser": "apply_browser",
            END: END,
        },
    )

    workflow.add_edge("apply_browser", END)

    return workflow.compile()


agent_graph = create_graph()

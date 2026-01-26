from langgraph.graph import StateGraph, END
from app.agent.state import AgentState
from app.agent.nodes import parse_resume, search_jobs, analyze_fit, submit_application, apply_browser

def create_graph():
    workflow = StateGraph(AgentState)
    
    # Add nodes
    workflow.add_node("parse_resume", parse_resume)
    workflow.add_node("search_jobs", search_jobs)
    workflow.add_node("analyze_fit", analyze_fit)
    workflow.add_node("submit_application", submit_application)
    workflow.add_node("apply_browser", apply_browser)
    
    # Define edges
    workflow.set_entry_point("parse_resume")
    workflow.add_edge("parse_resume", "search_jobs")
    workflow.add_edge("search_jobs", "analyze_fit")
    workflow.add_edge("analyze_fit", "submit_application")
    
    # Decide whether to go to apply_browser or END
    def should_continue(state):
        if state.get("auto_apply") and state.get("applications_submitted"):
            return "apply_browser"
        return END

    workflow.add_conditional_edges(
        "submit_application",
        should_continue,
        {
            "apply_browser": "apply_browser",
            END: END
        }
    )
    
    workflow.add_edge("apply_browser", END)
    
    return workflow.compile()

agent_graph = create_graph()

from langgraph.graph import StateGraph, END
from app.agent.state import AgentState
from app.agent.nodes import parse_resume, search_jobs, analyze_fit, submit_application

def create_graph():
    workflow = StateGraph(AgentState)
    
    # Add nodes
    workflow.add_node("parse_resume", parse_resume)
    workflow.add_node("search_jobs", search_jobs)
    workflow.add_node("analyze_fit", analyze_fit)
    workflow.add_node("submit_application", submit_application)
    
    # Define edges
    # Entry point -> Parse Resume
    workflow.set_entry_point("parse_resume")
    
    # Parse -> Search
    workflow.add_edge("parse_resume", "search_jobs")
    
    # Search -> Analyze
    workflow.add_edge("search_jobs", "analyze_fit")
    
    # Analyze -> Submit (or End)
    # Conditional edge could be added here to loop if we wanted to process all jobs.
    # For now, linear flow.
    workflow.add_edge("analyze_fit", "submit_application")
    
    # Submit -> End
    workflow.add_edge("submit_application", END)
    
    return workflow.compile()

agent_graph = create_graph()

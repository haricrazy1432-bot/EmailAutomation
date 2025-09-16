import os
from typing import TypedDict, Optional
from langgraph.graph import StateGraph, END

# Assuming these files contain the necessary functions
import gmail
import llm_client

# --- LangGraph State Definition ---
# This defines the data structure that the graph nodes will share and update.
class EmailState(TypedDict):
    """Represents the state of the email processing workflow."""
    email: Optional[dict]
    draft: Optional[str]
    validation_status: str
    error: Optional[str]
    rewrite_attempts: int

# --- LangGraph Node Definitions ---
# Each function is a "node" that performs a specific action and updates the state.

def retrieve_node(state: EmailState) -> dict:
    """Retrieves the latest email and initializes the state."""
    print("Retrieving the latest email...")
    email_data = gmail_client.fetch_latest_email()
    if not email_data:
        return {"error": "No new emails found."}
    return {"email": email_data, "validation_status": "pending", "rewrite_attempts": 0}

def draft_node(state: EmailState) -> dict:
    """Generates an initial draft of the email reply using an LLM."""
    if state.get("error"):
        return state
    print("Drafting reply with the agent...")
    draft_content = llm_client.generate_draft(state["email"])
    return {"draft": draft_content}

def validate_node(state: EmailState) -> dict:
    """Validates the drafted email using an LLM or a rule-based check."""
    print("Validating the draft...")
    is_valid = llm_client.validate_draft(state["draft"])
    return {"validation_status": "valid" if is_valid else "invalid"}

def rewrite_node(state: EmailState) -> dict:
    """Rewrites the draft based on validation failure feedback."""
    print("Validation failed, rewriting the draft...")
    new_draft = llm_client.rewrite_draft(state["draft"], "The previous draft failed validation.")
    return {"draft": new_draft, "rewrite_attempts": state.get("rewrite_attempts", 0) + 1}

def send_node(state: EmailState) -> dict:
    """Sends the final, validated email draft."""
    print("Draft approved. Sending email...")
    email_info = state["email"]
    gmail_client.send_email(
        to=email_info["from"],
        subject=f"Re: {email_info['subject']}",
        body=state["draft"]
    )
    return {"status": "Email sent successfully."}

# --- LangGraph Conditional Logic ---
# This function determines the next node based on the current state.
def should_continue(state: EmailState) -> str:
    """Decides the next step in the workflow based on the state."""
    if state.get("error"):
        return END  # Terminate on error
    if state["validation_status"] == "valid":
        return "send"
    if state["rewrite_attempts"] >= 2:
        return "escalate" # End the workflow if max rewrites are reached
    return "rewrite"

# --- Graph Definition and Compilation ---
# 1. Create the graph
workflow = StateGraph(EmailState)

# 2. Add nodes to the graph
workflow.add_node("retrieve", retrieve_node)
workflow.add_node("draft", draft_node)
workflow.add_node("validate", validate_node)
workflow.add_node("rewrite", rewrite_node)
workflow.add_node("send", send_node)

# 3. Define the graph's structure
workflow.set_entry_point("retrieve")
workflow.add_edge("retrieve", "draft")
workflow.add_edge("draft", "validate")
workflow.add_edge("rewrite", "validate")
workflow.add_edge("send", END)

# 4. Add conditional routing from the 'validate' node
workflow.add_conditional_edges(
    "validate",
    should_continue,
    {"send": "send", "rewrite": "rewrite", "escalate": END}
)

# 5. Compile the graph into a runnable application
email_agent_app = workflow.compile()

# --- Main Execution Block ---
if __name__ == "__main__":
    print("Starting the email agent workflow...")
    # Invoke the graph with an initial state
    final_state = email_agent_app.invoke({})
    
    print("\n--- Workflow Summary ---")
    if final_state.get("error"):
        print(f"Workflow failed: {final_state['error']}")
    else:
        print(f"Status: {final_state.get('status', 'Completed')}")
        if final_state.get("draft"):
            print(f"Final Draft: \n---\n{final_state['draft']}\n---")
    print("\n--- Final State ---")
    print(final_state)
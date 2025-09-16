import os
import fitz  # PyMuPDF
import chromadb
from sentence_transformers import SentenceTransformer
from fastapi import FastAPI, UploadFile, Form
from pydantic import BaseModel
from typing import TypedDict, Optional
from langgraph.graph import StateGraph, END

# Assuming these files exist in your project
from gmail import fetch_latest_email, send_email
from llm_client import generate_draft, validate_draft, rewrite_draft

# Initialize FastAPI
app = FastAPI(title="RAG Agent API with Chroma")

# --- Chroma + Embeddings ---
chroma_client = chromadb.PersistentClient(path="chroma_db")
embedder = SentenceTransformer("all-MiniLM-L6-v2")

def file_to_text(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        doc = fitz.open(file_path)
        return "\n".join([page.get_text() for page in doc])
    elif ext in [".md", ".txt"]:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    else:
        raise ValueError(f"Unsupported file type: {ext}")

def get_collection(name: str):
    return chroma_client.get_or_create_collection(name)

# --- RAG API Endpoints ---
@app.get("/")
def root():
    return {"message": "Welcome to the RAG API! Server is running 🚀"}

class QueryRequest(BaseModel):
    query: str
    collection: str

@app.post("/index")
async def index_file(file: UploadFile, collection: str = Form(...)):
    file_path = os.path.join("uploads", file.filename)
    os.makedirs("uploads", exist_ok=True)
    with open(file_path, "wb") as f:
        f.write(await file.read())
    text = file_to_text(file_path)
    collection_db = get_collection(collection)
    chunks = [text[i:i+500] for i in range(0, len(text), 500)]
    embeddings = embedder.encode(chunks).tolist()
    for idx, chunk in enumerate(chunks):
        collection_db.add(documents=[chunk], embeddings=[embeddings[idx]], ids=[f"{file.filename}_{idx}"])
    return {"status": "success", "chunks_indexed": len(chunks)}

@app.post("/query")
async def query_collection(request: QueryRequest):
    collection_db = get_collection(request.collection)
    query_embedding = embedder.encode([request.query]).tolist()[0]
    results = collection_db.query(query_embeddings=[query_embedding], n_results=3)
    return {"query": request.query, "results": results["documents"]}

# --- LangGraph Agent Integration ---
class EmailState(TypedDict):
    email: Optional[dict]
    draft: Optional[str]
    validation_status: str
    error: Optional[str]
    rewrite_attempts: int

def retrieve_node(state: EmailState) -> dict:
    email = fetch_latest_email()
    if not email:
        return {"error": "No new emails found."}
    return {"email": email, "validation_status": "pending", "rewrite_attempts": 0}

def draft_node(state: EmailState) -> dict:
    if "error" in state:
        return state
    draft_content = generate_draft(state["email"])
    return {"draft": draft_content}

def validate_node(state: EmailState) -> dict:
    is_valid = validate_draft(state["draft"])
    return {"validation_status": "valid" if is_valid else "invalid"}

def rewrite_node(state: EmailState) -> dict:
    new_draft = rewrite_draft(state["draft"], "Validation failed.")
    return {"draft": new_draft, "rewrite_attempts": state.get("rewrite_attempts", 0) + 1}

def send_node(state: EmailState) -> dict:
    send_email(to=state["email"]["from"], subject=f"Re: {state['email']['subject']}", body=state["draft"])
    return {"status": "Email sent successfully."}

def should_continue(state: EmailState) -> str:
    if state.get("error"):
        return END
    if state["validation_status"] == "valid":
        return "send"
    if state["rewrite_attempts"] >= 2:
        return "escalate"
    return "rewrite"

workflow = StateGraph(EmailState)
workflow.add_node("retrieve", retrieve_node)
workflow.add_node("draft", draft_node)
workflow.add_node("validate", validate_node)
workflow.add_node("rewrite", rewrite_node)
workflow.add_node("send", send_node)
workflow.set_entry_point("retrieve")
workflow.add_edge("retrieve", "draft")
workflow.add_edge("draft", "validate")
workflow.add_edge("rewrite", "validate")
workflow.add_edge("send", END)
workflow.add_conditional_edges("validate", should_continue, {"send": "send", "rewrite": "rewrite", "escalate": END})
agent_app = workflow.compile()

# --- New API Endpoint to run the agent ---
@app.post("/process-email")
async def process_email_endpoint():
    print("Starting email agent workflow...")
    final_state = await agent_app.ainvoke({})
    if final_state.get("error"):
        return {"status": "failed", "message": final_state["error"]}
    return {"status": "success", "message": "Workflow completed.", "final_state": final_state}
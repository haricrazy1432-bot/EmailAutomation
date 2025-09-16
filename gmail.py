# main.py
import os
import base64
import re
from typing import TypedDict, Optional
from bs4 import BeautifulSoup
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from langgraph.graph import StateGraph

# ---------------- Gmail Helper Functions ----------------

import os

BASE_DIR = r"C:\Users\kiran.yabaji\Desktop\Chroma"  # folder where credentials.json is
CLIENT_SECRET_FILE = os.path.join(BASE_DIR, "credentials.json")
TOKEN_FILE = os.path.join(BASE_DIR, "token.json")

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]  # readonly + send

def authenticate_gmail():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
        creds = flow.run_local_server(port=8080)
        with open(TOKEN_FILE, "w") as token_file:
            token_file.write(creds.to_json())
    return creds

def get_gmail_service():
    creds = authenticate_gmail()
    return build("gmail", "v1", credentials=creds)

def clean_body(raw_body: str) -> str:
    if not raw_body:
        return ""
    if "<html" in raw_body.lower():
        soup = BeautifulSoup(raw_body, "html.parser")
        text = soup.get_text()
        text = re.sub(r"\n\s*\n", "\n\n", text)
        return text.strip()
    return raw_body.strip()

def fetch_latest_email():
    service = get_gmail_service()
    results = service.users().messages().list(userId="me", maxResults=1, labelIds=["INBOX"], q="is:unread").execute()
    messages = results.get("messages", [])
    if not messages:
        return None

    msg_data = service.users().messages().get(userId="me", id=messages[0]["id"]).execute()
    headers = msg_data["payload"].get("headers", [])
    subject = next((h["value"] for h in headers if h["name"] == "Subject"), "")
    sender = next((h["value"] for h in headers if h["name"] == "From"), "")

    # Extract body
    body = ""
    if "data" in msg_data["payload"]["body"]:
        body = base64.urlsafe_b64decode(msg_data["payload"]["body"]["data"]).decode("utf-8", errors="ignore")
    else:
        for part in msg_data["payload"].get("parts", []):
            if part["mimeType"] in ["text/plain", "text/html"]:
                data = part["body"].get("data")
                if data:
                    body = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                    break

    # Mark as read
    service.users().messages().modify(userId="me", id=messages[0]["id"], body={"removeLabelIds": ["UNREAD"]}).execute()

    return {"subject": subject, "from": sender, "body": clean_body(body)}

def send_email(to: str, subject: str, body: str):
    service = get_gmail_service()
    from email.mime.text import MIMEText
    import base64

    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()


# ---------------- LangGraph Workflow ----------------

class EmailState(TypedDict):
    email: Optional[dict]
    draft: Optional[str]
    validated: Optional[str]
    rewritten: Optional[str]

def retrieve_node(state: EmailState):
    email = fetch_latest_email()
    if not email:
        print("📭 No new emails")
        return state
    print(f"📥 New email from {email['from']} with subject: {email['subject']}")
    state["email"] = email
    return state

def draft_node(state: EmailState):
    email = state.get("email")
    if email:
        state["draft"] = f"Hi, regarding '{email['subject']}', here is a draft reply..."
    return state

def validate_node(state: EmailState):
    state["validated"] = state.get("draft")  # approve draft for now
    return state

def rewrite_node(state: EmailState):
    draft = state.get("validated")
    if draft:
        state["rewritten"] = draft.replace("draft", "final")
    return state

def send_node(state: EmailState):
    email = state.get("email")
    reply = state.get("rewritten")
    if email and reply:
        send_email(email["from"], f"Re: {email['subject']}", reply)
        print(f"📤 Email sent to: {email['from']}")
    return state

# Build workflow
workflow = StateGraph(EmailState)
workflow.add_node("Retrieve", retrieve_node)
workflow.add_node("Draft", draft_node)
workflow.add_node("Validate", validate_node)
workflow.add_node("Rewrite", rewrite_node)
workflow.add_node("Send", send_node)

workflow.set_entry_point("Retrieve")
workflow.add_edge("Retrieve", "Draft")
workflow.add_edge("Draft", "Validate")
workflow.add_edge("Validate", "Rewrite")
workflow.add_edge("Rewrite", "Send")

app = workflow.compile()

# Run
if __name__ == "__main__":
    final_state = app.invoke({})
    print("✅ Workflow done. Final state:", final_state)

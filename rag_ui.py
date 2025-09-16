import streamlit as st
import requests
from datetime import datetime
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

st.set_page_config(page_title="Agent Dashboard", layout="wide")

# --- Gmail Function to show unread emails (for display purposes only) ---
def get_unread_messages():
    try:
        # NOTE: This UI function still uses the Gmail API directly for display.
        # This is okay as it only reads emails, but the agent itself is
        # triggered via the FastAPI endpoint.
        creds = Credentials.from_authorized_user_file(
            "token.json", ["https://www.googleapis.com/auth/gmail.readonly"]
        )
        service = build("gmail", "v1", credentials=creds)

        results = service.users().messages().list(
            userId="me", labelIds=["INBOX"], q="is:unread"
        ).execute()
        messages = results.get("messages", [])

        emails = []
        for msg in messages[:5]:
            msg_data = service.users().messages().get(
                userId="me", id=msg["id"]
            ).execute()
            headers = msg_data["payload"]["headers"]
            subject = next(h["value"] for h in headers if h["name"] == "Subject")
            sender = next(h["value"] for h in headers if h["name"] == "From")
            
            # This is a simplified body. The agent's full body fetch is on the backend.
            emails.append({
                "from": sender,
                "subject": subject,
                "time": datetime.now().strftime("%H:%M:%S")
            })
        return emails
    except Exception as e:
        st.error(f"❌ Gmail API error: {e}")
        return []

# --- Session state for logs ---
if "logs" not in st.session_state:
    st.session_state.logs = []
if "email_data" not in st.session_state:
    st.session_state.email_data = {}

# --- Dashboard UI ---
st.title("📨 Agent Dashboard")
st.subheader("🟢 Agent Status")
st.metric("Status", "Running")

# --- Inbox Section ---
st.subheader("📧 Inbox")
emails = get_unread_messages()
if not emails:
    st.info("No unread emails. Waiting for new ones...")
else:
    for email in emails:
        st.write(f"📩 **{email['subject']}** (from {email['from']} at {email['time']})")
        
# --- Agent Control & Logging ---
st.subheader("⚙️ Agent Control")
st.write("Click the button below to trigger the email agent.")

if st.button("🚀 Run Agent Workflow"):
    st.session_state.logs.append(f"{datetime.now().strftime('%H:%M:%S')} - Triggering agent workflow via API...")
    
    # Use a spinner to show that work is being done
    with st.spinner('Processing email...'):
        try:
            # Send a request to your FastAPI endpoint
            response = requests.post("http://127.0.0.1:8000/process-email")
            response.raise_for_status() # Raise an exception for bad status codes
            
            result = response.json()
            
            if result['status'] == 'success':
                st.session_state.logs.append(f"{datetime.now().strftime('%H:%M:%S')} - ✅ Workflow completed successfully!")
                st.session_state.email_data = result['final_state']
            else:
                st.session_state.logs.append(f"{datetime.now().strftime('%H:%M:%S')} - ❌ Workflow failed: {result['message']}")
                st.session_state.email_data = result.get('final_state', {})
                
        except requests.exceptions.RequestException as e:
            st.session_state.logs.append(f"{datetime.now().strftime('%H:%M:%S')} - 🚨 API call failed: {e}")
            st.session_state.email_data = {}

# --- Display Results ---
st.subheader("📬 Latest Agent Action")
if st.session_state.email_data:
    final_state = st.session_state.email_data
    
    if 'email' in final_state and final_state['email']:
        st.success("✅ Email Processed and Replied")
        
        with st.expander("Original Email"):
            st.write(f"**From:** {final_state['email']['from']}")
            st.write(f"**Subject:** {final_state['email']['subject']}")
            st.write("---")
            st.write(final_state['email']['body'])

        with st.expander("Drafted Reply"):
            st.write(final_state.get('draft', 'No draft generated.'))
            st.write(f"**Validation Status:** `{final_state.get('validation_status', 'N/A')}`")
            st.write(f"**Rewrite Attempts:** `{final_state.get('rewrite_attempts', 0)}`")

    elif 'error' in final_state:
        st.error(f"❌ Error: {final_state['error']}")
    else:
        st.info("No new email found.")
        st.write("The agent is waiting for a new unread email to process.")
else:
    st.info("Click 'Run Agent Workflow' to start.")

# --- Logs ---
st.subheader("📜 Agent Logs")
for log in reversed(st.session_state.logs):
    st.write(log)
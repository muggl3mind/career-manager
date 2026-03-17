#!/usr/bin/env python3
"""
Gmail OAuth2 Email Sender
Sends emails using Gmail API with OAuth2 authentication.
"""

import os
import base64
import pickle
import html
from pathlib import Path
from email.mime.text import MIMEText
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "scripts"))
from config_loader import get as config_get

# Gmail API scope for sending emails
SCOPES = ['https://www.googleapis.com/auth/gmail.send']

# Paths - resolved via config.yaml
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CREDS_DIR = PROJECT_ROOT / '.credentials'
CREDENTIALS_FILE = CREDS_DIR / 'gmail-credentials.json'
TOKEN_FILE = PROJECT_ROOT / config_get("credentials.gmail_token", ".credentials/gmail-token.pickle")


def get_gmail_service():
    """Authenticate and return Gmail API service."""
    creds = None
    
    # Load existing token if available
    if TOKEN_FILE.exists():
        with open(TOKEN_FILE, 'rb') as token:
            creds = pickle.load(token)
    
    # If no valid credentials, authenticate
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # Refresh expired token
            print("Refreshing expired token...")
            creds.refresh(Request())
        else:
            # First-time authentication
            print("Starting OAuth2 authentication flow...")
            print(f"Your browser will open. Sign in with {config_get('email.from', 'your-email@gmail.com')}")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Save the credentials for next time
        with open(TOKEN_FILE, 'wb') as token:
            pickle.dump(creds, token)
        print("✓ Token saved successfully")
    
    return build('gmail', 'v1', credentials=creds)


def _normalize_html_body(body: str) -> str:
    """Ensure readable HTML. If plain/markdown text is passed, preserve line breaks."""
    txt = body or ""
    lowered = txt.lower()
    looks_like_html = any(tag in lowered for tag in ["<html", "<body", "<p", "<br", "<h1", "<h2", "<ul", "<ol", "<table"]) 
    if looks_like_html:
        return txt
    escaped = html.escape(txt)
    escaped = escaped.replace("\n", "<br>\n")
    return f"<html><body style='font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif;line-height:1.45'>{escaped}</body></html>"


def send_email_with_result(to, subject, body, bcc=None):
    """Send an email via Gmail API and return structured result."""
    if not config_get("integrations.gmail_enabled", False):
        print("[gmail] Email send skipped — gmail_enabled is false in config.yaml")
        return {"success": False, "skipped": True, "message_id": None}

    BCC_RECIPIENT = config_get("email.bcc", "")

    try:
        service = get_gmail_service()

        body_html = _normalize_html_body(body)
        message = MIMEText(body_html, 'html')
        message['to'] = to
        message['subject'] = subject
        message['from'] = config_get("email.from", "your-email@gmail.com")

        bcc_parts = [b for b in [BCC_RECIPIENT, bcc] if b]
        if bcc_parts:
            message['bcc'] = ", ".join(bcc_parts)

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

        result = service.users().messages().send(
            userId='me',
            body={'raw': raw}
        ).execute()

        print(f"✓ Email sent successfully!")
        print(f"  To: {to}")
        print(f"  Subject: {subject}")
        print(f"  Message ID: {result['id']}")
        return {"success": True, "message_id": result.get('id')}

    except Exception as e:
        print(f"✗ Error sending email: {e}")
        return {"success": False, "error": str(e), "message_id": None}


def send_email(to, subject, body, bcc=None):
    """Backward-compatible boolean send API."""
    return bool(send_email_with_result(to, subject, body, bcc=bcc).get("success"))


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) < 4:
        print("Usage: python send_email.py <to> <subject> <body>")
        print("\nExample:")
        print('  python send_email.py recipient@example.com "Test" "Hello from AI Career Manager!"')
        sys.exit(1)
    
    to_addr = sys.argv[1]
    subject = sys.argv[2]
    body = sys.argv[3]
    
    send_email(to_addr, subject, body)

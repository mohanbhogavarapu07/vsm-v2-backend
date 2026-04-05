"""
VSM Backend – Email Service

Provides asynchronous email notification capabilities utilizing SMTP.
"""

import logging
import asyncio
import os
import smtplib
from email.message import EmailMessage

logger = logging.getLogger(__name__)

def _send_email_sync(to_email: str, subject: str, body: str) -> None:
    smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", 587))
    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    smtp_from = os.environ.get("SMTP_FROM", smtp_user or "noreply@vsm.dev")

    if not smtp_user or not smtp_password:
        logger.warning(f"SMTP credentials missing. Would have sent: {subject} to {to_email}")
        return

    msg = EmailMessage()
    msg.set_content(body)
    msg["Subject"] = subject
    msg["From"] = smtp_from
    msg["To"] = to_email

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
        server.quit()
        logger.info(f"Successfully sent email to {to_email}")
    except Exception as e:
        logger.error(f"SMTP sending failed: {str(e)}", exc_info=True)
        raise

async def send_task_assignment_email(
    user_email: str,
    user_name: str,
    task_title: str,
    project_name: str,
    team_name: str
) -> None:
    """
    Sends an assignment email using standard SMTP.
    """
    subject = "New Task Assigned to You"
    
    body = f"""Hello {user_name},

You have been assigned a task.

Project: {project_name}
Team: {team_name}
Task: {task_title}

Please check your dashboard.

Regards,
AI Workflow System
"""

    return await asyncio.to_thread(_send_email_sync, user_email, subject, body)

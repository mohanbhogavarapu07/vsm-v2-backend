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

def _send_email_sync(to_email: str, subject: str, body_text: str, body_html: str | None = None) -> None:
    smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", 587))
    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    smtp_from = os.environ.get("SMTP_FROM", smtp_user or "noreply@vsm.dev")

    if not smtp_user or not smtp_password:
        logger.warning(f"SMTP credentials missing. Would have sent: {subject} to {to_email}")
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp_from
    msg["To"] = to_email
    msg.set_content(body_text)

    if body_html:
        msg.add_alternative(body_html, subtype="html")

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
        server.quit()
        logger.info(f"Successfully sent dual-mode email to {to_email}")
    except Exception as e:
        logger.error(f"SMTP sending failed: {str(e)}", exc_info=True)
        raise

async def send_task_assignment_email(
    user_email: str,
    user_name: str,
    task_title: str,
    project_name: str,
    team_name: str,
    task_id: int | None = None,
    project_id: int | None = None,
    team_id: int | None = None,
    priority: str | None = None,
    status_name: str | None = None,
    assigned_by: str | None = None,
) -> None:
    """
    Sends a professional, HTML-formatted assignment email with GitHub/Jira-style layout.
    """
    subject = f"New Task Assigned: {task_title}"
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:8080")
    
    # Construct a full contextual deep link (GitHub/Jira style)
    if task_id and project_id and team_id:
        task_link = f"{frontend_url}/projects/{project_id}/teams/{team_id}/task/{task_id}"
    else:
        task_link = frontend_url

    # Plain Text Fallback
    body_text = f"""Hello {user_name},

You've been assigned a new task: {task_title}

Project: {project_name}
Team: {team_name}
Assigned By: {assigned_by or 'Admin'}
Priority: {priority or 'Normal'}
Status: {status_name or 'To Do'}

View Task: {task_link}

Regards,
AI Workflow System
"""

    # Professional HTML Template (Inline CSS for maximum compatibility)
    body_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #333; background-color: #f6f8fa; margin: 0; padding: 0; }}
            .container {{ max-width: 600px; margin: 20px auto; background: #ffffff; border: 1px solid #e1e4e8; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }}
            .header {{ background: #f8f9fa; padding: 24px; border-bottom: 1px solid #e1e4e8; text-align: left; }}
            .header h1 {{ margin: 0; font-size: 18px; color: #24292e; font-weight: 600; }}
            .body {{ padding: 32px; }}
            .greeting {{ font-size: 16px; margin-bottom: 16px; color: #24292e; }}
            .main-msg {{ font-size: 15px; margin-bottom: 24px; color: #586069; }}
            .task-card {{ background: #fafbfc; border: 1px solid #e1e4e8; border-radius: 6px; padding: 20px; margin-bottom: 30px; }}
            .task-title {{ font-size: 17px; font-weight: 600; color: #0366d6; margin: 0 0 16px 0; }}
            .detail-row {{ display: flex; margin-bottom: 8px; font-size: 14px; }}
            .detail-label {{ width: 100px; color: #6a737d; font-weight: 500; }}
            .detail-value {{ color: #24292e; font-weight: 500; }}
            .btn-container {{ text-align: center; margin-top: 10px; }}
            .button {{ background-color: #0366d6; color: #ffffff !important; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-size: 14px; font-weight: 600; display: inline-block; }}
            .footer {{ padding: 20px; text-align: center; font-size: 12px; color: #6a737d; background: #f8f9fa; border-top: 1px solid #e1e4e8; }}
            .footer a {{ color: #0366d6; text-decoration: none; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>AI Workflow System</h1>
            </div>
            <div class="body">
                <div class="greeting">Hello {user_name},</div>
                <div class="main-msg">You have been assigned a new task.</div>
                
                <div class="task-card">
                    <h2 class="task-title">{task_title}</h2>
                    <div style="margin-top: 15px;">
                        <table width="100%" border="0" cellspacing="0" cellpadding="4">
                            <tr>
                                <td width="100" style="color: #6a737d; font-size: 14px;">Project</td>
                                <td style="color: #24292e; font-size: 14px; font-weight: 500;">{project_name}</td>
                            </tr>
                            <tr>
                                <td style="color: #6a737d; font-size: 14px;">Team</td>
                                <td style="color: #24292e; font-size: 14px; font-weight: 500;">{team_name}</td>
                            </tr>
                            <tr>
                                <td style="color: #6a737d; font-size: 14px;">Assigned By</td>
                                <td style="color: #24292e; font-size: 14px; font-weight: 500;">{assigned_by or 'Admin'}</td>
                            </tr>
                            <tr>
                                <td style="color: #6a737d; font-size: 14px;">Priority</td>
                                <td style="color: #24292e; font-size: 14px; font-weight: 500;">{priority or 'Normal'}</td>
                            </tr>
                            <tr>
                                <td style="color: #6a737d; font-size: 14px;">Status</td>
                                <td style="color: #24292e; font-size: 14px; font-weight: 500;">{status_name or 'To Do'}</td>
                            </tr>
                        </table>
                    </div>
                </div>

                <div class="btn-container">
                    <a href="{task_link}" class="button">View Task Details</a>
                </div>
            </div>
            <div class="footer">
                This is an automated notification from AI Workflow System.<br>
                Need help? <a href="#">Contact Support</a>
            </div>
        </div>
    </body>
    </html>
    """

    return await asyncio.to_thread(_send_email_sync, user_email, subject, body_text, body_html)

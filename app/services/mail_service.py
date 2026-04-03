"""
VSM Backend – Mail Service (Gmail SMTP Implementation)

Provides reliable email delivery using Gmail's SMTP server via the built-in `smtplib`.
"""
import logging
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

class MailService:
    def __init__(self):
        self.smtp_server = settings.smtp_server.strip() if settings.smtp_server else "smtp.gmail.com"
        self.smtp_port = settings.smtp_port
        self.smtp_user = settings.smtp_user.strip() if settings.smtp_user else None
        self.smtp_password = settings.smtp_password.strip() if settings.smtp_password else None
        # Gmail strictness: The 'From' address must match the login user or it will fail
        self.sender = self.smtp_user if "gmail.com" in (self.smtp_user or "") else (settings.smtp_from or self.smtp_user)

    async def send_invitation_email(
        self,
        to_email: str,
        team_name: str,
        role_name: str,
        inviter_name: str,
        invitation_id: int
    ):
        """
        Sends an invitation email using the Gmail SMTP server.
        """
        if not self.smtp_user or not self.smtp_password:
            logger.warning("--- MOCK EMAIL (NO SMTP CREDENTIALS) ---")
            logger.warning(f"To: {to_email}")
            return True

        subject = f"You've been invited to join {team_name} on VSM"
        accept_url = f"{settings.frontend_url}/accept-invite/{invitation_id}"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f8fafc; margin: 0; padding: 0; }}
                .container {{ max-width: 600px; margin: 40px auto; background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); border: 1px solid #e2e8f0; }}
                .header {{ background-color: #4f46e5; padding: 32px; text-align: center; }}
                .logo {{ color: #ffffff; font-size: 24px; font-weight: 700; }}
                .content {{ padding: 40px; color: #1e293b; line-height: 1.6; }}
                h1 {{ font-size: 24px; font-weight: 600; color: #0f172a; margin-top: 0; }}
                .details {{ background-color: #f1f5f9; padding: 24px; border-radius: 8px; margin: 24px 0; border: 1px solid #e2e8f0; }}
                .button-container {{ text-align: center; margin-top: 32px; }}
                .button {{ background-color: #4f46e5; color: #ffffff !important; padding: 12px 32px; border-radius: 6px; text-decoration: none; font-weight: 600; display: inline-block; }}
                .footer {{ background-color: #f8fafc; padding: 24px; text-align: center; font-size: 12px; color: #94a3b8; border-top: 1px solid #e2e8f0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header"><div class="logo">Virtual Scrum Master</div></div>
                <div class="content">
                    <h1>You're Invited!</h1>
                    <p><strong>{inviter_name}</strong> has invited you to join <strong>{team_name}</strong> as a <strong>{role_name}</strong>.</p>
                    <div class="details">
                        <div><strong>Team:</strong> {team_name}</div>
                        <div><strong>Role:</strong> {role_name}</div>
                    </div>
                    <div class="button-container">
                        <a href="{accept_url}" class="button">Accept Invitation</a>
                    </div>
                </div>
                <div class="footer">&copy; 2026 VSM Backend. This is an automated message.</div>
            </div>
        </body>
        </html>
        """

        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = f"VSM <{self.sender}>"
        message["To"] = to_email

        text_content = f"You've been invited to join {team_name} on VSM as a {role_name}. Accept here: {accept_url}"
        message.attach(MIMEText(text_content, "plain"))
        message.attach(MIMEText(html_content, "html"))

        try:
            logger.info(f"Connecting to SMTP server {self.smtp_server}:{self.smtp_port}...")
            context = ssl.create_default_context()
            
            # Use threading to avoid blocking the event loop since smtplib is synchronous
            import asyncio
            from functools import partial

            def _send():
                # For Gmail, port 465 is SSL, 587 is STARTTLS
                if self.smtp_port == 465:
                    with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, context=context) as server:
                        server.login(self.smtp_user, self.smtp_password)
                        server.sendmail(self.sender, to_email, message.as_string())
                else:
                    with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                        server.ehlo()
                        server.starttls(context=context)
                        server.ehlo()
                        server.login(self.smtp_user, self.smtp_password)
                        server.sendmail(self.sender, to_email, message.as_string())

            await asyncio.get_event_loop().run_in_executor(None, _send)
            logger.info(f"Successfully sent SMTP email to {to_email}")
            return True
        except Exception as e:
            logger.error(f"SMTP error: {e}")
            raise e

"""
VSM Backend – Mail Service (Resend Implementation)

Provides reliable email delivery using the Resend.com HTTP API.
Bypasses ISP SMTP blocks and eliminates the need for manual handshake logic.
"""
import logging
import resend
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

if settings.resend_api_key:
    resend.api_key = settings.resend_api_key


class MailService:
    def __init__(self):
        self.api_key = settings.resend_api_key
        self.sender = settings.resend_from or "onboarding@resend.dev"

    async def send_invitation_email(
        self,
        to_email: str,
        team_name: str,
        role_name: str,
        inviter_name: str,
        invitation_id: int
    ):
        """
        Sends an invitation email using the Resend HTTP API.
        """
        if not self.api_key or self.api_key == "re_your_api_key_here":
            logger.warning("--- MOCK EMAIL (NO RESEND API KEY) ---")
            logger.warning(f"To: {to_email}")
            logger.warning(f"Invite: {settings.frontend_url}/accept-invite/{invitation_id}")
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

        try:
            logger.info(f"Sending Resend email to {to_email}...")
            # Note: resend-python is currently sync.
            resend.Emails.send({
                "from": f"VSM <{self.sender}>",
                "to": to_email,
                "subject": subject,
                "html": html_content
            })
            logger.info(f"Successfully sent Resend email to {to_email}")
            return True
        except Exception as e:
            logger.error(f"Resend API error: {e}")
            raise e

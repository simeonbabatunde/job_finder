import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os

from app.observability import log_event

# Default to Gmail (TLS)
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_EMAIL = os.getenv("SMTP_EMAIL")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")

def send_reset_email(to_email: str, reset_link: str):
    """
    Sends a password reset email using SMTP.
    Requires SMTP_EMAIL and SMTP_PASSWORD env vars.
    """
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        log_event("email.reset.skipped", level="warning", recipient=to_email, reason="missing_smtp_credentials")
        return False

    msg = MIMEMultipart('alternative')
    msg['From'] = SMTP_EMAIL
    msg['To'] = to_email
    msg['Subject'] = "Reset Your Password"

    text = f"Reset your password by following this link: {reset_link}\n\nThis link expires in 1 hour."
    
    html = f"""
    <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 600px; margin: 0 auto; padding: 40px 20px; background-color: #f8fafc; border-radius: 16px;">
        <div style="background-color: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.05);">
            <div style="text-align: center; margin-bottom: 30px;">
                <h1 style="color: #1e293b; font-size: 24px; font-weight: 800; margin: 0;">Job Finder</h1>
            </div>
            
            <h2 style="color: #334155; font-size: 20px; font-weight: 600; margin-bottom: 20px;">Reset Your Password</h2>
            
            <p style="color: #64748b; line-height: 1.6; margin-bottom: 30px;">
                We received a request to reset the password for your account. If you made this request, please click the button below to protect your account.
            </p>
            
            <div style="text-align: center; margin-bottom: 30px;">
                <a href="{reset_link}" style="display: inline-block; background-color: #4f46e5; color: white; padding: 14px 32px; text-decoration: none; border-radius: 8px; font-weight: bold; font-size: 16px; box-shadow: 0 4px 6px rgba(79, 70, 229, 0.2);">
                    Reset Password
                </a>
            </div>
            
            <p style="color: #94a3b8; font-size: 14px; text-align: center; margin-top: 40px;">
                Link expires in 1 hour. If you didn't ask for this, you can safely ignore this email.
            </p>
        </div>
    </div>
    """
    
    msg.attach(MIMEText(text, 'plain'))
    msg.attach(MIMEText(html, 'html'))

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        log_event("email.reset.sent", recipient=to_email)
        return True
    except Exception as e:
        log_event("email.reset.failed", level="error", recipient=to_email, error=str(e))
        return False

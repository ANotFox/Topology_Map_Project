import threading
import smtplib
from email.message import EmailMessage
import ssl
import logging

logger = logging.getLogger(__name__)

# Email configuration
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
EMAIL_ADDRESS = "ar694@snu.edu.in"
APP_PASSWORD = "mdsrfmvmwjhdznkd"

def send_email_alert_async(subject, body):
    def _send_email():
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = EMAIL_ADDRESS
        msg["To"] = EMAIL_ADDRESS
        msg.set_content(body)
        try:
            context = ssl.create_default_context()
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                server.login(EMAIL_ADDRESS, APP_PASSWORD)
                server.send_message(msg)
                logger.info("✅ Email alert sent successfully")
        except Exception as e:
            logger.error(f"❌ Failed to send email: {str(e)}")
    threading.Thread(target=_send_email, daemon=True).start()

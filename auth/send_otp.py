from datetime import datetime, timedelta
import random
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from supabase_config.client import supabase

load_dotenv()

def generate_otp() -> str:
    return str(random.randint(100000, 999999))

def send_otp_email(email: str, otp: str):
    sender_email = os.getenv("SMTP_EMAIL")
    sender_password = os.getenv("SMTP_PASSWORD")
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", 587))

    message = MIMEMultipart()
    message["From"] = sender_email
    message["To"] = email
    message["Subject"] = "Your Verification Code"

    html = f"""
    <html>
      <body>
        <h2>Your OTP Code</h2>
        <p>Your verification code is: <strong>{otp}</strong></p>
        <p>This code expires in 10 minutes.</p>
        <p><small>If you didn't request this, please ignore this email.</small></p>
      </body>
    </html>
    """

    message.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, email, message.as_string())
    except Exception as e:
        raise Exception(f"Failed to send OTP email: {str(e)}")

def save_otp(email: str, otp: str):
    expires_at = datetime.utcnow() + timedelta(minutes=10)
    try:
        response = supabase.table("email_otp_verification").insert({
            "email": email,
            "otp": otp,
            "expires_at": expires_at.isoformat(),
            "verified": False
        }).execute()
        
        if not response.data:
            raise Exception("Failed to save OTP: No data returned")
            
        return response.data[0]
    except Exception as e:
        raise Exception(f"Failed to save OTP: {str(e)}")
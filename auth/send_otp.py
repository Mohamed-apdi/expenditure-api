#send_otp.py
from datetime import datetime, timedelta
import random
from supabase_config.client import supabase

def generate_otp() -> str:
    return str(random.randint(100000, 999999))

def send_otp_email(email: str, otp: str):
    # Implement your email sending logic here
    print(f"OTP for {email}: {otp}")

def save_and_send_otp(email: str):
    # Delete any existing OTPs for this email
    supabase.table("email_otp_verification")\
        .delete()\
        .eq("email", email)\
        .execute()

    otp = generate_otp()
    expires_at = datetime.utcnow() + timedelta(minutes=10)

    supabase.table("email_otp_verification").insert({
        "email": email,
        "otp": otp,
        "expires_at": expires_at.isoformat()
    }).execute()

    send_otp_email(email, otp)

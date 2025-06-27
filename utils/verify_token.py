import requests
from fastapi import Request, HTTPException
from jose import jwt, JWTError
import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_JWKS_URL = os.getenv("SUPABASE_JWKS_URL")
ISSUER = f"{SUPABASE_URL}/auth/v1"
ALGORITHMS = ["RS256"]

# Simple cache for JWKS
jwks_cache = {}

def get_supabase_public_key():
    global jwks_cache
    if not jwks_cache:
        res = requests.get(SUPABASE_JWKS_URL)
        if res.status_code != 200:
            raise RuntimeError("Could not fetch Supabase JWKS")
        jwks_cache = res.json()
    return jwks_cache

def verify_token(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")

    token = auth_header.split(" ")[1]

    try:
        jwks = get_supabase_public_key()
        unverified_header = jwt.get_unverified_header(token)
        key = next((k for k in jwks["keys"] if k["kid"] == unverified_header["kid"]), None)

        if not key:
            raise HTTPException(status_code=401, detail="No matching JWK found")

        payload = jwt.decode(
            token,
            key,
            algorithms=ALGORITHMS,
            issuer=ISSUER,
            options={"verify_aud": False}  # set True if you want to enforce audience
        )

        return payload["sub"]  # This is the Supabase user ID

    except JWTError as e:
        raise HTTPException(status_code=401, detail="Token is invalid or expired")

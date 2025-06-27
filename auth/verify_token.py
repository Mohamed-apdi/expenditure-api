from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
import requests
from fastapi import Depends, HTTPException, status
import os
from typing import Dict, Any

security = HTTPBearer()

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        token = credentials.credentials
        
        # Configuration
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_KEY")
        jwks_url = f"{supabase_url}/auth/v1/keys"
        
        # Option 1: Verify using JWKS (recommended for production)
        headers = {"apikey": supabase_key}
        response = requests.get(jwks_url, headers=headers, timeout=10)
        response.raise_for_status()
        jwks = response.json()
        
        unverified_header = jwt.get_unverified_header(token)
        rsa_key = {}
        for key in jwks["keys"]:
            if key["kid"] == unverified_header["kid"]:
                rsa_key = {
                    "kty": key["kty"],
                    "kid": key["kid"],
                    "use": key["use"],
                    "n": key["n"],
                    "e": key["e"]
                }
        
        if not rsa_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unable to find appropriate key"
            )
            
        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            audience="authenticated",
            issuer=supabase_url
        )

        # Option 2: Alternative using JWT_SECRET (simpler but less secure)
        # Uncomment below if you prefer this method
        # payload = jwt.decode(
        #     token,
        #     os.getenv("JWT_SECRET"),
        #     algorithms=["HS256"],
        #     audience="authenticated",
        #     issuer=supabase_url
        # )
        
        return payload["sub"]  # return user_id
    
    except requests.exceptions.RequestException as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Could not fetch JWKS: {str(e)}"
        )
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Authentication failed: {str(e)}"
        )
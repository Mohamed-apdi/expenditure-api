from supabase import create_client, Client
import os
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv() 

def get_supabase_client():
    """Get Supabase client with proper error handling"""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    
    if not url or not key:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in environment variables")
    
    try:
        return create_client(url, key)
    except Exception as e:
        raise ValueError(f"Failed to create Supabase client: {e}")

# Initialize the client
try:
    supabase: Client = get_supabase_client()
except ValueError as e:
    print(f"Warning: Supabase client not initialized: {e}")
    supabase = None
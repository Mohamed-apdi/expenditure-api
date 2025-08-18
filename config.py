"""
Configuration management for the Household Expenditure API
"""

import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    """Application configuration"""
    
    # Supabase Configuration
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")
    
    # API Configuration
    API_HOST = os.getenv("API_HOST", "0.0.0.0")
    API_PORT = int(os.getenv("API_PORT", "8000"))
    
    # Logging
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    
    # CORS
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")
    
    @classmethod
    def validate(cls):
        """Validate required configuration"""
        required_vars = ["SUPABASE_URL", "SUPABASE_KEY"]
        missing_vars = [var for var in required_vars if not getattr(cls, var)]
        
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
        
        return True
    
    @classmethod
    def print_config(cls):
        """Print current configuration (without sensitive data)"""
        print("🔧 API Configuration:")
        print(f"   📍 Host: {cls.API_HOST}")
        print(f"   🔌 Port: {cls.API_PORT}")
        print(f"   🌐 Supabase URL: {cls.SUPABASE_URL}")
        print(f"   🔑 Supabase Key: {'*' * 10 if cls.SUPABASE_KEY else 'NOT SET'}")
        print(f"   📝 Log Level: {cls.LOG_LEVEL}")
        print(f"   🌍 CORS Origins: {cls.CORS_ORIGINS}")
        print("=" * 50)

# Global config instance
config = Config()

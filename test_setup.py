#!/usr/bin/env python3
"""
Test script to verify Supabase configuration and connection
"""

import os
from dotenv import load_dotenv

def test_environment():
    """Test if environment variables are properly set"""
    print("🔍 Testing Environment Configuration...")
    print("=" * 50)
    
    # Load environment variables
    load_dotenv()
    
    # Check required variables
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    
    print(f"SUPABASE_URL: {'✅ Set' if supabase_url else '❌ Missing'}")
    if supabase_url:
        print(f"  Value: {supabase_url}")
    
    print(f"SUPABASE_KEY: {'✅ Set' if supabase_key else '❌ Missing'}")
    if supabase_key:
        print(f"  Value: {supabase_key[:10]}...{supabase_key[-10:] if len(supabase_key) > 20 else ''}")
    
    print()
    
    if not supabase_url or not supabase_key:
        print("❌ Configuration Error: Missing required environment variables")
        print("Please create a .env file with SUPABASE_URL and SUPABASE_KEY")
        return False
    
    return True

def test_supabase_import():
    """Test if Supabase can be imported and initialized"""
    print("🔍 Testing Supabase Import...")
    print("=" * 50)
    
    try:
        from supabase_config.client import supabase, get_supabase_client
        print("✅ Supabase modules imported successfully")
        
        if supabase is None:
            print("❌ Supabase client is None - configuration issue")
            return False
        
        print("✅ Supabase client initialized")
        return True
        
    except ImportError as e:
        print(f"❌ Import Error: {e}")
        print("Please install required dependencies: pip install -r requirements.txt")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def test_supabase_connection():
    """Test actual connection to Supabase"""
    print("🔍 Testing Supabase Connection...")
    print("=" * 50)
    
    try:
        from supabase_config.client import supabase
        
        if supabase is None:
            print("❌ Cannot test connection - client not initialized")
            return False
        
        # Try a simple query
        response = supabase.table('expenses').select('count', count='exact').limit(1).execute()
        print("✅ Supabase connection successful")
        print(f"  Response: {response}")
        return True
        
    except Exception as e:
        print(f"❌ Connection Error: {e}")
        print("Please check your Supabase credentials and project status")
        return False

def main():
    """Run all tests"""
    print("🚀 Household Expenditure API - Setup Test")
    print("=" * 60)
    print()
    
    # Test 1: Environment variables
    env_ok = test_environment()
    print()
    
    # Test 2: Supabase import
    import_ok = test_supabase_import()
    print()
    
    # Test 3: Supabase connection
    connection_ok = False
    if env_ok and import_ok:
        connection_ok = test_supabase_connection()
    else:
        print("⏭️  Skipping connection test due to previous failures")
    print()
    
    # Summary
    print("📊 Test Summary")
    print("=" * 60)
    print(f"Environment: {'✅ PASS' if env_ok else '❌ FAIL'}")
    print(f"Import:      {'✅ PASS' if import_ok else '❌ FAIL'}")
    print(f"Connection:  {'✅ PASS' if connection_ok else '❌ FAIL'}")
    print()
    
    if env_ok and import_ok and connection_ok:
        print("🎉 All tests passed! Your API should work correctly.")
        print("You can now start the API with: python start_api.py")
    else:
        print("⚠️  Some tests failed. Please fix the issues before starting the API.")
        print()
        print("Common solutions:")
        print("1. Create a .env file with your Supabase credentials")
        print("2. Install dependencies: pip install -r requirements.txt")
        print("3. Check your Supabase project is active")
        print("4. Verify your API keys are correct")

if __name__ == "__main__":
    main()

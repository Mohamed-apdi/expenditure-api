# 🚀 Quick Setup Guide - Fix Supabase Connection Issues

## ❌ Current Problem
You're getting the error: `[ReferenceError: Property 'supabase' doesn't exist]`

This means the Supabase client is not properly initialized due to missing or incorrect environment variables.

## 🔧 Quick Fix Steps

### Step 1: Create Environment File
```bash
cd householdAPI
cp env_template.txt .env
```

### Step 2: Get Your Supabase Credentials
1. Go to [Supabase Dashboard](https://supabase.com/dashboard)
2. Select your project
3. Go to **Settings** → **API**
4. Copy these values:
   - **Project URL** (looks like: `https://abc123.supabase.co`)
   - **anon public** key (starts with `eyJ...`)

### Step 3: Update Your .env File
Edit the `.env` file and replace the placeholder values:
```env
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Step 4: Test Your Configuration
```bash
python test_setup.py
```

This will run 3 tests:
- ✅ Environment variables
- ✅ Supabase import
- ✅ Supabase connection

### Step 5: Start the API
If all tests pass:
```bash
python start_api.py
```

**Alternative**: You can also use the exact deployment command:
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## 🧪 Testing Your Setup

### Run the Test Script
```bash
python test_setup.py
```

### Expected Output (Success)
```
🚀 Household Expenditure API - Setup Test
============================================================

🔍 Testing Environment Configuration...
==================================================
SUPABASE_URL: ✅ Set
  Value: https://your-project-id.supabase.co
SUPABASE_KEY: ✅ Set
  Value: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

🔍 Testing Supabase Import...
==================================================
✅ Supabase modules imported successfully
✅ Supabase client initialized

🔍 Testing Supabase Connection...
==================================================
✅ Supabase connection successful
  Response: <Response object>

📊 Test Summary
============================================================
Environment: ✅ PASS
Import:      ✅ PASS
Connection:  ✅ PASS

🎉 All tests passed! Your API should work correctly.
You can now start the API with: python start_api.py
```

## 🐛 Common Issues & Solutions

### Issue 1: "SUPABASE_URL is not configured"
**Solution**: Check your `.env` file exists and has the correct values

### Issue 2: "Failed to create Supabase client"
**Solution**: Verify your Supabase project is active and credentials are correct

### Issue 3: "Connection failed"
**Solution**: 
- Check your internet connection
- Verify Supabase project is not paused
- Ensure API keys are correct

### Issue 4: "Module not found"
**Solution**: Install dependencies
```bash
pip install -r requirements.txt
```

## 🔍 Debug Mode

If you still have issues, enable debug logging:
```env
LOG_LEVEL=DEBUG
```

Then run the test script to see detailed error messages.

## 📞 Still Having Issues?

1. **Check Supabase Project Status**: Ensure your project is not paused
2. **Verify API Keys**: Make sure you're using the correct keys
3. **Check Network**: Ensure you can access Supabase from your machine
4. **Review Logs**: Look at the detailed error messages from the test script

## ✅ Success Checklist

- [ ] `.env` file created with correct credentials
- [ ] `python test_setup.py` shows all tests passing
- [ ] `python start_api.py` starts without errors
- [ ] API responds at `http://localhost:8000/`
- [ ] Reports endpoints work without supabase errors

---

**Once you complete these steps, your reports API should work perfectly! 🎉**

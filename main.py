from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Depends, HTTPException, status, Request, APIRouter, BackgroundTasks
from collections import defaultdict
from fastapi.middleware.cors import CORSMiddleware
from auth.verify_token import verify_token
from schemes.expenditure import ExpenditureInput
from schemes.compare import ComparisonRequest, ComparisonResult
from supabase_config.client import supabase
from supabase_config.auth_client import get_supabase_with_token
import joblib
import numpy as np
import pandas as pd
import os
from typing import Optional
from dotenv import load_dotenv
from pydantic import BaseModel
import re
import logging
import time
from calendar import monthrange

# Load environment variables
load_dotenv()

app = FastAPI()
# Add this with your other Pydantic models


class UserSignup(BaseModel):
    email: str
    password: str
    full_name: str


class UserLogin(BaseModel):
    email: str
    password: str


# CORS Configuration (Essential for React Native)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging at module level
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    """Middleware to log request processing time"""
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = f"{process_time:.4f}s"
    logger.info(
        f"Request {request.method} {request.url.path} processed in {process_time:.4f}s",
        extra={
            "method": request.method,
            "path": request.url.path,
            "duration": process_time
        }
    )
    return response

# Load model safely
try:
    MODEL_PATH = os.path.join(os.path.dirname(
        __file__), "model", "household_expenditure_model.pkl")
    model = joblib.load(MODEL_PATH)
except Exception as e:
    raise RuntimeError(f"Failed to load model: {str(e)}")


@app.get("/")
async def health_check():
    return {"status": "healthy", "message": "Household Expenditure Predictor API"}


# Add this new endpoint for user signup
@app.post("/auth/signup")
async def signup_user(user_data: UserSignup):
    try:
        auth_response = supabase.auth.sign_up({
            'email': user_data.email,
            'password': user_data.password,
            'options': {
                'data': {
                    'full_name': user_data.full_name
                }
            }
        })

        return {
            "message": "User created successfully",
            "user_id": auth_response.user.id
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Signup failed: {str(e)}")


# Modify your existing get_profile endpoint to handle missing profiles more gracefully
def is_phone_number(input_str: str) -> bool:
    """Check if input is a phone number"""
    # Simple international phone number regex
    pattern = r'^\+?[0-9\s\-\(\)]{7,}$'
    return re.match(pattern, input_str) is not None


@app.post("/auth/login")
async def login_user(login_data: UserLogin):
    try:
        # Determine if login is using phone or email
        if is_phone_number(login_data.email):
            # Step 1: Find user by phone
            user_profile = supabase.table("profiles") \
                .select("id") \
                .eq("phone", login_data.email) \
                .maybe_single() \
                .execute()

            if not user_profile.data:
                raise HTTPException(status_code=404, detail="Phone not found")

            # Step 2: Get email from auth.users
            auth_user = supabase.auth.admin.get_user_by_id(
                user_profile.data['id'])
            email = auth_user.user.email

            # Step 3: Login with email
            auth_response = supabase.auth.sign_in_with_password({
                "email": email,
                "password": login_data.password
            })
        else:
            # Regular email login
            auth_response = supabase.auth.sign_in_with_password({
                "email": login_data.email,
                "password": login_data.password
            })

        return {
            "access_token": auth_response.session.access_token,
            "refresh_token": auth_response.session.refresh_token,
            "user_id": auth_response.user.id
        }

    except Exception as e:
        raise HTTPException(
            status_code=401,
            detail=f"Login failed: {str(e)}"
        )


@app.post("/predict")
async def predict(
    request: Request,
    data: ExpenditureInput,
    user_id: str = Depends(verify_token)
):
    try:
        # Extract bearer token from request
        auth_header = request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing token")
        token = auth_header.split(" ")[1]

        # Use token-aware client
        supabase_user = get_supabase_with_token(token)

        print("Incoming data:", data.dict())
        # Convert input to DataFrame
        input_df = pd.DataFrame([data.dict()])

        # Make prediction
        pred = model.predict(input_df)[0]
        print("Raw model output:", pred)
        rounded_pred = float(round(pred, 2))

        # Store prediction
        response = supabase_user.table("predictions").insert({
            "input_data": data.dict(),
            "predicted_exp": rounded_pred,
            "model_used": "RF",
            "user_id": user_id
        }).execute()

        if hasattr(response, 'error') and response.error:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save prediction"
            )

        return {
            "predicted_expenditure": rounded_pred,
            "db_response": response.data
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Prediction failed: {str(e)}"
        )


@app.get("/predictions")
async def get_user_predictions(
    user_id: str = Depends(verify_token),
    limit: Optional[int] = 10
):
    try:
        response = supabase.table("predictions")\
            .select("*")\
            .eq("user_id", user_id)\
            .order("created_at", desc=True)\
            .limit(limit)\
            .execute()

        return response.data
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch predictions: {str(e)}"
        )


@app.get("/profile")
async def get_profile(request: Request,user_id: str = Depends(verify_token)):
    try:
        # 🔐 Get token from header
        auth_header = request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing token")
        token = auth_header.split(" ")[1]

        # ✅ Use user-authenticated Supabase client
        supabase_user = get_supabase_with_token(token)
        response = supabase_user.table("profiles")\
            .select("*")\
            .eq("id", user_id)\
            .single()\
            .execute()

        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Profile not found"
            )

        return response.data
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch profile: {str(e)}"
        )
        
@app.get("/profile/{profile_id}")
async def get_profile_by_id(
    profile_id: str,
    request: Request,
    current_user_id: str = Depends(verify_token)
):
    try:
        # 🔐 Get token from header
        auth_header = request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing token")
        token = auth_header.split(" ")[1]

        # ✅ Use user-authenticated Supabase client
        supabase_user = get_supabase_with_token(token)
        
        # First check if the requesting user has permission to view this profile
        # (Add your specific authorization logic here)
        # For example, you might want to restrict this to admin users only
        # or users with specific relationships
        
        # For now, we'll just verify the profile exists and return it
        response = supabase_user.table("profiles")\
            .select("*")\
            .eq("id", profile_id)\
            .single()\
            .execute()
            
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Profile not found"
            )
            
        return response.data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch profile: {str(e)}"
        )


@app.put("/profile")
async def update_profile(
    profile_data: dict,
    user_id: str = Depends(verify_token)
):
    try:
        response = supabase.table("profiles")\
            .update(profile_data)\
            .eq("id", user_id)\
            .execute()

        if response.error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to update profile"
            )

        return {
            "message": "Profile updated",
            "data": response.data
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Profile update failed: {str(e)}"
        )


@app.get("/analytics/prediction-trend")
async def prediction_trend(request: Request, user_id: str = Depends(verify_token), limit: int = 100):
    try:
        # 🔐 Get Bearer token from header
        auth_header = request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing token")
        token = auth_header.split(" ")[1]

        # ✅ Use authenticated Supabase client
        supabase_user = get_supabase_with_token(token)
        print("supabase user: ", supabase_user)
        print("👤 Authenticated user ID:", user_id)

        response = supabase_user.table("predictions")\
            .select("predicted_exp, created_at")\
            .eq("user_id", user_id)\
            .order("created_at", desc=True)\
            .limit(limit)\
            .execute()

        print("📊 Supabase raw response:", response)

        if not response.data:
            return []

        trend_data = [
            {
                "date": row["created_at"][:10],  # e.g., "2025-06-30"
                "predicted_exp": row["predicted_exp"]
            }
            for row in response.data if row["predicted_exp"] is not None
        ]

        return trend_data

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch prediction trend: {str(e)}"
        )


# Import the Api compare expenses and predictions
@app.post("/compare", response_model=ComparisonResult)
async def compare_expenses(
    request_data: ComparisonRequest,
    request: Request,
    user_id: str = Depends(verify_token)
):
    
    try:
        # Get authenticated Supabase client
        auth_header = request.headers.get("authorization")
        token = auth_header.split(" ")[1]
        supabase_user = get_supabase_with_token(token)

        # 1. Fetch the selected prediction
        prediction_res = supabase_user.table("predictions") \
            .select("*") \
            .eq("id", request_data.prediction.prediction_id) \
            .eq("user_id", user_id) \
            .single() \
            .execute()
        
        if not prediction_res.data:
            raise HTTPException(status_code=404, detail="Prediction not found")

        prediction = prediction_res.data
        
        # Initialize date variables
        start_date = None
        end_date = None

        # 2. Fetch selected expenses
        if request_data.expenses.expense_ids:
            # Compare specific selected expenses
            expenses_res = supabase_user.table("expenses") \
                .select("*") \
                .in_("id", request_data.expenses.expense_ids) \
                .eq("user_id", user_id) \
                .execute()
        else:
            if not request_data.expenses.month or not request_data.expenses.year:
                raise HTTPException(
                    status_code=422,
                    detail="Must provide either expense_ids or month/year"
                )
            # Add debug print
            print(f"Querying expenses between {start_date} and {end_date} for user {user_id}")
            # start_date = f"{request_data.expenses.year}-{request_data.expenses.month:02d}-01"
            # end_date = (datetime.strptime(start_date, "%Y-%m-%d") + timedelta(days=31)).strftime("%Y-%m-%d")
            
            # Calculate exact date range for the month
            _, last_day = monthrange(request_data.expenses.year, request_data.expenses.month)
            start_date = f"{request_data.expenses.year}-{request_data.expenses.month:02d}-01"
            end_date = f"{request_data.expenses.year}-{request_data.expenses.month:02d}-{last_day:02d}"
            
            expenses_res = supabase_user.table("expenses") \
                .select("*") \
                .eq("user_id", user_id) \
                .gte("date", start_date) \
                .lte("date", end_date) \
                .execute()

        expenses = expenses_res.data

        if not expenses:
            raise HTTPException(status_code=404, detail="No expenses found for comparison")

        # 3. Normalize time periods and calculate totals
        # Convert yearly prediction to monthly
        monthly_prediction = prediction["predicted_exp"] / 12
        
        # Calculate actual monthly spending (handling recurring expenses)
        actual_monthly = 0
        category_totals = defaultdict(float)
        recurring_adjustments = False

        for expense in expenses:
            amount = expense["amount"]
            
            # Handle recurring expenses
            if expense["is_recurring"]:
                recurring_adjustments = True
                interval = expense["recurrence_interval"]
                if interval == "weekly":
                    amount *= 4.33  # Approximate weeks in a month
                elif interval == "yearly":
                    amount /= 12
            
            actual_monthly += amount
            category_totals[expense["category"]] += amount

        # 4. Calculate variance
        variance = ((actual_monthly - monthly_prediction) / monthly_prediction) * 100
        
        # 5. Prepare category breakdown
        predicted_categories = {
            "Food": prediction["input_data"].get("Food_Expenditure", 0) / 12,
            "Housing": prediction["input_data"].get("Housing_Expenditure", 0) / 12,
            "Transport": prediction["input_data"].get("Transport_Expenditure", 0) / 12,
            "Utilities": prediction["input_data"].get("Utilities_Expenditure", 0) / 12,
            "Other": (prediction["input_data"].get("NonFood_Expenditure", 0) - 
                     prediction["input_data"].get("Transport_Expenditure", 0) -
                     prediction["input_data"].get("Utilities_Expenditure", 0)) / 12
        }

        category_comparisons = []
        for category, actual in category_totals.items():
            predicted = predicted_categories.get(category, 0)
            diff = actual - predicted
            percentage_diff = (diff / predicted) * 100 if predicted != 0 else 0
            category_comparisons.append({
                "category": category,
                "actual": round(actual, 2),
                "predicted": round(predicted, 2),
                "difference": round(diff, 2),
                "percentage_diff": round(percentage_diff, 2)
            })

        # 6. Determine comparison message
        if abs(variance) < 10:
            message = "Your spending aligns closely with predictions"
        elif variance > 0:
            message = f"You're spending {abs(variance):.1f}% more than predicted"
        else:
            message = f"You're spending {abs(variance):.1f}% less than predicted"

        # 7. Return comparison result
        return {
            "total_actual": round(actual_monthly, 2),
            "total_predicted_monthly": round(monthly_prediction, 2),
            "variance_percentage": round(variance, 2),
            "message": message,
            "category_breakdown": category_comparisons,
            "confidence_score": 75,  # Could come from model metadata
            "time_period_note": "Yearly prediction converted to monthly equivalent",
            "is_recurring_adjusted": recurring_adjustments
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Comparison failed: {str(e)}"
        )
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Depends, HTTPException, status, Request, APIRouter, BackgroundTasks
from collections import defaultdict
from fastapi.middleware.cors import CORSMiddleware
from auth.verify_token import verify_token
from schemes.expenditure import ExpenditureInput
from schemes.compare import ComparisonRequest, ComparisonResult
from schemes.analytics import ExpenseOverviewResponse, ExpenseCategoriesResponse, ExpenseTrendsResponse, Granularity, TrendDataPoint, PredictionSummary, PredictionOverviewResponse, InputCategoryItem, PredictionCategoriesResponse, PredictionTrendItem, PredictionTrendsResponse
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
from calendar import monthrange, month_name

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

# Analytics endpoints
# analytics/expense-overview
@app.get("/analytics/expense-overview", response_model=ExpenseOverviewResponse)
async def get_expense_overview(
    request: Request,
    period: str,  # Format: "YYYY-MM" for month or "YYYY" for year
    user_id: str = Depends(verify_token)
):
    """
    Get expense overview data for a specific period (month or year)
    
    Parameters:
    - period: Either "YYYY-MM" for monthly data or "YYYY" for yearly data
    - user_id: Authenticated user ID from token
    
    Returns:
    - Total amount spent
    - Transaction count
    - Recurring vs one-time breakdown
    - Essential vs non-essential breakdown
    - Top spending category
    - Average daily spending
    """
    try:
        # Get authenticated Supabase client
        auth_header = request.headers.get("authorization")
        token = auth_header.split(" ")[1]
        supabase_user = get_supabase_with_token(token)

        # Validate period format
        if len(period) == 7 and period[4] == '-':  # YYYY-MM format
            start_date = f"{period}-01"
            last_day = monthrange(int(period[:4]), int(period[5:7]))[1]
            end_date = f"{period}-{last_day:02d}"
            days_in_period = last_day
        elif len(period) == 4:  # YYYY format
            start_date = f"{period}-01-01"
            end_date = f"{period}-12-31"
            days_in_period = 366 if int(period) % 4 == 0 else 365  # Account for leap year
        else:
            raise HTTPException(
                status_code=400,
                detail="Invalid period format. Use YYYY-MM for month or YYYY for year"
            )

        # Fetch expenses for the period
        expenses_res = supabase_user.table("expenses") \
            .select("*") \
            .eq("user_id", user_id) \
            .gte("date", start_date) \
            .lte("date", end_date) \
            .execute()

        expenses = expenses_res.data

        if not expenses:
            return ExpenseOverviewResponse(
                total_amount=0,
                transaction_count=0,
                recurring_vs_one_time={"recurring": 0, "one_time": 0},
                essential_vs_non_essential={"essential": 0, "non_essential": 0},
                top_category="None",
                avg_daily_spending=0
            )

        # Calculate metrics
        total_amount = 0
        transaction_count = len(expenses)
        recurring = {"recurring": 0, "one_time": 0}
        essential = {"essential": 0, "non_essential": 0}
        categories = defaultdict(float)

        for expense in expenses:
            amount = expense["amount"]
            total_amount += amount

            # Handle recurring expenses
            if expense["is_recurring"]:
                interval = expense["recurrence_interval"]
                if interval == "weekly":
                    amount *= 4.33  # Approximate weeks in a month
                elif interval == "yearly":
                    amount /= 12
                recurring["recurring"] += amount
            else:
                recurring["one_time"] += amount

            # Handle essential expenses
            if expense["is_essential"]:
                essential["essential"] += amount
            else:
                essential["non_essential"] += amount

            # Track categories
            categories[expense["category"]] += amount

        # Determine top category
        top_category = max(categories.items(), key=lambda x: x[1])[0] if categories else "None"

        # Calculate average daily spending
        avg_daily = total_amount / days_in_period

        return ExpenseOverviewResponse(
            total_amount=round(total_amount, 2),
            transaction_count=transaction_count,
            recurring_vs_one_time={
                "recurring": round(recurring["recurring"], 2),
                "one_time": round(recurring["one_time"], 2)
            },
            essential_vs_non_essential={
                "essential": round(essential["essential"], 2),
                "non_essential": round(essential["non_essential"], 2)
            },
            top_category=top_category,
            avg_daily_spending=round(avg_daily, 2)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in expense overview: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate expense overview: {str(e)}"
        )

# analytics/expense-categories
@app.get("/analytics/expense-categories", response_model=ExpenseCategoriesResponse)
async def get_expense_categories(
    request: Request,
    period: str,  # Format: "YYYY-MM" for month or "YYYY" for year
    user_id: str = Depends(verify_token)
):
    """
    Get category breakdown for expenses in a specific period
    
    Parameters:
    - period: Either "YYYY-MM" for monthly data or "YYYY" for yearly data
    - user_id: Authenticated user ID from token
    
    Returns:
    - Period analyzed
    - Total amount spent
    - List of categories with:
      - Amount spent
      - Percentage of total
      - Number of transactions
    """
    try:
        # Get authenticated Supabase client
        auth_header = request.headers.get("authorization")
        token = auth_header.split(" ")[1]
        supabase_user = get_supabase_with_token(token)

        # Validate period and set date range
        if len(period) == 7 and period[4] == '-':  # YYYY-MM format
            start_date = f"{period}-01"
            last_day = monthrange(int(period[:4]), int(period[5:7]))[1]
            end_date = f"{period}-{last_day:02d}"
            period_label = f"{period[:4]} {month_name[int(period[5:7])]}"
        elif len(period) == 4:  # YYYY format
            start_date = f"{period}-01-01"
            end_date = f"{period}-12-31"
            period_label = period
        else:
            raise HTTPException(
                status_code=400,
                detail="Invalid period format. Use YYYY-MM for month or YYYY for year"
            )

        # Fetch expenses for the period
        expenses_res = supabase_user.table("expenses") \
            .select("*") \
            .eq("user_id", user_id) \
            .gte("date", start_date) \
            .lte("date", end_date) \
            .execute()

        expenses = expenses_res.data

        if not expenses:
            return ExpenseCategoriesResponse(
                period=period_label,
                total_amount=0,
                categories=[]
            )

        # Calculate category breakdown
        category_stats = defaultdict(lambda: {"amount": 0, "count": 0})
        total_amount = 0

        for expense in expenses:
            amount = expense["amount"]
            category = expense["category"]
            
            # Handle recurring expenses
            if expense["is_recurring"]:
                interval = expense["recurrence_interval"]
                if interval == "weekly":
                    amount *= 4.33  # Approximate weeks in a month
                elif interval == "yearly":
                    amount /= 12
            
            category_stats[category]["amount"] += amount
            category_stats[category]["count"] += 1
            total_amount += amount

        # Prepare response
        categories = []
        for category, stats in category_stats.items():
            percentage = (stats["amount"] / total_amount) * 100 if total_amount > 0 else 0
            categories.append({
                "category": category,
                "amount": round(stats["amount"], 2),
                "percentage": round(percentage, 2),
                "transaction_count": stats["count"]
            })

        # Sort by amount (descending)
        categories.sort(key=lambda x: x["amount"], reverse=True)

        return ExpenseCategoriesResponse(
            period=period_label,
            total_amount=round(total_amount, 2),
            categories=categories
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in expense categories: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate category breakdown: {str(e)}"
        )
        
# analytics/expense-trends
@app.get("/analytics/expense-trends", response_model=ExpenseTrendsResponse)
async def get_expense_trends(
    request: Request,
    period: str,            # Format: "YYYY-MM" or "YYYY"
    granularity: Granularity = Granularity.daily,
    user_id: str = Depends(verify_token)
):
    """
    Get time-series expense data for trend analysis
    
    Parameters:
    - period: "YYYY-MM" for month or "YYYY" for year
    - granularity: "daily" or "weekly" aggregation
    - user_id: Authenticated user ID
    
    Returns:
    - Formatted period label
    - Chosen granularity
    - Total amount for period
    - Time-series data points with:
      - Date/Week identifier
      - Amount spent
      - Transaction count
    """
    try:
        # Get authenticated Supabase client
        auth_header = request.headers.get("authorization")
        token = auth_header.split(" ")[1]
        supabase_user = get_supabase_with_token(token)

        # Validate period and set date range
        if len(period) == 7 and period[4] == '-':  # Monthly
            start_date = f"{period}-01"
            last_day = monthrange(int(period[:4]), int(period[5:7]))[1]
            end_date = f"{period}-{last_day:02d}"
            period_label = f"{period[:4]} {month_name[int(period[5:7])]}"
        elif len(period) == 4:  # Yearly
            start_date = f"{period}-01-01"
            end_date = f"{period}-12-31"
            period_label = period
        else:
            raise HTTPException(
                status_code=400,
                detail="Invalid period format. Use YYYY-MM or YYYY"
            )

        # Fetch raw expenses
        expenses_res = supabase_user.table("expenses") \
            .select("amount, date, is_recurring, recurrence_interval") \
            .eq("user_id", user_id) \
            .gte("date", start_date) \
            .lte("date", end_date) \
            .execute()

        expenses = expenses_res.data

        # Initialize time buckets
        date_format = "%Y-%m-%d"
        current = datetime.strptime(start_date, date_format)
        end = datetime.strptime(end_date, date_format)
        trends = {}

        # Create all possible time buckets first
        while current <= end:
            if granularity == Granularity.weekly:
                week_start = current - timedelta(days=current.weekday())
                week_end = week_start + timedelta(days=6)
                key = f"{week_start.strftime(date_format)} to {week_end.strftime(date_format)}"
                current = week_end + timedelta(days=1)  # Jump to next week
            else:  # daily
                key = current.strftime(date_format)
                current += timedelta(days=1)
            
            trends[key] = {"amount": 0, "count": 0}

        # Process expenses into buckets
        total_amount = 0
        for expense in expenses:
            amount = expense["amount"]
            date = expense["date"]
            
            # Handle recurring expenses
            if expense["is_recurring"]:
                interval = expense["recurrence_interval"]
                if interval == "weekly":
                    amount *= 0.142  # Daily equivalent (1/7)
                elif interval == "yearly":
                    amount /= 365
            
            # Determine time bucket
            expense_date = datetime.strptime(date, date_format)
            if granularity == Granularity.weekly:
                week_start = expense_date - timedelta(days=expense_date.weekday())
                week_end = week_start + timedelta(days=6)
                bucket_key = f"{week_start.strftime(date_format)} to {week_end.strftime(date_format)}"
            else:
                bucket_key = date
            
            # Add to bucket
            trends[bucket_key]["amount"] += amount
            trends[bucket_key]["count"] += 1
            total_amount += amount

        # Convert to response format
        trend_points = [
            TrendDataPoint(
                date=date_range,
                amount=round(stats["amount"], 2),
                transaction_count=stats["count"]
            )
            for date_range, stats in sorted(trends.items())
        ]

        return ExpenseTrendsResponse(
            period=period_label,
            granularity=granularity,
            total_amount=round(total_amount, 2),
            trends=trend_points
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in expense trends: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate trends: {str(e)}"
        )
        
        
# analytics/prediction-overview
@app.get("/analytics/prediction-overview", response_model=PredictionOverviewResponse)
async def get_prediction_overview(
    request: Request,
    user_id: str = Depends(verify_token)
):
    """
    Get summary of all predictions for a user
    
    Parameters:
    - user_id: Authenticated user ID
    
    Returns:
    - Total number of predictions
    - Average predicted amount
    - Average monthly equivalent
    - Details of latest prediction
    - Distribution of models used
    - Totals of input categories
    """
    try:
        # Get authenticated Supabase client
        auth_header = request.headers.get("authorization")
        token = auth_header.split(" ")[1]
        supabase_user = get_supabase_with_token(token)

        # Fetch all predictions
        predictions_res = supabase_user.table("predictions") \
            .select("*") \
            .eq("user_id", user_id) \
            .order("created_at", desc=True) \
            .execute()

        predictions = predictions_res.data

        if not predictions:
            return PredictionOverviewResponse(
                total_predictions=0,
                average_prediction=0,
                average_monthly=0,
                latest_prediction=None,
                model_distribution={},
                input_category_totals={}
            )

        # Calculate summary statistics
        total = len(predictions)
        sum_pred = sum(p["predicted_exp"] for p in predictions)
        avg_pred = sum_pred / total
        avg_monthly = avg_pred / 12

        # Model distribution
        models = defaultdict(int)
        for p in predictions:
            models[p["model_used"]] += 1

        # Input category totals (sum across all predictions)
        input_totals = defaultdict(float)
        for p in predictions:
            for key, value in p["input_data"].items():
                if key.endswith("_Expenditure"):
                    category = key.replace("_Expenditure", "").replace("_", " ")
                    input_totals[category] += value

        # Latest prediction details
        latest = predictions[0]
        monthly_equivalent = latest["predicted_exp"] / 12
        
        # Extract key inputs for summary
        input_summary = {
            "Region": latest["input_data"].get("Region"),
            "Residence": latest["input_data"].get("Residence_Type"),
            "Household Size": latest["input_data"].get("Number_of_Members"),
            "Main Expenses": {k: v for k, v in latest["input_data"].items() 
                            if k.endswith("_Expenditure") and v > 0}
        }

        return PredictionOverviewResponse(
            total_predictions=total,
            average_prediction=round(avg_pred, 2),
            average_monthly=round(avg_monthly, 2),
            latest_prediction=PredictionSummary(
                prediction_id=latest["id"],
                predicted_amount=round(latest["predicted_exp"], 2),
                monthly_equivalent=round(monthly_equivalent, 2),
                model_used=latest["model_used"],
                created_at=latest["created_at"],
                input_summary=input_summary
            ),
            model_distribution=dict(models),
            input_category_totals={k: round(v, 2) for k, v in input_totals.items()}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in prediction overview: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate prediction overview: {str(e)}"
        )
        
# analytics/prediction-categories
@app.get("/analytics/prediction-categories", response_model=PredictionCategoriesResponse)
async def get_prediction_categories(
    request: Request,
    user_id: str = Depends(verify_token)
):
    """
    Get breakdown of input categories used in predictions
    
    Parameters:
    - user_id: Authenticated user ID
    
    Returns:
    - Total number of predictions
    - List of input categories with:
      - Total amount across all predictions
      - Average amount per prediction
      - How many predictions used this category
      - Last used timestamp
    """
    try:
        # Get authenticated Supabase client
        auth_header = request.headers.get("authorization")
        token = auth_header.split(" ")[1]
        supabase_user = get_supabase_with_token(token)

        # Fetch all predictions
        predictions_res = supabase_user.table("predictions") \
            .select("id, input_data, created_at") \
            .eq("user_id", user_id) \
            .order("created_at", desc=True) \
            .execute()

        predictions = predictions_res.data

        if not predictions:
            return PredictionCategoriesResponse(
                total_predictions=0,
                categories=[]
            )

        # Process category data
        categories = defaultdict(lambda: {
            "total": 0,
            "count": 0,
            "last_used": "1970-01-01"
        })

        for pred in predictions:
            for key, value in pred["input_data"].items():
                if key.endswith("_Expenditure"):
                    # Clean category name (e.g., "Food_Expenditure" → "Food")
                    category = key.replace("_Expenditure", "").replace("_", " ")
                    
                    # Update category stats
                    categories[category]["total"] += float(value)
                    categories[category]["count"] += 1
                    
                    # Track most recent usage
                    if pred["created_at"] > categories[category]["last_used"]:
                        categories[category]["last_used"] = pred["created_at"]

        # Convert to response format
        category_list = []
        for name, stats in categories.items():
            category_list.append(InputCategoryItem(
                category=name,
                total_amount=round(stats["total"], 2),
                average_amount=round(stats["total"] / stats["count"], 2),
                prediction_count=stats["count"],
                last_used=stats["last_used"]
            ))

        # Sort by total amount (descending)
        category_list.sort(key=lambda x: x.total_amount, reverse=True)

        return PredictionCategoriesResponse(
            total_predictions=len(predictions),
            categories=category_list
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in prediction categories: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get prediction categories: {str(e)}"
        )
        
@app.get("/analytics/prediction-trends", response_model=PredictionTrendsResponse)
async def get_prediction_trends(
    request: Request,
    user_id: str = Depends(verify_token),
    limit: int = 100  # Default limit for safety
):
    """
    Get historical prediction data for trend analysis
    
    Parameters:
    - user_id: Authenticated user ID
    - limit: Maximum number of predictions to return
    
    Returns:
    - Total prediction count
    - Min/max/average amounts
    - Time-series data with:
      - Prediction details
      - Monthly equivalents
      - Model information
      - Key input summaries
    """
    try:
        # Get authenticated Supabase client
        auth_header = request.headers.get("authorization")
        token = auth_header.split(" ")[1]
        supabase_user = get_supabase_with_token(token)

        # Fetch predictions (newest first)
        predictions_res = supabase_user.table("predictions") \
            .select("id, predicted_exp, model_used, created_at, input_data") \
            .eq("user_id", user_id) \
            .order("created_at", desc=True) \
            .limit(limit) \
            .execute()

        predictions = predictions_res.data

        if not predictions:
            return PredictionTrendsResponse(
                total_predictions=0,
                min_amount=0,
                max_amount=0,
                average_amount=0,
                trends=[]
            )

        # Calculate summary stats
        amounts = [p["predicted_exp"] for p in predictions]
        total = len(predictions)
        min_amount = min(amounts)
        max_amount = max(amounts)
        avg_amount = sum(amounts) / total

        # Prepare trend items
        trend_items = []
        for pred in predictions:
            # Extract key inputs for summary
            inputs = pred["input_data"]
            input_summary = {
                "region": inputs.get("Region"),
                "residence": inputs.get("Residence_Type"),
                "household_size": inputs.get("Number_of_Members"),
                "main_categories": {
                    k.replace("_Expenditure", ""): v 
                    for k, v in inputs.items() 
                    if k.endswith("_Expenditure") and v > 0
                }
            }

            trend_items.append(PredictionTrendItem(
                prediction_id=pred["id"],
                created_at=pred["created_at"],
                predicted_amount=round(pred["predicted_exp"], 2),
                monthly_equivalent=round(pred["predicted_exp"] / 12, 2),
                model_used=pred["model_used"],
                input_summary=input_summary
            ))

        return PredictionTrendsResponse(
            total_predictions=total,
            min_amount=round(min_amount, 2),
            max_amount=round(max_amount, 2),
            average_amount=round(avg_amount, 2),
            trends=trend_items
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in prediction trends: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get prediction trends: {str(e)}"
        )
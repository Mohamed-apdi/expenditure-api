from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Depends, HTTPException, status, Request, APIRouter, BackgroundTasks
from collections import defaultdict
from fastapi.middleware.cors import CORSMiddleware
from auth.verify_token import verify_token
from schemes.expenditure import ExpenditureInput, PredictionOutput
from schemes.compare import ComparisonRequest, ComparisonResult, CategoryComparison, PredictionComparisonResult, PredictionComparisonRequest
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
from fastapi import BackgroundTasks
import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
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
    MODEL_PATH = os.path.join(os.path.dirname(__file__), "model", "gradient_boosting_with_categoricals.pkl")
    model = joblib.load(MODEL_PATH)
except Exception as e:
    raise RuntimeError(f"Failed to load model: {str(e)}")

# home page
@app.get("/")
async def health_check():
    return {"status": "healthy", "message": "Household Expenditure Predictor API"}


# OTP Functions
def generate_otp() -> str:
    return str(random.randint(100000, 999999))

def send_otp_email(email: str, otp: str):
    """Send OTP email using SMTP"""
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
      </body>
    </html>
    """
    
    message.attach(MIMEText(html, "html"))
    
    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, email, message.as_string())

def save_otp(email: str, otp: str):
    expires_at = datetime.utcnow() + timedelta(minutes=10)
    supabase.table("email_otp_verification").insert({
        "email": email,
        "otp": otp,
        "expires_at": expires_at.isoformat(),
        "verified": False
    }).execute()

# Models
class SignupRequest(BaseModel):
    email: str
    password: str
    full_name: str
    otp: str

class OtpRequest(BaseModel):
    email: str

# Endpoints
@app.post("/auth/request-signup-otp")
async def request_signup_otp(request: OtpRequest, background_tasks: BackgroundTasks):
    # Check if email already exists
    user_check = supabase.table("auth.users")\
        .select("email")\
        .eq("email", request.email)\
        .maybe_single()\
        .execute()
    
    if user_check.data:
        raise HTTPException(status_code=400, detail="Email already registered")

    # Generate and send OTP
    otp = generate_otp()
    background_tasks.add_task(send_otp_email, request.email, otp)
    background_tasks.add_task(save_otp, request.email, otp)
    
    return {"message": "OTP sent to email"}

@app.post("/auth/verify-and-signup")
async def verify_and_signup(request: SignupRequest):
    # Verify OTP first
    result = supabase.table("email_otp_verification")\
        .select("*")\
        .eq("email", request.email)\
        .eq("otp", request.otp)\
        .eq("verified", False)\
        .maybe_single()\
        .execute()

    if not result.data:
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")

    expires_at = datetime.fromisoformat(result.data["expires_at"])
    if datetime.utcnow() > expires_at:
        raise HTTPException(status_code=400, detail="OTP expired")

    # Mark OTP as verified
    supabase.table("email_otp_verification")\
        .update({"verified": True})\
        .eq("id", result.data["id"])\
        .execute()

    # Create user with Supabase Auth
    auth_response = supabase.auth.sign_up({
        "email": request.email,
        "password": request.password,
        "options": {
            "data": {
                "full_name": request.full_name,
                "email_verified": True  # Mark as verified since we verified via OTP
            }
        }
    })

    if auth_response.error:
        raise HTTPException(status_code=400, detail=auth_response.error.message)

    return {"message": "Account created successfully"}


# Safely handles prediction with early return for empty/zero inputs
def safe_predict_with_categoricals(model, input_dict):
    """
    Safely handles prediction with early return for empty/zero inputs
    Args:
        model: The loaded ML model
        input_dict: Dictionary containing all input fields
    Returns:
        float: Predicted value (0 if all inputs are empty/zero)
    """
    # Define which fields are numeric
    numeric_fields = [
        "exp_food", "exp_rent", "exp_Education", "exp_Water",
        "exp_Electricity", "Savings_or_Insurance_Payment", "Communication_Exp", "hhsize"
    ]
    
    # Check if all numeric fields are 0 and strings are empty
    all_numeric_zero = all(input_dict.get(field, 0) == 0 for field in numeric_fields)
    area_empty = input_dict.get("Area_Name", "").strip() == ""
    region_empty = input_dict.get("Region_Name", "").strip() == ""

    # If everything is empty/zero, return 0 directly
    if all_numeric_zero and area_empty and region_empty:
        return 0.0

    # Prepare data for prediction
    input_df = pd.DataFrame([[
        input_dict["exp_food"],
        input_dict["exp_rent"],
        input_dict["exp_Education"],
        input_dict["exp_Water"],
        input_dict["exp_Electricity"],
        input_dict["Savings_or_Insurance_Payment"],
        input_dict["Communication_Exp"],
        input_dict["hhsize"],
        input_dict["Area_Name"],
        input_dict["Region_Name"]
    ]], columns=[
        "exp_food",
        "exp_rent",
        "exp_Education",
        "exp_Water",
        "exp_Electricity",
        "Savings_or_Insurance_Payment",
        "Communication_Exp",
        "hhsize",
        "Area_Name",
        "Region_Name"
    ])

    # Make prediction
    return model.predict(input_df)[0]

@app.post("/predict", response_model=PredictionOutput)
async def predict(
    request: Request,
    data: ExpenditureInput,
    user_id: str = Depends(verify_token)
):
    try:
        # Get authenticated Supabase client
        auth_header = request.headers.get("authorization")
        token = auth_header.split(" ")[1]
        supabase_user = get_supabase_with_token(token)

        # Convert input to dictionary
        input_dict = data.dict()
        print("Incoming data:", input_dict)
        
        # Use safe prediction function
        pred = safe_predict_with_categoricals(model, input_dict)
        print("Raw model output:", pred)
        rounded_pred = float(round(pred, 2))
        
        # Calculate monthly equivalent
        monthly_equivalent = round(rounded_pred / 12, 2)

        # Store prediction
        response = supabase_user.table("predictions").insert({
            "input_data": input_dict,
            "predicted_exp": rounded_pred,
            "model_used": "GradientBoosting",
            "user_id": user_id
        }).execute()

        if hasattr(response, 'error') and response.error:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save prediction"
            )

        return {
            "predicted_expenditure": rounded_pred,
            "monthly_equivalent": monthly_equivalent,
            "input_data": input_dict
        }

    except Exception as e:
        import traceback
        print(f"Error details:\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Prediction failed: {str(e)}"
        )


@app.put("/predictions/{prediction_id}", response_model=PredictionOutput)
async def update_prediction(
    prediction_id: str,
    request: Request,
    updated_data: ExpenditureInput,
    user_id: str = Depends(verify_token)
):
    try:
        # Get authenticated Supabase client
        auth_header = request.headers.get("authorization")
        token = auth_header.split(" ")[1]
        supabase_user = get_supabase_with_token(token)

        # Verify prediction exists
        existing_pred = supabase_user.table("predictions") \
            .select("*") \
            .eq("id", prediction_id) \
            .eq("user_id", user_id) \
            .maybe_single() \
            .execute()

        if not existing_pred.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Prediction not found or not owned by user"
            )

        # Prepare data for prediction
        input_dict = updated_data.dict()
        # Use safe prediction function
        pred = safe_predict_with_categoricals(model, input_dict)
        rounded_pred = float(round(pred, 2))
        monthly_equivalent = round(rounded_pred / 12, 2)
        print("Updated model output:", rounded_pred)

        # Update the prediction
        update_response = supabase_user.table("predictions") \
            .update({
                "input_data": input_dict,
                "predicted_exp": rounded_pred,
                "updated_at": "now()"
            }) \
            .eq("id", prediction_id) \
            .execute()

        if hasattr(update_response, 'error') and update_response.error:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update prediction"
            )

        return {
            "predicted_expenditure": rounded_pred,
            "monthly_equivalent": monthly_equivalent,
            "input_data": input_dict
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"Error updating prediction: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update prediction: {str(e)}"
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

        # 2. Validate month/year selection
        if not request_data.expenses.month or not request_data.expenses.year:
            raise HTTPException(
                status_code=422,
                detail="Must provide both month and year for comparison"
            )

        # 3. Calculate date range for the month
        _, last_day = monthrange(request_data.expenses.year, request_data.expenses.month)
        start_date = f"{request_data.expenses.year}-{request_data.expenses.month:02d}-01"
        end_date = f"{request_data.expenses.year}-{request_data.expenses.month:02d}-{last_day:02d}"
        
        # 4. Fetch expenses for the selected month
        expenses_res = supabase_user.table("expenses") \
            .select("*") \
            .eq("user_id", user_id) \
            .gte("date", start_date) \
            .lte("date", end_date) \
            .execute()

        expenses = expenses_res.data

        if not expenses:
            return ComparisonResult(
                total_actual=0,
                total_predicted_monthly=0,
                variance_percentage=0,
                message="No expenses found for selected month",
                category_breakdown=[],
                confidence_score=None,
                time_period_note=f"No expenses in {month_name[request_data.expenses.month]} {request_data.expenses.year}",
                is_recurring_adjusted=False
            )

        # 5. Calculate actual monthly spending (with recurring adjustments)
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
                    amount /= 12    # Convert yearly to monthly
            
            actual_monthly += amount
            category_totals[expense["category"]] += amount

        # 6. Prepare predicted values
        # Yearly total converted to monthly
        monthly_predicted_total = prediction["predicted_exp"] / 12
        
        # Predicted categories (already monthly values)
        predicted_categories = {
            "Food": prediction["input_data"].get("exp_food", 0),
            "Housing": prediction["input_data"].get("exp_rent", 0),
            "Education": prediction["input_data"].get("exp_Education", 0),
            "Utilities": (prediction["input_data"].get("exp_Water", 0) + 
                         prediction["input_data"].get("exp_Electricity", 0)),
            "Communication": prediction["input_data"].get("Communication_Exp", 0),
            "Savings": prediction["input_data"].get("Savings_or_Insurance_Payment", 0),
            "Other": 0  # Will calculate remaining
        }

        # Calculate "Other" category as remaining predicted amount
        predicted_sum = sum(predicted_categories.values())
        predicted_categories["Other"] = max(0, monthly_predicted_total - predicted_sum)

        # 7. Prepare category breakdown
        category_comparisons = []
        all_categories = set(category_totals.keys()).union(set(predicted_categories.keys()))
        
        for category in all_categories:
            actual = category_totals.get(category, 0)
            predicted = predicted_categories.get(category, 0)
            diff = actual - predicted
            percentage_diff = (diff / predicted) * 100 if predicted != 0 else 0
            
            category_comparisons.append(CategoryComparison(
                category=category,
                actual=round(actual, 2),
                predicted=round(predicted, 2),
                difference=round(diff, 2),
                percentage_diff=round(percentage_diff, 2)
            ))

        # Sort categories by absolute difference (most significant first)
        category_comparisons.sort(key=lambda x: abs(x.difference), reverse=True)

        # 8. Calculate overall variance
        if monthly_predicted_total == 0:
            variance_pct = 0
            message = "No predicted amount available for comparison"
        else:
            variance_pct = ((actual_monthly - monthly_predicted_total) / monthly_predicted_total) * 100
            if abs(variance_pct) < 10:
                message = "Your spending aligns closely with predictions"
            elif variance_pct > 0:
                message = f"You're spending {abs(variance_pct):.1f}% more than predicted"
            else:
                message = f"You're spending {abs(variance_pct):.1f}% less than predicted"

        # 9. Return comparison result
        return ComparisonResult(
            total_actual=round(actual_monthly, 2),
            total_predicted_monthly=round(monthly_predicted_total, 2),
            variance_percentage=round(variance_pct, 2),
            message=message,
            category_breakdown=category_comparisons,
            confidence_score=75,
            time_period_note=f"Comparing {month_name[request_data.expenses.month]} {request_data.expenses.year} expenses with predicted monthly amounts",
            is_recurring_adjusted=recurring_adjustments
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Comparison failed: {str(e)}", exc_info=True)
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
        
        
@app.post("/compare-predictions", response_model=PredictionComparisonResult)
async def compare_predictions(
    request_data: PredictionComparisonRequest,
    request: Request,
    user_id: str = Depends(verify_token)
):
    """Compare two predictions by ID, showing differences in totals and by category"""
    try:
        # Get authenticated Supabase client
        auth_header = request.headers.get("authorization")
        token = auth_header.split(" ")[1]
        supabase_user = get_supabase_with_token(token)

        # Fetch both predictions
        pred1_res = supabase_user.table("predictions") \
            .select("*") \
            .eq("id", request_data.prediction1_id) \
            .eq("user_id", user_id) \
            .single() \
            .execute()
        
        pred2_res = supabase_user.table("predictions") \
            .select("*") \
            .eq("id", request_data.prediction2_id) \
            .eq("user_id", user_id) \
            .single() \
            .execute()

        if not pred1_res.data or not pred2_res.data:
            raise HTTPException(status_code=404, detail="One or both predictions not found")

        pred1 = pred1_res.data
        pred2 = pred2_res.data

        # Calculate time difference between predictions
        created_at_diff = None
        try:
            date1 = datetime.fromisoformat(pred1["created_at"])
            date2 = datetime.fromisoformat(pred2["created_at"])
            delta = abs(date2 - date1)
            
            if delta.days > 365:
                created_at_diff = f"{delta.days//365} years apart"
            elif delta.days > 30:
                created_at_diff = f"{delta.days//30} months apart"
            elif delta.days > 0:
                created_at_diff = f"{delta.days} days apart"
            elif delta.seconds > 3600:
                created_at_diff = f"{delta.seconds//3600} hours apart"
            else:
                created_at_diff = "created at similar times"
        except:
            pass  # Don't fail if date parsing fails

        # Calculate totals and differences
        pred1_total = pred1["predicted_exp"]
        pred2_total = pred2["predicted_exp"]
        abs_diff = pred2_total - pred1_total
        pct_diff = (abs_diff / pred1_total) * 100 if pred1_total != 0 else 0

        # Prepare category breakdown
        category_comparisons = []
        common_categories = {
            "Food": ("exp_food", "exp_food"),
            "Housing": ("exp_rent", "exp_rent"),
            "Education": ("exp_Education", "exp_Education"),
            "Utilities": (["exp_Water", "exp_Electricity"], ["exp_Water", "exp_Electricity"]),
            "Communication": ("Communication_Exp", "Communication_Exp"),
            "Savings": ("Savings_or_Insurance_Payment", "Savings_or_Insurance_Payment")
        }

        for category, (fields1, fields2) in common_categories.items():
            # Handle multi-field categories (like Utilities)
            def get_amount(pred, fields):
                if isinstance(fields, list):
                    return sum(pred["input_data"].get(f, 0) for f in fields)
                return pred["input_data"].get(fields, 0)

            amount1 = get_amount(pred1, fields1)
            amount2 = get_amount(pred2, fields2)
            diff = amount2 - amount1
            pct = (diff / amount1) * 100 if amount1 != 0 else 0

            category_comparisons.append(CategoryComparison(
                category=category,
                actual=round(amount2, 2),
                predicted=round(amount1, 2),
                difference=round(diff, 2),
                percentage_diff=round(pct, 2)
            ))

        # Generate comparison message
        if abs_diff > 0:
            message = f"Second prediction is {abs(pct_diff):.1f}% higher than the first"
        else:
            message = f"Second prediction is {abs(pct_diff):.1f}% lower than the first"

        return PredictionComparisonResult(
            prediction1_total=round(pred1_total, 2),
            prediction2_total=round(pred2_total, 2),
            absolute_difference=round(abs_diff, 2),
            percentage_difference=round(pct_diff, 2),
            category_breakdown=category_comparisons,
            comparison_message=message,
            created_at_difference=created_at_diff
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Prediction comparison failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Prediction comparison failed: {str(e)}"
        )
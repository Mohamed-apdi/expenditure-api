from fastapi import FastAPI, Depends, HTTPException, status, Request, APIRouter
from collections import defaultdict
from fastapi.middleware.cors import CORSMiddleware
from auth.verify_token import verify_token
from schemes.expenditure import ExpenditureInput
from supabase_config.client import supabase
from supabase_config.auth_client import get_supabase_with_token
import joblib
import numpy as np
import pandas as pd
import os
from typing import Optional
from dotenv import load_dotenv
from pydantic import BaseModel


# Load environment variables
load_dotenv()

app = FastAPI()

# CORS Configuration (Essential for React Native)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load model safely
try:
    MODEL_PATH = os.path.join(os.path.dirname(__file__), "model", "model_household_expenditure.pkl")
    model = joblib.load(MODEL_PATH)
except Exception as e:
    raise RuntimeError(f"Failed to load model: {str(e)}")

@app.get("/")
async def health_check():
    return {"status": "healthy", "message": "Household Expenditure Predictor API"}

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
        log_pred = model.predict(input_df)[0]
        prediction = np.expm1(log_pred)
        rounded_pred = float(round(prediction, 2))

        # Store prediction
        response = supabase_user.table("predictions").insert({
            "input_data": data.dict(),
            "predicted_exp": rounded_pred,
            "model_used": "GB",
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
async def get_profile(user_id: str = Depends(verify_token)):
    try:
        response = supabase.table("profiles")\
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



@app.get("/analytics/monthly-average")
async def monthly_average(
    request: Request,
    user_id: str = Depends(verify_token),
    limit: int = 1000  # optional cap
):
    try:
        # 🔐 Get token from header
        auth_header = request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing token")
        token = auth_header.split(" ")[1]

        # ✅ Use user-authenticated Supabase client
        supabase_user = get_supabase_with_token(token)

        # 🗂️ Fetch predictions
        response = supabase_user.table("predictions")\
            .select("predicted_exp, created_at")\
            .eq("user_id", user_id)\
            .order("created_at", desc=True)\
            .limit(limit)\
            .execute()

        if not response.data:
            return []

        # 📅 Group by year-month and calculate averages
        monthly_data = defaultdict(list)
        for row in response.data:
            if row["predicted_exp"] is not None:
                month_key = row["created_at"][:7]  # "YYYY-MM"
                monthly_data[month_key].append(row["predicted_exp"])

        average_per_month = [
            {
                "month": month,
                "average_predicted_exp": round(sum(values) / len(values), 2)
            }
            for month, values in sorted(monthly_data.items(), reverse=True)
        ]

        return average_per_month

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch monthly averages: {str(e)}"
        )
        
        
@app.get("/analytics/total-count")
async def total_prediction_count(
    request: Request, 
    user_id: str = Depends(verify_token)
):
    try:
        # 🔐 Get Bearer token
        auth_header = request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing token")
        token = auth_header.split(" ")[1]

        # ✅ Authenticated Supabase client
        supabase_user = get_supabase_with_token(token)

        # 📊 Query count
        response = supabase_user.table("predictions")\
            .select("id", count="exact")\
            .eq("user_id", user_id)\
            .execute()

        if response.error:
            raise HTTPException(status_code=500, detail="Failed to count predictions")

        return { "total_predictions": response.count }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.get("/analytics/expense-breakdown")
async def expense_breakdown(
    request: Request, 
    user_id: str = Depends(verify_token)
):
    try:
        # 🔐 Get token
        auth_header = request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing token")
        token = auth_header.split(" ")[1]

        # ✅ Authenticated client
        supabase_user = get_supabase_with_token(token)

        # 📥 Fetch predictions for the user
        response = supabase_user.table("predictions")\
            .select("input_data")\
            .eq("user_id", user_id)\
            .execute()

        if not response.data:
            return {
                "food": 0,
                "rent": 0,
                "other": 0
            }

        food_total = 0
        rent_total = 0
        other_total = 0

        for row in response.data:
            input_data = row.get("input_data", {})
            food_total += float(input_data.get("food_exp", 0))
            rent_total += float(input_data.get("rent_exp", 0))
            other_total += float(input_data.get("other_exp", 0))

        return {
            "food": round(food_total, 2),
            "rent": round(rent_total, 2),
            "other": round(other_total, 2)
        }

    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to compute breakdown: {str(e)}"
        )


from datetime import datetime, timedelta

@app.get("/analytics/recent")
async def recent_predictions(
    request: Request,
    user_id: str = Depends(verify_token)
):
    try:
        # 🔐 Get token
        auth_header = request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing token")
        token = auth_header.split(" ")[1]

        # ✅ Authenticated Supabase client
        supabase_user = get_supabase_with_token(token)

        # 📅 7 days ago date (ISO format)
        seven_days_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()

        # 📥 Query predictions after 7 days ago
        response = supabase_user.table("predictions")\
            .select("predicted_exp, created_at")\
            .eq("user_id", user_id)\
            .gte("created_at", seven_days_ago)\
            .order("created_at", desc=True)\
            .execute()

        if response.error:
            raise HTTPException(status_code=500, detail="Failed to fetch recent predictions")

        return [
            {
                "date": row["created_at"][:10],
                "predicted_exp": row["predicted_exp"]
            }
            for row in response.data if row["predicted_exp"] is not None
        ]

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching recent predictions: {str(e)}"
        )



@app.get("/analytics/peak-day")
async def get_peak_prediction_day(
    request: Request,
    user_id: str = Depends(verify_token)
):
    try:
        # 🔐 Extract token
        auth_header = request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing token")
        token = auth_header.split(" ")[1]

        # ✅ Authenticated Supabase client
        supabase_user = get_supabase_with_token(token)

        # 🔍 Query predictions sorted by predicted_exp descending
        response = supabase_user.table("predictions")\
            .select("predicted_exp, created_at")\
            .eq("user_id", user_id)\
            .order("predicted_exp", desc=True)\
            .limit(1)\
            .execute()

        if response.error or not response.data:
            raise HTTPException(status_code=404, detail="No predictions found")

        peak = response.data[0]

        return {
            "peak_date": peak["created_at"][:10],  # YYYY-MM-DD
            "predicted_exp": peak["predicted_exp"]
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get peak day: {str(e)}"
        )
class ScenarioCreate(BaseModel):
    prediction_id: str
    name: Optional[str] = None
    

@app.get("/scenarios")
async def get_scenarios(request: Request, user_id: str = Depends(verify_token)):
    try:
        # Get authenticated Supabase client
        auth_header = request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing token")
        token = auth_header.split(" ")[1]
        supabase_user = get_supabase_with_token(token)
        
        # Get all scenarios for user with their prediction data
        response = supabase_user.rpc("get_user_scenarios", {"user_id_param": user_id}).execute()
        
        if response.error:
            raise HTTPException(status_code=500, detail="Failed to fetch scenarios")
            
        return response.data
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch scenarios: {str(e)}")
    
    
def calculate_confidence(input_data):
    """Calculate confidence score based on input completeness"""
    required_fields = [
        'exp_food', 'exp_nfnd', 'exp_rent', 
        'hhsize', 'region_n', 'hh_water_type'
    ]
    
    filled = sum(1 for field in required_fields 
               if field in input_data and input_data[field] not in [0, None, ""])
    
    confidence = min(100, int((filled / len(required_fields)) * 100))
    
    # Boost confidence if all financial fields are filled
    if all(input_data.get(f, 0) > 0 for f in ['exp_food', 'exp_nfnd', 'exp_rent']):
        confidence = min(100, confidence + 20)
        
    return confidence

@app.post("/scenarios")
async def create_scenario(
    scenario_data: ScenarioCreate,
    request: Request,
    user_id: str = Depends(verify_token)
):
    try:
        # Get authenticated Supabase client
        auth_header = request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing token")
        token = auth_header.split(" ")[1]
        supabase_user = get_supabase_with_token(token)
        
        print(f"Attempting to create scenario for user {user_id} with prediction {scenario_data.prediction_id}")  # Debug
        
        # Verify prediction exists and belongs to user
        try:
            pred_response = supabase_user.table("predictions") \
                .select("*") \
                .eq("id", scenario_data.prediction_id) \
                .eq("user_id", user_id) \
                .single() \
                .execute()
                
            if not pred_response.data:
                print(f"Prediction not found: {scenario_data.prediction_id}")
                raise HTTPException(
                    status_code=404,
                    detail="Prediction not found or doesn't belong to user"
                )
                
            print(f"Found prediction: {pred_response.data}")  # Debug
        except Exception as e:
            print(f"Prediction lookup error: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Error verifying prediction: {str(e)}"
            )

        # Calculate confidence
        try:
            confidence = calculate_confidence(pred_response.data["input_data"])
            print(f"Calculated confidence: {confidence}")  # Debug
        except Exception as e:
            print(f"Confidence calculation error: {str(e)}")
            confidence = 50  # Default value if calculation fails

        # Create scenario record
        scenario_record = {
            "user_id": user_id,
            "prediction_id": scenario_data.prediction_id,
            "name": scenario_data.name or f"Scenario {datetime.now().strftime('%Y-%m-%d')}",
            "confidence": confidence
        }

        print(f"Attempting to insert: {scenario_record}")  # Debug
        
        # Insert scenario
        try:
            insert_response = supabase_user.table("scenarios")\
                .insert(scenario_record)\
                .execute()
                
            if not insert_response.data:
                print("Empty response from Supabase insert")
                raise HTTPException(
                    status_code=500,
                    detail="Scenario creation failed - no data returned"
                )
                
            print(f"Successfully created scenario: {insert_response.data[0]}")  # Debug
            return insert_response.data[0]
            
        except Exception as e:
            print(f"Insert error: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create scenario in database: {str(e)}"
            )
            
    except HTTPException as he:
        print(f"HTTPException: {he.detail}")
        raise
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error creating scenario: {str(e)}"
        )

@app.post("/scenarios/{scenario_id}/set-active")
async def set_active_scenario(
    scenario_id: str,
    user_id: str = Depends(verify_token)
):
    try:
        # First deactivate all other scenarios
        supabase.table("scenarios")\
            .update({"is_active": False})\
            .eq("user_id", user_id)\
            .execute()
            
        # Then activate this one
        response = supabase.table("scenarios")\
            .update({"is_active": True})\
            .eq("id", scenario_id)\
            .eq("user_id", user_id)\
            .execute()
            
        if response.error:
            raise HTTPException(status_code=500, detail="Failed to set active scenario")
            
        return {"success": True}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to set active scenario: {str(e)}")

@app.delete("/scenarios/{scenario_id}")
async def delete_scenario(
    scenario_id: str,
    user_id: str = Depends(verify_token)
):
    try:
        response = supabase.table("scenarios")\
            .delete()\
            .eq("id", scenario_id)\
            .eq("user_id", user_id)\
            .execute()
            
        if response.error:
            raise HTTPException(status_code=500, detail="Failed to delete scenario")
            
        return {"success": True}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete scenario: {str(e)}")


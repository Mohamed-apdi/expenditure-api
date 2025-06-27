from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from auth.verify_token import verify_token
from schemes.expenditure import ExpenditureInput
from supabase_config.client import supabase
import joblib
import numpy as np
import pandas as pd
import os
from typing import Optional
from dotenv import load_dotenv

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
    data: ExpenditureInput, 
    # user_id: str = Depends(verify_token)
):
    try:
        print("Incoming data:", data.dict())
        # Convert input to DataFrame
        input_df = pd.DataFrame([data.dict()])
        
        # Make prediction
        log_pred = model.predict(input_df)[0]
        prediction = np.expm1(log_pred)
        rounded_pred = float(round(prediction, 2))

        # Store prediction
        response = supabase.table("predictions").insert({
            "input_data": data.dict(),
            "predicted_exp": rounded_pred,
            "model_used": "GB",
            # "user_id": user_id
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
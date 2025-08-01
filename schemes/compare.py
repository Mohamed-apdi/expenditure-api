from pydantic import BaseModel, model_validator, field_validator
from typing import List, Optional, Union
from pydantic import ConfigDict

class ExpenseSelection(BaseModel):
    month: int  # 1-12 (required)
    year: int   # required

    @field_validator('month')
    def month_must_be_valid(cls, v):
        if v < 1 or v > 12:
            raise ValueError("Month must be between 1 and 12")
        return v
    
    

class PredictionSelection(BaseModel):
    prediction_id: str
    
    @field_validator('prediction_id')
    def validate_prediction_id(cls, v):
        if not v or not isinstance(v, str):
            raise ValueError("Prediction ID must be a non-empty string")
        return v

class ComparisonRequest(BaseModel):
    expenses: ExpenseSelection
    prediction: PredictionSelection

class CategoryComparison(BaseModel):
    category: str
    actual: float
    predicted: float
    difference: float
    percentage_diff: float

class ComparisonResult(BaseModel):
    total_actual: float
    total_predicted_monthly: float
    variance_percentage: float
    message: str
    category_breakdown: List[CategoryComparison]
    confidence_score: Optional[float] = None
    time_period_note: str
    is_recurring_adjusted: bool
    model_config = ConfigDict(protected_namespaces=())
    
    
# compare predictions
from typing import Annotated
from fastapi import Body

class PredictionComparisonRequest(BaseModel):
    """Request body for comparing two predictions"""
    prediction1_id: str
    prediction2_id: str
    
    @field_validator('prediction1_id', 'prediction2_id')
    def validate_prediction_ids(cls, v):
        if not v or not isinstance(v, str):
            raise ValueError("Prediction ID must be a non-empty string")
        return v

class PredictionComparisonResult(BaseModel):
    """Result of comparing two predictions"""
    prediction1_total: float
    prediction2_total: float
    absolute_difference: float
    percentage_difference: float
    category_breakdown: List[CategoryComparison]
    comparison_message: str
    created_at_difference: Optional[str]
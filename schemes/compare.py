from pydantic import BaseModel, model_validator, field_validator
from typing import List, Optional, Union
from pydantic import ConfigDict


class ExpenseSelection(BaseModel):
    expense_ids: Optional[List[str]] = None
    month: Optional[int] = None  # 1-12
    year: Optional[int] = None

    @field_validator('month')
    def month_must_be_valid(cls, v):
        if v is not None and (v < 1 or v > 12):
            raise ValueError("Month must be between 1 and 12")
        return v

    @model_validator(mode='after')
    def check_exclusive_fields(self):
        expense_ids = self.expense_ids
        month = self.month
        year = self.year
        
        if expense_ids and (month or year):
            raise ValueError("Cannot specify both expense_ids and month/year")
        if not expense_ids and not (month and year):
            raise ValueError("Must specify either expense_ids or both month/year")
        return self

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
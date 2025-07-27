# ALL analytics classes
from typing import List, Dict
from pydantic import BaseModel
from enum import Enum

class Granularity(str, Enum):
    daily = "daily"
    weekly = "weekly"

class TrendDataPoint(BaseModel):
    date: str
    amount: float
    transaction_count: int

class ExpenseTrendsResponse(BaseModel):
    period: str
    granularity: str
    total_amount: float
    trends: List[TrendDataPoint]

class ExpenseOverviewResponse(BaseModel):
    total_amount: float
    transaction_count: int
    recurring_vs_one_time: dict
    essential_vs_non_essential: dict
    top_category: str
    avg_daily_spending: float
    

class CategoryBreakdownItem(BaseModel):
    category: str
    amount: float
    percentage: float
    transaction_count: int

class ExpenseCategoriesResponse(BaseModel):
    period: str
    total_amount: float
    categories: list[CategoryBreakdownItem]
    

class Granularity(str, Enum):
    daily = "daily"
    weekly = "weekly"

class TrendDataPoint(BaseModel):
    date: str
    amount: float
    transaction_count: int

class ExpenseTrendsResponse(BaseModel):
    period: str
    granularity: str
    total_amount: float
    trends: List[TrendDataPoint]
    
class PredictionSummary(BaseModel):
    prediction_id: str
    predicted_amount: float
    monthly_equivalent: float
    model_used: str
    created_at: str
    input_summary: dict

class PredictionOverviewResponse(BaseModel):
    total_predictions: int
    average_prediction: float
    average_monthly: float
    latest_prediction: PredictionSummary
    model_distribution: Dict[str, int]
    input_category_totals: Dict[str, float]
    
class InputCategoryItem(BaseModel):
    category: str
    total_amount: float
    average_amount: float
    prediction_count: int
    last_used: str

class PredictionCategoriesResponse(BaseModel):
    total_predictions: int
    categories: List[InputCategoryItem]

class PredictionTrendItem(BaseModel):
    prediction_id: str
    created_at: str
    predicted_amount: float
    monthly_equivalent: float
    model_used: str
    input_summary: dict

class PredictionTrendsResponse(BaseModel):
    total_predictions: int
    min_amount: float
    max_amount: float
    average_amount: float
    trends: List[PredictionTrendItem]
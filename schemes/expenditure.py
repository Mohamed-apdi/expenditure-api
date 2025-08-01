from pydantic import BaseModel

class ExpenditureInput(BaseModel):
    exp_food: float
    exp_rent: float
    exp_Education: float
    exp_Water: float
    exp_Electricity: float
    Savings_or_Insurance_Payment: float
    Communication_Exp: float
    hhsize: int
    Area_Name: str
    Region_Name: str
    
class PredictionOutput(BaseModel):
    predicted_expenditure: float
    input_data: dict
    monthly_equivalent: float
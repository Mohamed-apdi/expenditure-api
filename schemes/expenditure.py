from pydantic import BaseModel

class ExpenditureInput(BaseModel):
    Food_Expenditure: float
    NonFood_Expenditure: float
    Housing_Expenditure: float
    Utilities_Expenditure: float
    Transport_Expenditure: float
    Number_of_Members: int
    Region: str
    Residence_Type: str
    Spent_on_Food_Drink_Outside: float
    General_NonFood_Expenditure: float
    Livestock_Byproducts_Value: float
    Business_Revenue: float
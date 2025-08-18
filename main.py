from datetime import datetime, timedelta
from fastapi import FastAPI, Depends, HTTPException, status, Request
from collections import defaultdict
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from auth.verify_token import verify_token
from supabase_config.client import supabase
from supabase_config.auth_client import get_supabase_with_token
from config import config
import logging
import time
import csv
import io
import json
from calendar import monthrange, month_name
from typing import List, Dict, Optional
from schemes.analytics import *
from schemes.expenditure import *
from schemes.compare import *

# Validate configuration
try:
    config.validate()
    config.print_config()
except ValueError as e:
    print(f"❌ Configuration Error: {e}")
    print("Please check your .env file and ensure SUPABASE_URL and SUPABASE_KEY are set.")
    exit(1)

app = FastAPI(
    title="Household Expenditure API",
    description="Comprehensive financial management and reporting API",
    version="1.0.0"
)

# CORS Configuration (Essential for React Native)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging at module level
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("startup")
async def startup_event():
    """Application startup event"""
    logger.info("🚀 Household Expenditure API starting up...")
    
    # Check if Supabase client is available
    if supabase is None:
        logger.error("❌ Supabase client not initialized")
        logger.error("Please check your SUPABASE_URL and SUPABASE_KEY configuration")
        return
    
    try:
        # Test Supabase connection
        response = supabase.table('expenses').select('count', count='exact').limit(1).execute()
        logger.info("✅ Supabase connection successful")
    except Exception as e:
        logger.error(f"❌ Supabase connection failed: {e}")
        logger.error("Please check your SUPABASE_URL and SUPABASE_KEY configuration")

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

# Health check endpoint
@app.get("/")
async def health_check():
    return {
        "status": "healthy", 
        "message": "Household Expenditure API",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat()
    }

# Test endpoint for development
@app.get("/test")
async def test_endpoint():
    """Test endpoint to verify API functionality"""
    return {
        "message": "API is working!",
        "timestamp": datetime.now().isoformat(),
        "supabase_configured": bool(config.SUPABASE_URL and config.SUPABASE_KEY)
    }

# Report endpoints
@app.get("/reports/transactions")
async def get_transaction_reports(
    start_date: str,
    end_date: str,
    user_id: str = Depends(verify_token)
):
    """Get comprehensive transaction reports"""
    if supabase is None:
        raise HTTPException(status_code=500, detail="Supabase client not initialized")
    
    try:
        # Fetch transactions from Supabase
        response = supabase.table('expenses').select('*').eq('user_id', user_id).gte('date', start_date).lte('date', end_date).execute()
        
        transactions = response.data
        
        # Process data for different chart types
        category_breakdown = defaultdict(float)
        daily_trends = defaultdict(float)
        monthly_trends = defaultdict(float)
        
        for transaction in transactions:
            amount = abs(transaction['amount'])
            category = transaction['category']
            date = datetime.fromisoformat(transaction['date'].replace('Z', '+00:00'))
            
            # Category breakdown
            category_breakdown[category] += amount
            
            # Daily trends
            daily_key = date.strftime('%Y-%m-%d')
            daily_trends[daily_key] += amount
            
            # Monthly trends
            monthly_key = date.strftime('%Y-%m')
            monthly_trends[monthly_key] += amount
        
        # Calculate statistics
        total_amount = sum(category_breakdown.values())
        total_transactions = len(transactions)
        avg_transaction = total_amount / total_transactions if total_transactions > 0 else 0
        
        return {
            "summary": {
                "total_amount": total_amount,
                "total_transactions": total_transactions,
                "average_transaction": avg_transaction,
                "period": f"{start_date} to {end_date}"
            },
            "category_breakdown": [
                {
                    "category": category,
                    "amount": amount,
                    "percentage": (amount / total_amount * 100) if total_amount > 0 else 0
                }
                for category, amount in category_breakdown.items()
            ],
            "daily_trends": [
                {
                    "date": date,
                    "amount": amount
                }
                for date, amount in sorted(daily_trends.items())
            ],
            "monthly_trends": [
                {
                    "month": month,
                    "amount": amount
                }
                for month, amount in sorted(monthly_trends.items())
            ],
            "transactions": transactions
        }
    except Exception as e:
        logger.error(f"Error fetching transaction reports: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch transaction reports")

@app.get("/reports/accounts")
async def get_account_reports(
    user_id: str = Depends(verify_token)
):
    """Get comprehensive account reports"""
    if supabase is None:
        raise HTTPException(status_code=500, detail="Supabase client not initialized")
    
    try:
        # Fetch accounts from Supabase
        response = supabase.table('accounts').select('*').eq('user_id', user_id).execute()
        accounts = response.data
        
        # Calculate account statistics
        total_balance = sum(account['balance'] for account in accounts)
        account_types = defaultdict(list)
        
        for account in accounts:
            account_types[account['type']].append(account)
        
        return {
            "summary": {
                "total_accounts": len(accounts),
                "total_balance": total_balance,
                "account_types": len(account_types)
            },
            "accounts": accounts,
            "by_type": {
                account_type: {
                    "count": len(accounts_list),
                    "total_balance": sum(acc['balance'] for acc in accounts_list),
                    "accounts": accounts_list
                }
                for account_type, accounts_list in account_types.items()
            }
        }
    except Exception as e:
        logger.error(f"Error fetching account reports: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch account reports")

@app.get("/reports/budget")
async def get_budget_reports(
    user_id: str = Depends(verify_token)
):
    """Get comprehensive budget reports"""
    if supabase is None:
        raise HTTPException(status_code=500, detail="Supabase client not initialized")
    
    try:
        # Fetch budgets from Supabase
        response = supabase.table('budgets').select('*').eq('user_id', user_id).execute()
        budgets = response.data
        
        # Fetch expenses for budget comparison
        current_month = datetime.now().strftime('%Y-%m')
        expenses_response = supabase.table('expenses').select('*').eq('user_id', user_id).gte('date', f"{current_month}-01").lte('date', f"{current_month}-31").execute()
        expenses = expenses_response.data
        
        # Calculate budget vs actual
        budget_analysis = []
        total_budget = 0
        total_spent = 0
        
        for budget in budgets:
            category = budget['category']
            budget_amount = budget['amount']
            spent_amount = sum(abs(exp['amount']) for exp in expenses if exp['category'] == category and exp['entry_type'] == 'Expense')
            
            total_budget += budget_amount
            total_spent += spent_amount
            
            budget_analysis.append({
                "category": category,
                "budget_amount": budget_amount,
                "spent_amount": spent_amount,
                "remaining": budget_amount - spent_amount,
                "percentage_used": (spent_amount / budget_amount * 100) if budget_amount > 0 else 0
            })
        
        return {
            "summary": {
                "total_budget": total_budget,
                "total_spent": total_spent,
                "total_remaining": total_budget - total_spent,
                "overall_percentage_used": (total_spent / total_budget * 100) if total_budget > 0 else 0
            },
            "budget_analysis": budget_analysis,
            "budgets": budgets
        }
    except Exception as e:
        logger.error(f"Error fetching budget reports: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch budget reports")

@app.get("/reports/subscriptions")
async def get_subscription_reports(
    user_id: str = Depends(verify_token)
):
    """Get comprehensive subscription reports"""
    if supabase is None:
        raise HTTPException(status_code=500, detail="Supabase client not initialized")
    
    try:
        # Fetch subscriptions from Supabase
        response = supabase.table('subscriptions').select('*').eq('user_id', user_id).execute()
        subscriptions = response.data
        
        # Calculate subscription statistics
        total_monthly_cost = sum(sub['monthly_cost'] for sub in subscriptions)
        total_yearly_cost = total_monthly_cost * 12
        
        subscription_types = defaultdict(list)
        for subscription in subscriptions:
            subscription_types[subscription['category']].append(subscription)
        
        return {
            "summary": {
                "total_subscriptions": len(subscriptions),
                "total_monthly_cost": total_monthly_cost,
                "total_yearly_cost": total_yearly_cost
            },
            "subscriptions": subscriptions,
            "by_category": {
                category: {
                    "count": len(subs_list),
                    "total_monthly_cost": sum(sub['monthly_cost'] for sub in subs_list),
                    "subscriptions": subs_list
                }
                for category, subs_list in subscription_types.items()
            }
        }
    except Exception as e:
        logger.error(f"Error fetching subscription reports: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch subscription reports")

@app.get("/reports/goals")
async def get_goal_reports(
    user_id: str = Depends(verify_token)
):
    """Get comprehensive goal reports"""
    if supabase is None:
        raise HTTPException(status_code=500, detail="Supabase client not initialized")
    
    try:
        # Fetch goals from Supabase
        response = supabase.table('goals').select('*').eq('user_id', user_id).execute()
        goals = response.data
        
        # Calculate goal statistics
        total_target = sum(goal['target_amount'] for goal in goals)
        total_saved = sum(goal['current_amount'] for goal in goals)
        total_progress = (total_saved / total_target * 100) if total_target > 0 else 0
        
        # Categorize goals by status
        active_goals = [goal for goal in goals if goal['status'] == 'active']
        completed_goals = [goal for goal in goals if goal['status'] == 'completed']
        
        return {
            "summary": {
                "total_goals": len(goals),
                "active_goals": len(active_goals),
                "completed_goals": len(completed_goals),
                "total_target": total_target,
                "total_saved": total_saved,
                "total_progress": total_progress
            },
            "goals": goals,
            "active_goals": active_goals,
            "completed_goals": completed_goals
        }
    except Exception as e:
        logger.error(f"Error fetching goal reports: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch goal reports")

@app.get("/reports/download/{report_type}")
async def download_report(
    report_type: str,
    format: str = "csv",  # csv or pdf
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user_id: str = Depends(verify_token)
):
    """Download reports in CSV or PDF format"""
    if supabase is None:
        raise HTTPException(status_code=500, detail="Supabase client not initialized")
    
    try:
        # Get report data based on type
        if report_type == "transactions":
            if not start_date or not end_date:
                raise HTTPException(status_code=400, detail="Start date and end date required for transaction reports")
            data = await get_transaction_reports(start_date, end_date, user_id)
        elif report_type == "accounts":
            data = await get_account_reports(user_id)
        elif report_type == "budget":
            data = await get_budget_reports(user_id)
        elif report_type == "subscriptions":
            data = await get_subscription_reports(user_id)
        elif report_type == "goals":
            data = await get_goal_reports(user_id)
        else:
            raise HTTPException(status_code=400, detail="Invalid report type")
        
        if format.lower() == "csv":
            # Generate CSV
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header based on report type
            if report_type == "transactions":
                writer.writerow(['Date', 'Description', 'Category', 'Amount', 'Type'])
                for transaction in data['transactions']:
                    writer.writerow([
                        transaction['date'],
                        transaction['description'],
                        transaction['category'],
                        transaction['amount'],
                        transaction['entry_type']
                    ])
            elif report_type == "accounts":
                writer.writerow(['Name', 'Type', 'Balance', 'Currency'])
                for account in data['accounts']:
                    writer.writerow([
                        account['name'],
                        account['type'],
                        account['balance'],
                        account.get('currency', 'USD')
                    ])
            elif report_type == "budget":
                writer.writerow(['Category', 'Budget Amount', 'Spent Amount', 'Remaining', 'Percentage Used'])
                for analysis in data['budget_analysis']:
                    writer.writerow([
                        analysis['category'],
                        analysis['budget_amount'],
                        analysis['spent_amount'],
                        analysis['remaining'],
                        f"{analysis['percentage_used']:.2f}%"
                    ])
            elif report_type == "subscriptions":
                writer.writerow(['Name', 'Category', 'Monthly Cost', 'Billing Cycle', 'Next Billing'])
                for subscription in data['subscriptions']:
                    writer.writerow([
                        subscription['name'],
                        subscription['category'],
                        subscription['monthly_cost'],
                        subscription['billing_cycle'],
                        subscription.get('next_billing_date', 'N/A')
                    ])
            elif report_type == "goals":
                writer.writerow(['Name', 'Target Amount', 'Current Amount', 'Progress', 'Status', 'Deadline'])
                for goal in data['goals']:
                    progress = (goal['current_amount'] / goal['target_amount'] * 100) if goal['target_amount'] > 0 else 0
                    writer.writerow([
                        goal['name'],
                        goal['target_amount'],
                        goal['current_amount'],
                        f"{progress:.2f}%",
                        goal['status'],
                        goal.get('deadline', 'N/A')
                    ])
            
            csv_content = output.getvalue()
            output.close()
            
            # Return CSV file
            return {
                "content": csv_content,
                "filename": f"{report_type}_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                "content_type": "text/csv"
            }
        
        elif format.lower() == "pdf":
            # For PDF, we'll return a JSON with data that can be converted to PDF on the client side
            return {
                "data": data,
                "filename": f"{report_type}_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                "content_type": "application/pdf"
            }
        
        else:
            raise HTTPException(status_code=400, detail="Invalid format. Use 'csv' or 'pdf'")
            
    except Exception as e:
        logger.error(f"Error generating report download: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate report download")




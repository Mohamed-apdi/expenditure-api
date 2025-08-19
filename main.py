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
    account_id: Optional[str] = None,
    user_id: str = Depends(verify_token)
):
    """Get comprehensive transaction reports"""
    if supabase is None:
        raise HTTPException(status_code=500, detail="Supabase client not initialized")
    
    try:
        logger.info(f"Fetching transaction reports for user {user_id}, account {account_id}, dates {start_date} to {end_date}")
        
        # Fetch transactions from Supabase with optional account filtering
        query = supabase.table('expenses').select('*').eq('user_id', user_id).gte('date', start_date).lte('date', end_date)
        
        # Add account filter if account_id is provided
        if account_id:
            query = query.eq('account_id', account_id)
            
        response = query.execute()
        
        transactions = response.data
        logger.info(f"Found {len(transactions)} transactions")
        
        # Process data for different chart types
        category_breakdown = defaultdict(float)
        daily_trends = defaultdict(float)
        monthly_trends = defaultdict(float)
        
        total_income = 0
        total_expenses = 0
        
        for transaction in transactions:
            try:
                amount = transaction['amount']
                category = transaction['category']
                entry_type = transaction.get('entry_type', 'Expense')
                
                # Handle different date formats
                date_str = transaction['date']
                if date_str.endswith('Z'):
                    date_str = date_str.replace('Z', '+00:00')
                elif not any(c in date_str for c in ['+', '-', 'T']):
                    # If it's just a date (YYYY-MM-DD), add time
                    date_str += 'T00:00:00+00:00'
                
                date = datetime.fromisoformat(date_str)
                
            except Exception as e:
                logger.error(f"Error processing transaction {transaction.get('id', 'unknown')}: {e}")
                continue
            
            # Use absolute amount for category breakdown and trends
            abs_amount = abs(amount)
            
            # Category breakdown
            category_breakdown[category] += abs_amount
            
            # Daily trends
            daily_key = date.strftime('%Y-%m-%d')
            daily_trends[daily_key] += abs_amount
            
            # Monthly trends
            monthly_key = date.strftime('%Y-%m')
            monthly_trends[monthly_key] += abs_amount
            
            # Calculate totals based on entry type
            if entry_type == 'Income':
                total_income += abs_amount
            else:  # Expense
                total_expenses += abs_amount
        
        # Calculate statistics - net amount (income - expenses)
        total_amount = total_income - total_expenses
        total_transactions = len(transactions)
        avg_transaction = total_amount / total_transactions if total_transactions > 0 else 0
        
        # Create category breakdown object in the format frontend expects
        category_breakdown_obj = {}
        total_category_amount = sum(category_breakdown.values())
        
        for category, amount in category_breakdown.items():
            category_breakdown_obj[category] = {
                "amount": amount,
                "percentage": (amount / total_category_amount * 100) if total_category_amount > 0 else 0,
                "count": sum(1 for t in transactions if t['category'] == category)
            }
        
        return {
            "summary": {
                "total_amount": total_amount,
                "total_income": total_income,
                "total_expenses": total_expenses,
                "total_transactions": total_transactions,
                "average_transaction": avg_transaction,
                "period": f"{start_date} to {end_date}"
            },
            "category_breakdown": category_breakdown_obj,
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



@app.get("/reports/download/{report_type}")
async def download_report(
    report_type: str,
    format: str = "csv",  # csv or pdf
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    account_id: Optional[str] = None,
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
            data = await get_transaction_reports(start_date, end_date, account_id, user_id)
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




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
    # """Application startup event"""
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
    # """Middleware to log request processing time"""
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
    # """Test endpoint to verify API functionality"""
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
    # """Get comprehensive transaction reports"""
    if supabase is None:
        raise HTTPException(status_code=500, detail="Supabase client not initialized")

    try:
        logger.info(f"🔍 [TRANSACTIONS DEBUG] Starting transaction report for user {user_id}")
        logger.info(f"🔍 [TRANSACTIONS DEBUG] Parameters - start_date: {start_date}, end_date: {end_date}, account_id: {account_id}")

        # First, let's check what data exists for this user
        total_check = supabase.table('expenses').select('*', count='exact').eq('user_id', user_id).execute()
        logger.info(f"🔍 [TRANSACTIONS DEBUG] Total transactions in database for user {user_id}: {len(total_check.data)}")

        # Check ALL transactions without filters to see what exists
        all_user_transactions = supabase.table('expenses').select('*').eq('user_id', user_id).limit(10).execute()
        logger.info(f"🔍 [TRANSACTIONS DEBUG] All transactions for user (no filters): {len(all_user_transactions.data)}")
        if all_user_transactions.data:
            for i, trans in enumerate(all_user_transactions.data[:3]):
                logger.info(f"🔍 [TRANSACTIONS DEBUG] Sample transaction {i+1}: ID={trans.get('id')}, Date={trans.get('date')}, Account={trans.get('account_id')}, Amount={trans.get('amount')}")

        # Fetch transactions from Supabase with optional account filtering
        query = supabase.table('expenses').select('*').eq('user_id', user_id)

        # Log the date range
        logger.info(f"🔍 [TRANSACTIONS DEBUG] Applying date filter: {start_date} to {end_date}")
        query = query.gte('date', start_date).lte('date', end_date)

        # Add account filter if account_id is provided and not empty
        if account_id and account_id.strip():
            logger.info(f"🔍 [TRANSACTIONS DEBUG] Filtering by account_id: {account_id}")
            query = query.eq('account_id', account_id)

            # Debug: Check how many transactions exist for this account
            account_check = supabase.table('expenses').select('*', count='exact').eq('user_id', user_id).eq('account_id', account_id).execute()
            logger.info(f"🔍 [TRANSACTIONS DEBUG] Total transactions for account {account_id}: {len(account_check.data)}")

            # Check account exists and belongs to user
            account_verify = supabase.table('accounts').select('*').eq('id', account_id).eq('user_id', user_id).execute()
            logger.info(f"🔍 [TRANSACTIONS DEBUG] Account verification - found: {len(account_verify.data)} accounts")
            if account_verify.data:
                logger.info(f"🔍 [TRANSACTIONS DEBUG] Account details: {account_verify.data[0]}")
        else:
            logger.info("🔍 [TRANSACTIONS DEBUG] No account filter applied - showing all accounts")

        logger.info("🔍 [TRANSACTIONS DEBUG] Executing final query...")
        response = query.execute()
        logger.info(f"🔍 [TRANSACTIONS DEBUG] Final query returned {len(response.data)} transactions")

        transactions = response.data

        # Debug: Log sample transaction if any exist
        if transactions and len(transactions) > 0:
            logger.info(f"🔍 [TRANSACTIONS DEBUG] Sample transaction from final query: {transactions[0]}")
        else:
            # Check if date format is the issue
            logger.warning("🔍 [TRANSACTIONS DEBUG] No transactions found. Checking possible date format issues...")
            # Try without date filter to see if data exists
            no_date_filter = supabase.table('expenses').select('*').eq('user_id', user_id).limit(5).execute()
            if no_date_filter.data:
                logger.info(f"🔍 [TRANSACTIONS DEBUG] Found {len(no_date_filter.data)} transactions without date filter")
                sample_dates = [t.get('date') for t in no_date_filter.data[:3]]
                logger.info(f"🔍 [TRANSACTIONS DEBUG] Sample dates in database: {sample_dates}")
            else:
                logger.warning("🔍 [TRANSACTIONS DEBUG] No transactions found at all for this user")

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
                logger.error(f"🔍 [TRANSACTIONS DEBUG] Error processing transaction {transaction.get('id', 'unknown')}: {e}")
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

        logger.info(f"🔍 [TRANSACTIONS DEBUG] Final summary - Income: {total_income}, Expenses: {total_expenses}, Net: {total_amount}, Transactions: {total_transactions}")

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
        logger.error(f"❌ [TRANSACTIONS DEBUG] Error fetching transaction reports: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch transaction reports")


@app.get("/reports/accounts")
async def get_account_reports(
    account_id: Optional[str] = None,
    user_id: str = Depends(verify_token)
):
    # """Get account balance and transaction summary reports"""
    if supabase is None:
        raise HTTPException(status_code=500, detail="Supabase client not initialized")

    try:
        logger.info(f"🔍 [ACCOUNTS DEBUG] Starting account reports for user {user_id}, account_id: {account_id}")

        # Debug: Check ALL accounts for this user first
        all_accounts_check = supabase.table('accounts').select('*', count='exact').eq('user_id', user_id).execute()
        logger.info(f"🔍 [ACCOUNTS DEBUG] Total accounts in database for user {user_id}: {len(all_accounts_check.data)}")

        if all_accounts_check.data:
            for account in all_accounts_check.data:
                logger.info(f"🔍 [ACCOUNTS DEBUG] Account: ID={account.get('id')}, Name={account.get('name')}, Balance={account.get('balance')}")

        # Fetch accounts
        if account_id and account_id.strip():
            logger.info(f"🔍 [ACCOUNTS DEBUG] Filtering by specific account ID: {account_id}")
            accounts_query = supabase.table('accounts').select('*').eq('user_id', user_id).eq('id', account_id)
        else:
            accounts_query = supabase.table('accounts').select('*').eq('user_id', user_id)

        accounts_response = accounts_query.execute()
        accounts = accounts_response.data

        logger.info(f"🔍 [ACCOUNTS DEBUG] Final accounts query returned {len(accounts)} accounts")

        if not accounts:
            logger.warning(f"🔍 [ACCOUNTS DEBUG] No accounts found for user {user_id}")
            return {
                "summary": {
                    "total_balance": 0,
                    "total_accounts": 0,
                    "total_transactions": 0
                },
                "accounts": []
            }

        # Calculate summary for each account
        account_details = []
        total_balance = 0
        total_transactions = 0

        for account in accounts:
            # Fetch transactions for this account
            trans_query = supabase.table('expenses').select('*', count='exact').eq('user_id', user_id).eq('account_id', account['id'])
            trans_response = trans_query.execute()

            transaction_count = len(trans_response.data) if trans_response.data else 0
            total_transactions += transaction_count

            account_balance = account.get('balance', 0)
            total_balance += account_balance

            account_details.append({
                "id": account['id'],
                "name": account['name'],
                "type": account.get('type', 'Unknown'),
                "balance": account_balance,
                "currency": account.get('currency', 'USD'),
                "transaction_count": transaction_count,
                "created_at": account.get('created_at', '')
            })

            logger.info(f"🔍 [ACCOUNTS DEBUG] Account {account['name']}: balance={account_balance}, transactions={transaction_count}")

        logger.info(f"🔍 [ACCOUNTS DEBUG] Final summary - Total balance: {total_balance}, Total accounts: {len(accounts)}, Total transactions: {total_transactions}")

        return {
            "summary": {
                "total_balance": total_balance,
                "total_accounts": len(accounts),
                "total_transactions": total_transactions
            },
            "accounts": account_details
        }

    except Exception as e:
        logger.error(f"❌ [ACCOUNTS DEBUG] Error fetching account reports: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch account reports")


@app.get("/reports/budgets")
async def get_budget_reports(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    account_id: Optional[str] = None,
    user_id: str = Depends(verify_token)
):
    # """Get budget vs actual spending analysis"""
    if supabase is None:
        raise HTTPException(status_code=500, detail="Supabase client not initialized")

    try:
        logger.info(f"🔍 [BUDGETS DEBUG] Starting budget reports for user {user_id}")
        logger.info(f"🔍 [BUDGETS DEBUG] Parameters - start_date: {start_date}, end_date: {end_date}, account_id: {account_id}")

        # If no dates provided, use current month
        if not start_date or not end_date:
            today = datetime.now()
            start_date = today.replace(day=1).strftime('%Y-%m-%d')
            last_day = monthrange(today.year, today.month)[1]
            end_date = today.replace(day=last_day).strftime('%Y-%m-%d')
            logger.info(f"🔍 [BUDGETS DEBUG] Using default date range: {start_date} to {end_date}")

        # Fetch budgets
        budgets_query = supabase.table('budgets').select('*').eq('user_id', user_id)
        budgets_response = budgets_query.execute()
        budgets = budgets_response.data or []

        logger.info(f"🔍 [BUDGETS DEBUG] Found {len(budgets)} budgets for user {user_id}")
        if budgets:
            for budget in budgets:
                logger.info(f"🔍 [BUDGETS DEBUG] Budget: Category={budget.get('category')}, Amount={budget.get('amount')}")

        # Fetch expenses for the period
        expenses_query = supabase.table('expenses').select('*').eq('user_id', user_id).gte('date', start_date).lte('date', end_date)

        if account_id and account_id.strip():
            logger.info(f"🔍 [BUDGETS DEBUG] Filtering expenses by account_id: {account_id}")
            expenses_query = expenses_query.eq('account_id', account_id)

        expenses_response = expenses_query.execute()
        expenses = expenses_response.data or []

        logger.info(f"🔍 [BUDGETS DEBUG] Found {len(expenses)} expenses in date range")

        # Calculate spending by category
        category_spending = defaultdict(float)
        for expense in expenses:
            if expense.get('entry_type', 'Expense') == 'Expense':
                category = expense.get('category', 'Uncategorized')
                category_spending[category] += abs(expense.get('amount', 0))

        logger.info(f"🔍 [BUDGETS DEBUG] Category spending: {dict(category_spending)}")

        # Compare budgets with actual spending
        budget_comparison = []
        total_budget = 0
        total_spent = 0

        for budget in budgets:
            category = budget.get('category', 'Uncategorized')
            budget_amount = budget.get('amount', 0)
            spent = category_spending.get(category, 0)
            remaining = budget_amount - spent
            percentage = (spent / budget_amount * 100) if budget_amount > 0 else 0

            total_budget += budget_amount
            total_spent += spent

            budget_comparison.append({
                "category": category,
                "budget": budget_amount,
                "spent": spent,
                "remaining": remaining,
                "percentage": percentage,
                "status": "over" if spent > budget_amount else "under" if spent < budget_amount * 0.9 else "near"
            })

            logger.info(f"🔍 [BUDGETS DEBUG] Budget comparison for {category}: budget={budget_amount}, spent={spent}, remaining={remaining}")

        # Find unbudgeted spending
        unbudgeted_categories = {category: amount for category, amount in category_spending.items() if not any(b.get('category') == category for b in budgets)}
        logger.info(f"🔍 [BUDGETS DEBUG] Unbudgeted spending: {unbudgeted_categories}")

        return {
            "summary": {
                "period": f"{start_date} to {end_date}",
                "total_budget": total_budget,
                "total_spent": total_spent,
                "total_remaining": total_budget - total_spent,
                "overall_percentage": (total_spent / total_budget * 100) if total_budget > 0 else 0
            },
            "budget_comparison": budget_comparison,
            "unbudgeted_spending": unbudgeted_categories
        }

    except Exception as e:
        logger.error(f"❌ [BUDGETS DEBUG] Error fetching budget reports: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch budget reports")


@app.get("/reports/goals")
async def get_goal_reports(
    user_id: str = Depends(verify_token)
):
    # """Get financial goals progress tracking"""
    if supabase is None:
        raise HTTPException(status_code=500, detail="Supabase client not initialized")

    try:
        logger.info(f"🔍 [GOALS DEBUG] Starting goal reports for user {user_id}")

        # Fetch goals
        goals_query = supabase.table('goals').select('*').eq('user_id', user_id)
        goals_response = goals_query.execute()
        goals = goals_response.data or []

        logger.info(f"🔍 [GOALS DEBUG] Found {len(goals)} goals for user {user_id}")
        if goals:
            for goal in goals:
                logger.info(f"🔍 [GOALS DEBUG] Goal: Name={goal.get('name')}, Target={goal.get('target_amount')}, Current={goal.get('current_amount')}")

        goal_details = []
        total_target = 0
        total_saved = 0

        for goal in goals:
            target = goal.get('target_amount', 0)
            saved = goal.get('current_amount', 0)
            remaining = target - saved
            percentage = (saved / target * 100) if target > 0 else 0

            # Calculate days remaining if deadline exists
            deadline = goal.get('target_date')
            days_remaining = None
            if deadline:
                try:
                    deadline_date = datetime.fromisoformat(deadline.replace('Z', '+00:00'))
                    days_remaining = (deadline_date - datetime.now()).days
                except:
                    pass

            total_target += target
            total_saved += saved

            goal_details.append({
                "id": goal.get('id'),
                "name": goal.get('name', 'Untitled Goal'),
                "target_amount": target,
                "current_amount": saved,
                "remaining": remaining,
                "percentage": percentage,
                "deadline": deadline,
                "days_remaining": days_remaining,
                "status": "completed" if percentage >= 100 else "on_track" if percentage >= 50 else "needs_attention"
            })

        logger.info(f"🔍 [GOALS DEBUG] Final summary - Total target: {total_target}, Total saved: {total_saved}, Goals: {len(goals)}")

        return {
            "summary": {
                "total_goals": len(goals),
                "total_target": total_target,
                "total_saved": total_saved,
                "total_remaining": total_target - total_saved,
                "overall_percentage": (total_saved / total_target * 100) if total_target > 0 else 0,
                "completed_goals": len([g for g in goal_details if g['status'] == 'completed'])
            },
            "goals": goal_details
        }

    except Exception as e:
        logger.error(f"❌ [GOALS DEBUG] Error fetching goal reports: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch goal reports")


@app.get("/reports/subscriptions")
async def get_subscription_reports(
    account_id: Optional[str] = None,
    user_id: str = Depends(verify_token)
):
    # """Get subscription cost breakdown and analysis"""
    if supabase is None:
        raise HTTPException(status_code=500, detail="Supabase client not initialized")

    try:
        logger.info(f"🔍 [SUBSCRIPTIONS DEBUG] Starting subscription reports for user {user_id}, account_id: {account_id}")

        # Fetch subscriptions
        subs_query = supabase.table('subscriptions').select('*').eq('user_id', user_id)

        if account_id and account_id.strip():
            logger.info(f"🔍 [SUBSCRIPTIONS DEBUG] Filtering by account_id: {account_id}")
            subs_query = subs_query.eq('account_id', account_id)

        subs_response = subs_query.execute()
        subscriptions = subs_response.data or []

        logger.info(f"🔍 [SUBSCRIPTIONS DEBUG] Found {len(subscriptions)} subscriptions for user {user_id}")
        if subscriptions:
            for sub in subscriptions:
                logger.info(f"🔍 [SUBSCRIPTIONS DEBUG] Subscription: Name={sub.get('name')}, Cost={sub.get('cost')}, Cycle={sub.get('billing_cycle')}")

        # Calculate costs
        subscription_details = []
        monthly_total = 0
        yearly_total = 0

        frequency_map = {
            'monthly': 1,
            'yearly': 12,
            'weekly': 0.25,
            'daily': 0.033
        }

        for sub in subscriptions:
            cost = sub.get('cost', 0)
            frequency = sub.get('billing_cycle', 'monthly').lower()

            # Convert to monthly equivalent
            months = frequency_map.get(frequency, 1)
            monthly_cost = cost / months if months > 0 else cost

            monthly_total += monthly_cost
            yearly_total += monthly_cost * 12

            subscription_details.append({
                "id": sub.get('id'),
                "name": sub.get('name', 'Unknown'),
                "cost": cost,
                "billing_cycle": frequency,
                "monthly_equivalent": monthly_cost,
                "yearly_equivalent": monthly_cost * 12,
                "next_billing": sub.get('next_billing_date'),
                "status": sub.get('status', 'active'),
                "category": sub.get('category', 'Other')
            })

        # Group by category
        category_breakdown = defaultdict(float)
        for sub in subscription_details:
            category_breakdown[sub['category']] += sub['monthly_equivalent']

        logger.info(f"🔍 [SUBSCRIPTIONS DEBUG] Final summary - Monthly total: {monthly_total}, Yearly total: {yearly_total}, Active: {len([s for s in subscriptions if s.get('status') == 'active'])}")

        return {
            "summary": {
                "total_subscriptions": len(subscriptions),
                "monthly_cost": monthly_total,
                "yearly_cost": yearly_total,
                "active_subscriptions": len([s for s in subscriptions if s.get('status') == 'active'])
            },
            "subscriptions": subscription_details,
            "category_breakdown": dict(category_breakdown)
        }

    except Exception as e:
        logger.error(f"❌ [SUBSCRIPTIONS DEBUG] Error fetching subscription reports: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch subscription reports")


@app.get("/reports/download/{report_type}")
async def download_report(
    report_type: str,
    format: str = "csv",  # csv or pdf
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    account_id: Optional[str] = None,
    user_id: str = Depends(verify_token)
):
    # """Download reports in CSV or PDF format"""
    if supabase is None:
        raise HTTPException(status_code=500, detail="Supabase client not initialized")

    try:
        logger.info(f"🔍 [DOWNLOAD DEBUG] Starting download for report_type: {report_type}, format: {format}")
        logger.info(f"🔍 [DOWNLOAD DEBUG] Parameters - start_date: {start_date}, end_date: {end_date}, account_id: {account_id}")

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

            logger.info(f"🔍 [DOWNLOAD DEBUG] Generated CSV with {len(data['transactions'])} transactions")

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
        logger.error(f"❌ [DOWNLOAD DEBUG] Error generating report download: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate report download")


# Add comprehensive diagnostic endpoints
@app.get("/debug/all-user-data")
async def debug_all_user_data(user_id: str = Depends(verify_token)):
    # """Comprehensive diagnostic endpoint to check ALL user data"""
    if supabase is None:
        raise HTTPException(status_code=500, detail="Supabase client not initialized")

    try:
        diagnostic_data = {}
        tables = [
            'expenses', 'accounts', 'budgets', 'goals',
            'subscriptions', 'loans', 'categories', 'users'
        ]

        for table in tables:
            try:
                # First check if table exists and get total count
                count_query = supabase.table(table).select('id', count='exact').eq('user_id', user_id)
                count_response = count_query.execute()

                # Get sample data
                sample_query = supabase.table(table).select('*').eq('user_id', user_id).limit(3)
                sample_response = sample_query.execute()

                diagnostic_data[table] = {
                    "total_count": len(count_response.data) if count_response.data else 0,
                    "sample_data": sample_response.data if sample_response.data else [],
                    "raw_count_response": count_response.count if hasattr(count_response, 'count') else 'unknown'
                }

                logger.info(f"🔍 [DIAGNOSTIC DEBUG] Table '{table}': {diagnostic_data[table]['total_count']} records for user {user_id}")

            except Exception as e:
                diagnostic_data[table] = {
                    "error": str(e),
                    "total_count": 0,
                    "sample_data": []
                }
                logger.error(f"❌ [DIAGNOSTIC DEBUG] Error querying {table}: {e}")

        return {
            "user_id": user_id,
            "timestamp": datetime.now().isoformat(),
            "diagnostic": diagnostic_data,
            "summary": {
                "tables_with_data": [table for table, data in diagnostic_data.items() if data.get('total_count', 0) > 0],
                "total_tables_checked": len(tables)
            }
        }
    except Exception as e:
        logger.error(f"❌ [DIAGNOSTIC DEBUG] Error in comprehensive diagnostic: {e}")
        raise HTTPException(status_code=500, detail="Comprehensive diagnostic failed")


@app.get("/debug/check-data-issues")
async def debug_data_issues(user_id: str = Depends(verify_token)):
    # """Check for common data issues"""
    if supabase is None:
        raise HTTPException(status_code=500, detail="Supabase client not initialized")

    issues = []

    # Check 1: Are there any transactions at all in the database?
    try:
        all_transactions = supabase.table('expenses').select('*').limit(5).execute()
        if all_transactions.data:
            issues.append(f"Found {len(all_transactions.data)} total transactions in DB, but none for current user")
            issues.append(f"Sample transaction user_ids: {[t.get('user_id') for t in all_transactions.data]}")
        else:
            issues.append("No transactions found in entire database")
    except Exception as e:
        issues.append(f"Error checking all transactions: {e}")

    # Check 2: Check table structure
    try:
        sample_structure = supabase.table('expenses').select('*').limit(1).execute()
        if sample_structure.data:
            issues.append(f"Expenses table structure: {list(sample_structure.data[0].keys())}")
        else:
            issues.append("Cannot determine expenses table structure - table might be empty")
    except Exception as e:
        issues.append(f"Error checking table structure: {e}")

    # Check 3: Verify user exists in auth system
    try:
        user_check = supabase.table('users').select('*').eq('id', user_id).execute()
        if user_check.data:
            issues.append(f"User found in users table: {user_check.data[0]}")
        else:
            issues.append("User not found in users table (might be using auth.users only)")
    except Exception as e:
        issues.append(f"Error checking users table: {e}")

    return {
        "user_id": user_id,
        "issues": issues,
        "timestamp": datetime.now().isoformat()
    }


@app.post("/debug/create-sample-data")
async def create_sample_data(user_id: str = Depends(verify_token)):
    # """Create sample data for testing"""
    if supabase is None:
        raise HTTPException(status_code=500, detail="Supabase client not initialized")

    try:
        # Create a sample account
        account_data = {
            "user_id": user_id,
            "name": "Sample Bank Account",
            "type": "checking",
            "balance": 1500.00,
            "currency": "USD"
        }
        account_response = supabase.table('accounts').insert(account_data).execute()
        account_id = account_response.data[0]['id'] if account_response.data else None

        # Create sample transactions
        sample_transactions = [
            {
                "user_id": user_id,
                "account_id": account_id,
                "amount": -100.00,
                "description": "Grocery Shopping",
                "category": "Food",
                "date": "2024-01-15",
                "entry_type": "Expense"
            },
            {
                "user_id": user_id,
                "account_id": account_id,
                "amount": 2000.00,
                "description": "Salary",
                "category": "Income",
                "date": "2024-01-01",
                "entry_type": "Income"
            },
            {
                "user_id": user_id,
                "account_id": account_id,
                "amount": -50.00,
                "description": "Netflix Subscription",
                "category": "Entertainment",
                "date": "2024-01-05",
                "entry_type": "Expense"
            }
        ]

        transactions_response = supabase.table('expenses').insert(sample_transactions).execute()

        return {
            "message": "Sample data created successfully",
            "account_created": account_id is not None,
            "transactions_created": len(transactions_response.data) if transactions_response.data else 0,
            "sample_account_id": account_id,
            "user_id": user_id
        }

    except Exception as e:
        logger.error(f"❌ Error creating sample data: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create sample data: {e}")

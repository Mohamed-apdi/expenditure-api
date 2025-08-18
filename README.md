# Household Expenditure API

A comprehensive FastAPI-based backend for the Household Expenditure App, providing financial reporting, analytics, and data management capabilities.

## 🚀 Features

- **Comprehensive Reports**: Transactions, Accounts, Budget, Subscriptions, Goals
- **Data Export**: CSV and PDF download capabilities
- **Real-time Analytics**: Category breakdowns, trends, and insights
- **Secure Authentication**: JWT-based user authentication
- **RESTful API**: Clean, documented endpoints
- **CORS Support**: Optimized for React Native frontend

## 📋 Prerequisites

- Python 3.8+
- Supabase account and project
- FastAPI and required dependencies

## 🛠️ Installation

1. **Clone the repository** (if not already done)
   ```bash
   cd householdAPI
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables**
   Create a `.env` file in the `householdAPI` directory:
   ```env
   # Supabase Configuration
   SUPABASE_URL=your_supabase_project_url_here
   SUPABASE_KEY=your_supabase_anon_key_here
   
   # API Configuration
   API_HOST=0.0.0.0
   API_PORT=8000
   
   # Logging
   LOG_LEVEL=INFO
   ```

## 🔑 Supabase Setup

1. **Get your Supabase credentials**:
   - Go to your Supabase project dashboard
   - Navigate to Settings → API
   - Copy the Project URL and anon/public key

2. **Update your `.env` file** with the actual values:
   ```env
   SUPABASE_URL=https://your-project-id.supabase.co
   SUPABASE_KEY=your-anon-key-here
   ```

## 🚀 Running the API

### Option 1: Using the startup script (Recommended for development)
```bash
python start_api.py
```

### Option 2: Using uvicorn directly (Same as deployment)
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Option 3: Using the main file
```bash
python main.py
```

**Note**: The startup script uses the same uvicorn command structure as your deployment environment for consistency.

## 📚 API Documentation

Once the server is running, you can access:

- **API Documentation**: http://localhost:8000/docs
- **ReDoc Documentation**: http://localhost:8000/redoc
- **Health Check**: http://localhost:8000/
- **Test Endpoint**: http://localhost:8000/test

## 🔌 API Endpoints

### Reports
- `GET /reports/transactions` - Transaction reports with date filtering
- `GET /reports/accounts` - Account balance and overview
- `GET /reports/budget` - Budget vs actual spending analysis
- `GET /reports/subscriptions` - Subscription cost breakdown
- `GET /reports/goals` - Financial goals progress tracking

### Downloads
- `GET /reports/download/{report_type}` - Download reports in CSV/PDF format

### Health & Testing
- `GET /` - Health check endpoint
- `GET /test` - Test endpoint for development

## 🧪 Testing the API

1. **Start the server** using one of the methods above

2. **Test the health endpoint**:
   ```bash
   curl http://localhost:8000/
   ```

3. **Test the test endpoint**:
   ```bash
   curl http://localhost:8000/test
   ```

4. **Check API documentation**:
   Open http://localhost:8000/docs in your browser

## 🔒 Authentication

The API uses JWT tokens for authentication. To test protected endpoints:

1. **Get a token** from your frontend app
2. **Include it in the Authorization header**:
   ```bash
   curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:8000/reports/transactions?start_date=2024-01-01&end_date=2024-01-31
   ```

## 🐛 Troubleshooting

### Common Issues

1. **"SUPABASE_URL is not configured"**
   - Check your `.env` file
   - Ensure SUPABASE_URL and SUPABASE_KEY are set correctly

2. **"Connection failed"**
   - Verify your Supabase credentials
   - Check if your Supabase project is active

3. **"Module not found"**
   - Install dependencies: `pip install -r requirements.txt`
   - Check Python version (3.8+ required)

4. **Port already in use**
   - Change the port in `.env` file
   - Kill the process using the port: `lsof -ti:8000 | xargs kill`

### Debug Mode

Enable debug logging by setting:
```env
LOG_LEVEL=DEBUG
```

## 📁 Project Structure

```
householdAPI/
├── main.py              # Main FastAPI application
├── start_api.py         # Startup script
├── config.py            # Configuration management
├── requirements.txt     # Python dependencies
├── auth/                # Authentication modules
│   └── verify_token.py  # Token verification
├── supabase_config/     # Supabase client configuration
│   ├── client.py        # Main Supabase client
│   └── auth_client.py   # Authenticated client
├── schemes/             # Pydantic models
│   ├── analytics.py     # Analytics data models
│   ├── expenditure.py   # Expenditure models
│   └── compare.py       # Comparison models
└── README.md            # This file
```

## 🔄 Development

### Adding New Endpoints

1. **Create the endpoint** in `main.py`
2. **Add data models** in `schemes/` if needed
3. **Update documentation** in this README
4. **Test thoroughly** before deploying

### Code Style

- Follow PEP 8 guidelines
- Use type hints
- Add docstrings to functions
- Handle errors gracefully

## 🚀 Deployment

### Production Considerations

1. **Environment Variables**: Use proper secret management
2. **CORS**: Restrict origins to your frontend domains
3. **Logging**: Configure production logging levels
4. **Monitoring**: Add health checks and metrics
5. **Security**: Enable HTTPS and proper authentication

### Docker (Optional)

```dockerfile
FROM python:3.9-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## 📞 Support

If you encounter issues:

1. **Check the logs** for error messages
2. **Verify configuration** in your `.env` file
3. **Test endpoints** using the documentation
4. **Check Supabase** project status and credentials

## 📄 License

This project is part of the Household Expenditure App ecosystem.

---

**Happy coding! 🎉**

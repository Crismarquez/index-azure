#!/usr/bin/env python3
"""
Setup script for OCR Document Processing Database

This script helps users set up and configure the database for the document processing system.
"""

import os
import sys
import argparse
from pathlib import Path

# Add the parent directory to the path
sys.path.append(str(Path(__file__).parent.parent))

from database.init_db import init_database, create_sample_data
from config.config import ENV_VARIABLES, logger

def setup_directories():
    """Create necessary directories"""
    base_dir = Path(__file__).parent.parent
    
    directories = [
        base_dir / "database",
        base_dir / "storage",
        base_dir / "logs"
    ]
    
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
        print(f"📁 Created directory: {directory}")

def check_environment():
    """Check if environment variables are properly configured"""
    required_vars = [
        'AZURE_FORM_RECOGNIZER_ENDPOINT',
        'AZURE_FORM_RECOGNIZER_KEY',
        'AZURE_OPENAI_SERVICE',
        'AZURE_OPENAI_API_KEY',
        'AZURE_OPENAI_DEPLOYMENT_NAME'
    ]
    
    missing_vars = []
    for var in required_vars:
        if not ENV_VARIABLES.get(var):
            missing_vars.append(var)
    
    if missing_vars:
        print("⚠️  Warning: The following environment variables are not set:")
        for var in missing_vars:
            print(f"   - {var}")
        print("   Please check your .env file or environment configuration.")
        return False
    
    print("✅ Environment variables are properly configured")
    return True

def setup_database(database_url=None, create_samples=False):
    """Set up the database"""
    print("🏗️  Setting up database...")
    
    if not database_url:
        database_url = ENV_VARIABLES.get('DATABASE_URL', 'sqlite:///./documents.db')
    
    success = init_database(database_url)
    
    if not success:
        print("❌ Database setup failed!")
        return False
    
    print("✅ Database setup completed successfully!")
    
    if create_samples:
        print("📝 Creating sample data...")
        create_sample_data()
    
    return True

def print_usage_info():
    """Print information about how to use the system"""
    print("\n" + "="*60)
    print("🎉 Setup completed successfully!")
    print("="*60)
    print("\n📋 Next steps:")
    print("1. Start the API server:")
    print("   uvicorn main:app --reload --host 0.0.0.0 --port 8000")
    print("\n2. Test the API:")
    print("   curl http://localhost:8000/api/v1/health")
    print("\n3. Process a document:")
    print("   curl -X POST http://localhost:8000/api/v1/process_document \\")
    print("        -H 'Content-Type: application/json' \\")
    print("        -d '{your_processing_request}'")
    print("\n4. Check document statistics:")
    print("   curl http://localhost:8000/api/v1/documents/stats")
    print("\n5. Query documents by state:")
    print("   curl http://localhost:8000/api/v1/documents/state/bronze")
    print("   curl http://localhost:8000/api/v1/documents/state/silver")
    print("   curl http://localhost:8000/api/v1/documents/state/gold")
    print("\n📚 Available document states:")
    print("   - bronze: Raw processed documents")
    print("   - silver: Cleaned and structured data")
    print("   - gold: Enriched data ready for analysis")

def main():
    parser = argparse.ArgumentParser(description='Setup OCR Document Processing Database')
    parser.add_argument('--database-url', help='Database URL (default: from environment)')
    parser.add_argument('--create-samples', action='store_true', help='Create sample data')
    parser.add_argument('--check-env-only', action='store_true', help='Only check environment configuration')
    
    args = parser.parse_args()
    
    print("🚀 OCR Document Processing System Setup")
    print("="*50)
    
    # Check environment
    env_ok = check_environment()
    
    if args.check_env_only:
        sys.exit(0 if env_ok else 1)
    
    # Setup directories
    print("\n📁 Setting up directories...")
    setup_directories()
    
    # Setup database
    print("\n🗄️  Setting up database...")
    db_success = setup_database(args.database_url, args.create_samples)
    
    if not db_success:
        print("❌ Setup failed!")
        sys.exit(1)
    
    # Print usage information
    print_usage_info()

if __name__ == "__main__":
    main() 
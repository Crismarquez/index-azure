#!/usr/bin/env python3
"""
Database initialization script for the OCR Document Processing system.

This script creates the database tables and can be run independently or as part of the application startup.
"""

import os
import sys
from pathlib import Path

# Add the parent directory to the path so we can import from services
sys.path.append(str(Path(__file__).parent.parent))

from services.database import DocumentDatabase, DocumentRecord, DataState, ProcessStage
from config.config import ENV_VARIABLES, logger

def init_database(database_url: str = None):
    """
    Initialize the database with all required tables
    
    Args:
        database_url: Database connection URL (if None, uses environment variable)
    """
    try:
        # Use provided URL or get from environment
        if not database_url:
            database_url = ENV_VARIABLES.get('DATABASE_URL', 'sqlite:///./documents.db')
        
        logger.info(f"Initializing database: {database_url}")
        
        # Create database instance (this will create tables)
        db = DocumentDatabase(database_url)
        
        logger.info("Database tables created successfully")
        
        # Test the connection by getting stats
        stats = db.get_processing_stats()
        logger.info(f"Database initialized. Current stats: {stats}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error initializing database: {str(e)}")
        return False

def create_sample_data():
    """
    Create some sample data for testing (optional)
    """
    try:
        database_url = ENV_VARIABLES.get('DATABASE_URL', 'sqlite:///./documents.db')
        db = DocumentDatabase(database_url)
        
        # This could be expanded to create sample records for testing
        logger.info("Sample data creation function ready (no data created by default)")
        
        return True
        
    except Exception as e:
        logger.error(f"Error creating sample data: {str(e)}")
        return False

if __name__ == "__main__":
    """
    Run the database initialization script directly
    """
    print("🏗️  Initializing OCR Document Processing Database...")
    
    success = init_database()
    
    if success:
        print("✅ Database initialization completed successfully!")
        
        # Optionally create sample data (uncomment if needed)
        # print("📝 Creating sample data...")
        # create_sample_data()
        
    else:
        print("❌ Database initialization failed!")
        sys.exit(1) 
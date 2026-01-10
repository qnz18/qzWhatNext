"""Migration script to update task categories.

Maps old categories to new categories:
- social → family
- stress → personal
- other → unknown

Run this script before deploying the new category system.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from qzwhatnext.database.database import SessionLocal, engine
from qzwhatnext.database.models import TaskDB
from sqlalchemy import text


def migrate_categories():
    """Migrate task categories from old to new values."""
    
    db = SessionLocal()
    
    try:
        # Category mapping: old → new
        category_mapping = {
            'social': 'family',
            'stress': 'personal',
            'other': 'unknown',
        }
        
        print("Starting category migration...")
        
        # Get all tasks with old categories
        tasks_to_migrate = []
        for old_cat, new_cat in category_mapping.items():
            tasks = db.query(TaskDB).filter(TaskDB.category == old_cat).all()
            if tasks:
                print(f"Found {len(tasks)} tasks with category '{old_cat}' to migrate to '{new_cat}'")
                tasks_to_migrate.extend([(task, new_cat) for task in tasks])
        
        if not tasks_to_migrate:
            print("No tasks need migration.")
            return
        
        # Update tasks
        updated_count = 0
        for task, new_category in tasks_to_migrate:
            task.category = new_category
            updated_count += 1
        
        # Commit changes
        db.commit()
        print(f"Successfully migrated {updated_count} tasks.")
        
    except Exception as e:
        db.rollback()
        print(f"Error during migration: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print("=" * 60)
    print("Task Category Migration Script")
    print("=" * 60)
    print()
    print("This script will update task categories:")
    print("  social → family")
    print("  stress → personal")
    print("  other → unknown")
    print()
    
    response = input("Do you want to proceed? (yes/no): ")
    if response.lower() in ['yes', 'y']:
        migrate_categories()
        print()
        print("Migration complete!")
    else:
        print("Migration cancelled.")


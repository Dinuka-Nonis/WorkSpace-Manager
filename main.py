"""
WorkSpace Manager - Entry Point
Simple test version to verify setup works.
"""

import sys
import logging
from pathlib import Path

# Setup basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s | %(message)s'
)
logger = logging.getLogger("workspace")

def main():
    print("=" * 60)
    print("🗂  WorkSpace Manager - Test Mode")
    print("=" * 60)
    print()
    
    # Test 1: Check Python version
    print("✓ Python version:", sys.version.split()[0])
    
    # Test 2: Try importing models
    try:
        from src.db.models import Session, SessionStatus
        from datetime import datetime
        
        session = Session(
            id=None,
            name="Test Session",
            desktop_id="test-guid",
            status=SessionStatus.ACTIVE,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        print("✓ Database models work")
        print(f"  Created test session: '{session.name}'")
    except Exception as e:
        print(f"✗ Models failed: {e}")
        return
    
    # Test 3: Try creating database
    try:
        from src.db.database import Database
        
        db_path = Path.home() / "AppData" / "Roaming" / "WorkSpace" / "test.db"
        db = Database(db_path)
        db.connect()
        
        # Try creating a session
        created = db.create_session(session)
        print(f"✓ Database works")
        print(f"  Session saved with ID: {created.id}")
        
        # Try reading it back
        sessions = db.get_all_sessions()
        print(f"  Sessions in DB: {len(sessions)}")
        
        db.close()
        
        # Cleanup test db
        if db_path.exists():
            db_path.unlink()
            db_path.parent.rmdir() if not list(db_path.parent.iterdir()) else None
            
    except Exception as e:
        print(f"✗ Database failed: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Test 4: Check Windows APIs (if available)
    print()
    print("Checking Windows APIs:")
    try:
        import win32gui
        print("  ✓ win32gui available")
    except ImportError:
        print("  ✗ win32gui not installed (pip install pywin32)")
    
    try:
        import pyvda
        print("  ✓ pyvda available")
    except ImportError:
        print("  ✗ pyvda not installed (pip install pyvda)")
    
    try:
        import psutil
        print("  ✓ psutil available")
    except ImportError:
        print("  ✗ psutil not installed")
    
    try:
        import keyboard
        print("  ✓ keyboard available")
    except ImportError:
        print("  ✗ keyboard not installed")
    
    print()
    print("=" * 60)
    print("✓ Core functionality verified!")
    print("=" * 60)
    print()
    print("Next step: Install dependencies with:")
    print("  pip install -r requirements.txt")


if __name__ == "__main__":
    main()

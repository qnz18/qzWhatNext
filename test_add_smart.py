#!/usr/bin/env python3
"""Test script for /tasks/add_smart endpoint."""

import requests
import json

def test_add_smart_task():
    """Test the /tasks/add_smart endpoint."""
    url = "http://localhost:8000/tasks/add_smart"
    
    payload = {
        "notes": "This is a test note from Python script"
    }
    
    print("Testing /tasks/add_smart endpoint...")
    print(f"URL: {url}")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    print()
    
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        
        print("✅ Success!")
        print(f"Status Code: {response.status_code}")
        print("\nResponse:")
        print(json.dumps(response.json(), indent=2))
        
        # Extract task info
        task = response.json().get("task", {})
        print(f"\n📝 Created Task:")
        print(f"   ID: {task.get('id')}")
        print(f"   Title: {task.get('title')}")
        print(f"   Notes: {task.get('notes')}")
        print(f"   Created: {task.get('created_at')}")
        
    except requests.exceptions.ConnectionError:
        print("❌ Error: Could not connect to server.")
        print("   Make sure the server is running: python run.py")
    except requests.exceptions.HTTPError as e:
        print(f"❌ HTTP Error: {e}")
        print(f"   Response: {response.text}")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    test_add_smart_task()


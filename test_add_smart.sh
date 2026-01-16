#!/bin/bash
# Test script for /tasks/add_smart endpoint

echo "Testing /tasks/add_smart endpoint..."
echo ""

curl -X POST "http://localhost:8000/tasks/add_smart" \
  -H "Content-Type: application/json" \
  -d '{"notes": "This is a test note from my MacBook"}'

echo ""
echo ""
echo "Test complete!"



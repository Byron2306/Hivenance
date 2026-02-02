#!/bin/bash

echo "============================================"
echo " Hivenance Desktop UI - Quick Launcher"
echo "============================================"
echo ""

# Check if node_modules exists
if [ ! -d "node_modules" ]; then
    echo "Installing dependencies..."
    npm install
    if [ $? -ne 0 ]; then
        echo "Failed to install dependencies!"
        exit 1
    fi
    echo ""
fi

echo "Starting Hivenance Desktop UI..."
echo ""
echo "Make sure your backend is running at http://127.0.0.1:5000"
echo ""

npm start

#!/usr/bin/env python3
"""Run script for qzWhatNext."""

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "qzwhatnext.api.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )


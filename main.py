import os
import sys
import uvicorn

sys.path.insert(0, os.path.abspath("."))
from app import app

__all__ = ["app"]

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run(app, host=host, port=port)

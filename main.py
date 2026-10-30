import os
import sys

import uvicorn

# Setup paths
sys.path.insert(0, os.path.abspath("."))

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run("main:app", host=host, port=port, reload=False)

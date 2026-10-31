import os
import sys

# Forward all arguments and logic to src.predict
sys.path.insert(0, os.path.abspath("."))
from src.predict import main

if __name__ == "__main__":
    main()

import subprocess
import sys

# Try to run the Python script
result = subprocess.run(
    [sys.executable, 'C:\\Users\\arhou\\OneDrive\\Bureau\\PFE.0\\run_verify.py'],
    capture_output=False,
    text=True
)
sys.exit(result.returncode)

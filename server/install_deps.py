import subprocess
import sys
import os
from concurrent.futures import ThreadPoolExecutor
import time

def install_package(package):
    try:
        print(f"Installing {package}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        print(f"Successfully installed {package}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error installing {package}: {e}")
        return False

def main():
    # Read requirements.txt
    with open('requirements.txt', 'r') as f:
        requirements = [line.strip() for line in f if line.strip() and not line.startswith('#')]

    print("Starting parallel installation of dependencies...")
    start_time = time.time()

    # Install packages in parallel
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(install_package, requirements))

    # Check if all installations were successful
    if all(results):
        print(f"\nAll dependencies installed successfully in {time.time() - start_time:.2f} seconds")
    else:
        print("\nSome dependencies failed to install. Please check the errors above.")
        sys.exit(1)

if __name__ == "__main__":
    main() 
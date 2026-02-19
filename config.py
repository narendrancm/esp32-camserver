import os
from dotenv import load_dotenv

load_dotenv()

# Flask/FastAPI Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "your-super-secret-key-change-this-123456")

# AWS Configuration
AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_KEY")
AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
AWS_BUCKET = os.getenv("AWS_BUCKET")

# Application Settings
IMAGES_PER_CAMERA = int(os.getenv("IMAGES_PER_CAMERA", 6))
CAMERA_TIMEOUT_MINUTES = float(os.getenv("CAMERA_TIMEOUT_MINUTES", 1))  # 1 minute timeout

# Debug S3 configuration
print("=== S3 DEBUG INFO ===")
print(f"AWS_ACCESS_KEY: {'✓ Set' if AWS_ACCESS_KEY else '✗ Not set'}")
print(f"AWS_SECRET_KEY: {'✓ Set' if AWS_SECRET_KEY else '✗ Not set'}")
print(f"AWS_REGION: {AWS_REGION}")
print(f"AWS_BUCKET: {AWS_BUCKET}")
print("=====================")

import os
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise ValueError("SECRET_KEY must be set in environment variables")

S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY")
S3_REGION = os.getenv("S3_REGION", "ap-south-1")
S3_BUCKET = os.getenv("S3_BUCKET")

if not all([S3_ACCESS_KEY, S3_SECRET_KEY, S3_BUCKET]):
    raise ValueError("S3 credentials (S3_ACCESS_KEY, S3_SECRET_KEY, S3_BUCKET) must be set")

IMAGES_PER_CAMERA = int(os.getenv("IMAGES_PER_CAMERA", 6))
CAMERA_TIMEOUT_MINUTES = float(os.getenv("CAMERA_TIMEOUT_MINUTES", 0.5))

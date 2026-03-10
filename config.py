import os
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise ValueError("SECRET_KEY must be set in environment variables")

AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_KEY")
AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
AWS_BUCKET = os.getenv("AWS_BUCKET")

IMAGES_PER_CAMERA = int(os.getenv("IMAGES_PER_CAMERA", 6))
CAMERA_TIMEOUT_MINUTES = float(os.getenv("CAMERA_TIMEOUT_MINUTES", 0.5))






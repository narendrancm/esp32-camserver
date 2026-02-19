import boto3
from botocore.exceptions import ClientError
from config import AWS_ACCESS_KEY, AWS_SECRET_KEY, AWS_REGION, AWS_BUCKET, IMAGES_PER_CAMERA
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize S3 client
try:
    s3_client = boto3.client(
        's3',
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY,
        region_name=AWS_REGION
    )
    logger.info("✅ S3 client initialized successfully")
except Exception as e:
    logger.error(f"❌ Failed to initialize S3 client: {e}")
    s3_client = None

def upload_to_s3(file_content, filename):
    """Upload file to S3 bucket"""
    if not s3_client:
        logger.error("S3 client not initialized")
        return False
    try:
        logger.info(f"📤 Uploading to S3: {filename}")
        s3_client.put_object(
            Bucket=AWS_BUCKET,
            Key=filename,
            Body=file_content,
            ContentType='image/jpeg'
        )
        logger.info(f"✅ Upload successful: {filename}")
        return True
    except ClientError as e:
        logger.error(f"❌ S3 upload error: {e}")
        return False

def get_presigned_url(filename, expiration=3600):
    """Generate presigned URL for S3 object"""
    if not s3_client:
        return None
    try:
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': AWS_BUCKET,
                'Key': filename,
                'ResponseContentType': 'image/jpeg',
                'ResponseContentDisposition': 'inline'
            },
            ExpiresIn=expiration
        )
        return url
    except ClientError as e:
        logger.error(f"❌ Presigned URL error for {filename}: {e}")
        return None

def list_camera_images(camera_id, display_limit=6, max_storage=5000):
    """
    List images for a camera from S3
    display_limit: Number of images to return for display (default 6)
    max_storage: Maximum images to consider from S3 (default 5000)
    """
    if not s3_client:
        return []
    try:
        logger.info(f"📋 Listing images for camera: {camera_id}")
        response = s3_client.list_objects_v2(
            Bucket=AWS_BUCKET,
            Prefix=f"{camera_id}/",
            MaxKeys=max_storage  # Get up to max_storage images from S3
        )
        
        if 'Contents' not in response:
            logger.info(f"No images found for camera: {camera_id}")
            return []
        
        # Sort by date, newest first
        objects = sorted(
            response['Contents'],
            key=lambda x: x['LastModified'],
            reverse=True
        )
        
        images = []
        # Only return display_limit images for the dashboard
        for obj in objects[:display_limit]:
            url = get_presigned_url(obj['Key'])
            if url:
                images.append({
                    'key': obj['Key'],
                    'url': url,
                    'timestamp': obj['LastModified'],
                    'size': obj['Size']
                })
        
        logger.info(f"Returning {len(images)} images for display (out of {len(objects)} total)")
        return images
    except ClientError as e:
        logger.error(f"❌ S3 list error for {camera_id}: {e}")
        return []

def delete_old_images(camera_id, keep_count=None):
    """Delete old images, keeping only the latest keep_count images"""
    if not s3_client:
        return
    
    # Use IMAGES_PER_CAMERA from config if keep_count not specified
    if keep_count is None:
        from config import IMAGES_PER_CAMERA
        keep_count = IMAGES_PER_CAMERA
    
    try:
        logger.info(f"Checking images for {camera_id}, keeping {keep_count} newest")
        response = s3_client.list_objects_v2(
            Bucket=AWS_BUCKET,
            Prefix=f"{camera_id}/",
            MaxKeys=keep_count + 100  # Get a few more to ensure we have enough
        )
        
        if 'Contents' not in response:
            return
        
        # Sort by date (oldest first for deletion)
        objects = sorted(response['Contents'], key=lambda x: x['LastModified'])
        
        # Delete only if we have more than keep_count
        if len(objects) > keep_count:
            to_delete = objects[:-keep_count]  # Keep newest keep_count
            logger.info(f"Deleting {len(to_delete)} old images, keeping {keep_count}")
            
            for obj in to_delete:
                logger.info(f"🗑 Deleting old image: {obj['Key']}")
                s3_client.delete_object(Bucket=AWS_BUCKET, Key=obj['Key'])
        else:
            logger.info(f"Only {len(objects)} images, keeping all (max {keep_count})")
            
    except ClientError as e:
        logger.error(f"❌ S3 delete error for {camera_id}: {e}")

import boto3
from botocore.exceptions import ClientError
from config import AWS_ACCESS_KEY, AWS_SECRET_KEY, AWS_REGION, AWS_BUCKET, MAX_STORAGE_GB
from datetime import datetime
import logging

# Set up logging
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
        
        # Get file size from the bytes object
        file_size = len(file_content)
        logger.info(f"📏 File size: {file_size} bytes")
        
        # Check storage before uploading
        if not check_storage_limit(file_size):
            logger.warning("⚠️ Storage limit reached, cleaning up old images...")
            cleanup_storage(file_size)
        
        response = s3_client.put_object(
            Bucket=AWS_BUCKET,
            Key=filename,
            Body=file_content,
            ContentType='image/jpeg',
            Metadata={
                'upload_time': datetime.utcnow().isoformat()
            }
        )
        logger.info(f"✅ Upload successful: {filename}")
        return True
    except ClientError as e:
        logger.error(f"❌ S3 upload error: {e}")
        return False

def check_storage_limit(new_file_size_bytes):
    """Check if adding new file would exceed storage limit"""
    if not s3_client:
        return True
        
    try:
        # Get total bucket size
        response = s3_client.list_objects_v2(Bucket=AWS_BUCKET)
        
        total_size_bytes = 0
        if 'Contents' in response:
            total_size_bytes = sum(obj['Size'] for obj in response['Contents'])
        
        max_size_bytes = MAX_STORAGE_GB * 1024 * 1024 * 1024
        
        logger.info(f"📊 Current storage: {total_size_bytes / (1024*1024):.2f}MB / {MAX_STORAGE_GB}GB")
        logger.info(f"📊 New file size: {new_file_size_bytes / 1024:.2f}KB")
        
        # Check if adding new file would exceed limit
        would_exceed = (total_size_bytes + new_file_size_bytes) > max_size_bytes
        if would_exceed:
            logger.warning(f"⚠️ Would exceed limit: {total_size_bytes + new_file_size_bytes} > {max_size_bytes}")
        
        return not would_exceed
        
    except ClientError as e:
        logger.error(f"❌ Storage check error: {e}")
        return True

def cleanup_storage(new_file_size_bytes):
    """Delete oldest images until enough space is available"""
    if not s3_client:
        return
        
    try:
        # Get all objects sorted by last modified (oldest first)
        response = s3_client.list_objects_v2(Bucket=AWS_BUCKET)
        
        if 'Contents' not in response:
            return
            
        # Sort by last modified (oldest first)
        objects = sorted(
            response['Contents'],
            key=lambda x: x['LastModified']
        )
        
        total_size_bytes = sum(obj['Size'] for obj in objects)
        max_size_bytes = MAX_STORAGE_GB * 1024 * 1024 * 1024
        target_size_bytes = max_size_bytes - new_file_size_bytes
        
        logger.info(f"🧹 Need to free up space. Target: {target_size_bytes / (1024*1024):.2f}MB")
        
        # Delete oldest files until under limit
        to_delete = []
        current_size_bytes = total_size_bytes
        
        for obj in objects:
            if current_size_bytes <= target_size_bytes:
                break
            to_delete.append(obj)
            current_size_bytes -= obj['Size']
        
        if to_delete:
            logger.info(f"🗑️ Deleting {len(to_delete)} oldest images to free up space")
            for obj in to_delete:
                logger.info(f"   Deleting: {obj['Key']} from {obj['LastModified']}")
                s3_client.delete_object(Bucket=AWS_BUCKET, Key=obj['Key'])
        else:
            logger.info("✅ No need to delete any images")
                
    except ClientError as e:
        logger.error(f"❌ Cleanup error: {e}")

def get_presigned_url(filename, expiration=3600):
    """Generate presigned URL for S3 object"""
    if not s3_client:
        logger.error("S3 client not initialized")
        return None
        
    try:
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': AWS_BUCKET, 
                'Key': filename,
                'ResponseContentType': 'image/jpeg'
            },
            ExpiresIn=expiration
        )
        return url
    except ClientError as e:
        logger.error(f"❌ Presigned URL error for {filename}: {e}")
        return None

def list_camera_images(camera_id, max_images=6):
    """List images for a camera from S3, sorted newest first (for display)"""
    if not s3_client:
        logger.error("S3 client not initialized")
        return []
        
    try:
        logger.info(f"📋 Listing images for camera: {camera_id}")
        
        # Use list_objects_v2 to get all objects with the prefix
        response = s3_client.list_objects_v2(
            Bucket=AWS_BUCKET,
            Prefix=f"{camera_id}/",
            MaxKeys=100
        )
        
        if 'Contents' not in response:
            logger.info(f"No images found for camera: {camera_id}")
            return []
        
        logger.info(f"Found {len(response['Contents'])} total images for {camera_id}")
        
        # Sort by LastModified in DESCENDING order (newest first) for DISPLAY
        objects = sorted(
            response['Contents'],
            key=lambda x: x['LastModified'],
            reverse=True  # Newest first for display!
        )
        
        if objects:
            logger.info(f"Newest image timestamp: {objects[0]['LastModified']}")
            logger.info(f"Oldest image timestamp: {objects[-1]['LastModified']}")
        
        # Get only the latest max_images for display
        images = []
        for i, obj in enumerate(objects[:max_images]):
            # Generate presigned URL for each image
            url = get_presigned_url(obj['Key'])
            if url:
                image_data = {
                    'key': obj['Key'],
                    'url': url,
                    'timestamp': obj['LastModified'].isoformat(),
                    'size': obj['Size'],
                    'display_order': i + 1
                }
                images.append(image_data)
                logger.info(f"✅ Display image {i+1}: {obj['Key']} - {obj['LastModified']}")
        
        logger.info(f"Returning {len(images)} images for display for {camera_id}")
        return images
        
    except ClientError as e:
        logger.error(f"❌ S3 list error for {camera_id}: {e}")
        return []

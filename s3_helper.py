import boto3
from botocore.exceptions import ClientError
from config import AWS_ACCESS_KEY, AWS_SECRET_KEY, AWS_REGION, AWS_BUCKET
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
    
    # Test bucket access
    s3_client.head_bucket(Bucket=AWS_BUCKET)
    logger.info(f"✅ Successfully accessed bucket: {AWS_BUCKET}")
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

def get_presigned_url(filename, expiration=3600):
    """Generate presigned URL for S3 object"""
    if not s3_client:
        logger.error("S3 client not initialized")
        return None
        
    try:
        logger.info(f"🔑 Generating presigned URL for: {filename}")
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
        logger.info(f"✅ Presigned URL generated for: {filename}")
        return url
    except ClientError as e:
        logger.error(f"❌ Presigned URL error for {filename}: {e}")
        return None

def list_camera_images(camera_id, max_images=10):
    """List images for a camera from S3, sorted newest first"""
    if not s3_client:
        logger.error("S3 client not initialized")
        return []
        
    try:
        logger.info(f"📋 Listing images for camera: {camera_id}")
        
        # Use list_objects_v2 to get all objects with the prefix
        response = s3_client.list_objects_v2(
            Bucket=AWS_BUCKET,
            Prefix=f"{camera_id}/",
            MaxKeys=100  # Get up to 100 images to sort
        )
        
        if 'Contents' not in response:
            logger.info(f"No images found for camera: {camera_id}")
            return []
        
        logger.info(f"Found {len(response['Contents'])} total images for {camera_id}")
        
        # Sort by last modified in DESCENDING order (newest first)
        objects = sorted(
            response['Contents'],
            key=lambda x: x['LastModified'],
            reverse=True
        )
        
        logger.info(f"Newest image: {objects[0]['Key']} - {objects[0]['LastModified']}")
        
        # Get only the latest max_images
        images = []
        for obj in objects[:max_images]:
            # Generate presigned URL for each image
            url = get_presigned_url(obj['Key'])
            if url:
                images.append({
                    'key': obj['Key'],
                    'url': url,  # This is the critical part!
                    'timestamp': obj['LastModified'].isoformat(),
                    'size': obj['Size']
                })
                logger.info(f"✅ Added image: {obj['Key']} with URL")
            else:
                logger.warning(f"⚠️ Failed to generate URL for: {obj['Key']}")
        
        logger.info(f"Returning {len(images)} images for {camera_id}")
        return images
        
    except ClientError as e:
        logger.error(f"❌ S3 list error for {camera_id}: {e}")
        return []

def delete_old_images(camera_id, keep_count=10):
    """Delete old images, keeping only the latest keep_count images"""
    if not s3_client:
        logger.error("S3 client not initialized")
        return
        
    try:
        logger.info(f"🗑️ Checking for old images to delete for {camera_id}")
        response = s3_client.list_objects_v2(
            Bucket=AWS_BUCKET,
            Prefix=f"{camera_id}/",
            MaxKeys=100
        )
        
        if 'Contents' not in response:
            return
        
        total_images = len(response['Contents'])
        logger.info(f"Found {total_images} total images for {camera_id}")
        
        # Sort by last modified (oldest first) to delete oldest
        objects = sorted(
            response['Contents'],
            key=lambda x: x['LastModified']
        )
        
        # Delete all except the latest keep_count
        to_delete = objects[:-keep_count] if len(objects) > keep_count else []
        
        if to_delete:
            logger.info(f"Deleting {len(to_delete)} old images, keeping latest {keep_count}")
            for obj in to_delete:
                logger.info(f"🗑️ Deleting old image: {obj['Key']}")
                s3_client.delete_object(Bucket=AWS_BUCKET, Key=obj['Key'])
        else:
            logger.info(f"No old images to delete")
            
    except ClientError as e:
        logger.error(f"❌ S3 delete error for {camera_id}: {e}")

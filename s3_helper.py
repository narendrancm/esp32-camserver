import boto3
from botocore.exceptions import ClientError
from config import AWS_ACCESS_KEY, AWS_SECRET_KEY, AWS_REGION, AWS_BUCKET
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


def list_camera_images(camera_id, max_images=10):
    """List images for a camera from S3"""
    if not s3_client:
        return []
    try:
        logger.info(f"📋 Listing images for camera: {camera_id}")
        response = s3_client.list_objects_v2(
            Bucket=AWS_BUCKET,
            Prefix=f"{camera_id}/",
            MaxKeys=100
        )
        if 'Contents' not in response:
            return []
        objects = sorted(
            response['Contents'],
            key=lambda x: x['LastModified'],
            reverse=True
        )
        images = []
        for obj in objects[:max_images]:
            url = get_presigned_url(obj['Key'])
            if url:
                images.append({
                    'key': obj['Key'],
                    'url': url,
                    'timestamp': obj['LastModified'],
                    'size': obj['Size']
                })
        return images
    except ClientError as e:
        logger.error(f"❌ S3 list error for {camera_id}: {e}")
        return []


def delete_old_images(camera_id, keep_count=10):
    """Delete old images, keeping only the latest keep_count images"""
    if not s3_client:
        return
    try:
        response = s3_client.list_objects_v2(
            Bucket=AWS_BUCKET,
            Prefix=f"{camera_id}/",
            MaxKeys=100
        )
        if 'Contents' not in response:
            return
        objects = sorted(response['Contents'], key=lambda x: x['LastModified'])
        to_delete = objects[:-keep_count] if len(objects) > keep_count else []
        for obj in to_delete:
            logger.info(f"🗑 Deleting old image: {obj['Key']}")
            s3_client.delete_object(Bucket=AWS_BUCKET, Key=obj['Key'])
    except ClientError as e:
        logger.error(f"❌ S3 delete error for {camera_id}: {e}")

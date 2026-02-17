import boto3
from botocore.exceptions import ClientError
from config import AWS_ACCESS_KEY, AWS_SECRET_KEY, AWS_REGION, AWS_BUCKET
from datetime import datetime

# Initialize S3 client
s3_client = boto3.client(
    's3',
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY,
    region_name=AWS_REGION
)

def upload_to_s3(file_content, filename):
    """Upload file to S3 bucket"""
    try:
        s3_client.put_object(
            Bucket=AWS_BUCKET,
            Key=filename,
            Body=file_content,
            ContentType='image/jpeg'
        )
        return True
    except ClientError as e:
        print(f"S3 upload error: {e}")
        return False

def get_presigned_url(filename, expiration=3600):
    """Generate presigned URL for S3 object"""
    try:
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': AWS_BUCKET, 'Key': filename},
            ExpiresIn=expiration
        )
        return url
    except ClientError as e:
        print(f"Presigned URL error: {e}")
        return None

def list_camera_images(camera_id, max_images=6):
    """List images for a camera from S3"""
    try:
        response = s3_client.list_objects_v2(
            Bucket=AWS_BUCKET,
            Prefix=f"{camera_id}/",
            MaxKeys=100
        )
        
        if 'Contents' not in response:
            return []
        
        # Sort by last modified (newest first)
        objects = sorted(
            response['Contents'],
            key=lambda x: x['LastModified'],
            reverse=True
        )
        
        # Get only the latest max_images
        images = []
        for obj in objects[:max_images]:
            images.append({
                'key': obj['Key'],
                'timestamp': obj['LastModified'],
                'size': obj['Size']
            })
        
        return images
    except ClientError as e:
        print(f"S3 list error: {e}")
        return []

def delete_old_images(camera_id, keep_count=6):
    """Delete old images, keeping only the latest keep_count images"""
    try:
        response = s3_client.list_objects_v2(
            Bucket=AWS_BUCKET,
            Prefix=f"{camera_id}/",
            MaxKeys=100
        )
        
        if 'Contents' not in response:
            return
        
        # Sort by last modified (oldest first)
        objects = sorted(
            response['Contents'],
            key=lambda x: x['LastModified']
        )
        
        # Delete all except the latest keep_count
        to_delete = objects[:-keep_count] if len(objects) > keep_count else []
        
        for obj in to_delete:
            s3_client.delete_object(Bucket=AWS_BUCKET, Key=obj['Key'])
            print(f"Deleted old image: {obj['Key']}")
            
    except ClientError as e:
        print(f"S3 delete error: {e}")
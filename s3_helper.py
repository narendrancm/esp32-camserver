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
        print(f"✅ Uploaded to S3: {filename}")
        return True
    except ClientError as e:
        print(f"❌ S3 upload error: {e}")
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
        print(f"❌ Presigned URL error: {e}")
        return None

def list_camera_images(camera_id, max_images=6):
    """
    List images for a camera from S3
    Returns ONLY the latest 'max_images' images for display
    All images are kept in S3 permanently
    """
    try:
        print(f"📸 Listing images for camera: {camera_id}")
        
        # List ALL objects with this camera prefix
        all_images = []
        continuation_token = None
        
        while True:
            list_params = {
                'Bucket': AWS_BUCKET,
                'Prefix': f"{camera_id}/",
                'MaxKeys': 1000  # Get up to 1000 at a time
            }
            
            if continuation_token:
                list_params['ContinuationToken'] = continuation_token
            
            # Get batch of objects
            response = s3_client.list_objects_v2(**list_params)
            
            if 'Contents' in response:
                all_images.extend(response['Contents'])
            
            # Check if there are more
            if not response.get('IsTruncated'):
                break
            continuation_token = response.get('NextContinuationToken')
        
        if not all_images:
            print(f"  No images found for camera {camera_id}")
            return []
        
        # Sort by last modified (newest first)
        all_images.sort(key=lambda x: x['LastModified'], reverse=True)
        
        # FORCE only the latest max_images for display
        display_images = all_images[:max_images]
        
        print(f"📸 Total in S3: {len(all_images)}, Returning for display: {len(display_images)}")
        
        images = []
        for obj in display_images:
            images.append({
                'key': obj['Key'],
                'timestamp': obj['LastModified'],
                'size': obj['Size']
            })
        
        return images
        
    except ClientError as e:
        print(f"❌ S3 list error: {e}")
        return []

def delete_old_images(camera_id, keep_count=6):
    """
    DELETE FUNCTION DISABLED - Keeping all images for surveillance
    This function intentionally does nothing to preserve all images
    """
    print(f"📸 SURVEILLANCE MODE: Keeping ALL images for camera {camera_id}")
    return

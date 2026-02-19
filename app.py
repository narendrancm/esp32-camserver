from fastapi import FastAPI, Request, HTTPException, Depends, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Optional
import os, traceback, boto3
from config import SECRET_KEY, IMAGES_PER_CAMERA, CAMERA_TIMEOUT_MINUTES
from models import Base, User, Camera, CameraShare, engine, get_db
from auth import hash_password, verify_password
from s3_helper import upload_to_s3, get_presigned_url, list_camera_images, delete_old_images

app = FastAPI(title='Surveillance Cam')
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
templates = Jinja2Templates(directory='templates')
Base.metadata.create_all(bind=engine)

def create_default_admin():
    db = next(get_db())
    admin = db.query(User).filter(User.username == 'admin').first()
    if not admin:
        db.add(User(username='admin', email='admin@example.com',
                password_hash=hash_password('admin123')))
        db.commit()
        print('✓ Default admin user created')
    db.close()

create_default_admin()

def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    user_id = request.session.get('user_id')
    if not user_id: return None
    return db.query(User).filter(User.id == user_id).first()

def require_login(request: Request, db: Session = Depends(get_db)) -> User:
    user = get_current_user(request, db)
    if not user: raise HTTPException(status_code=401, detail='Not authenticated')
    return user

@app.get('/', response_class=HTMLResponse)
async def root(request: Request):
    if request.session.get('user_id'): return RedirectResponse(url='/dashboard', status_code=302)
    return RedirectResponse(url='/login', status_code=302)

@app.get('/login', response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse('login.html', {'request': request, 'session': request.session})

@app.post('/login')
async def login(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    user = db.query(User).filter(User.username == form.get('username')).first()
    if not user or not verify_password(form.get('password'), user.password_hash):
        return templates.TemplateResponse('login.html', {'request': request,
                'session': request.session, 'error': 'Invalid username or password'})
    request.session['user_id'] = user.id
    request.session['username'] = user.username
    return RedirectResponse(url='/dashboard', status_code=302)

@app.get('/register', response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse('register.html', {'request': request, 'session': request.session})

@app.post('/register')
async def register(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    username, email = form.get('username'), form.get('email')
    password, confirm = form.get('password'), form.get('confirm_password')
    if password != confirm:
        return templates.TemplateResponse('register.html', {'request': request,
                'session': request.session, 'error': 'Passwords do not match'})
    if db.query(User).filter(User.username == username).first():
        return templates.TemplateResponse('register.html', {'request': request,
                'session': request.session, 'error': 'Username already exists'})
    if db.query(User).filter(User.email == email).first():
        return templates.TemplateResponse('register.html', {'request': request,
                'session': request.session, 'error': 'Email already registered'})
    new_user = User(username=username, email=email, password_hash=hash_password(password))
    db.add(new_user); db.commit()
    request.session['user_id'] = new_user.id
    request.session['username'] = new_user.username
    return RedirectResponse(url='/dashboard', status_code=302)

@app.get('/logout')
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url='/login', status_code=302)

@app.get('/dashboard', response_class=HTMLResponse)
async def dashboard(request: Request, user: User = Depends(require_login), db: Session = Depends(get_db)):
    owned_cameras = db.query(Camera).filter(Camera.user_id == user.id).all()
    shared_cameras = db.query(Camera).join(CameraShare, Camera.id == CameraShare.camera_id).filter(
        CameraShare.shared_with_user_id == user.id).all()
    all_cameras = []
    for camera in owned_cameras:
        all_cameras.append({'id': camera.id, 'camera_id': camera.camera_id,
                'name': camera.name, 'location': camera.location, 'is_active': camera.is_active,
                'last_seen': camera.last_seen.isoformat() if camera.last_seen else None,
                'created_at': camera.created_at.isoformat() if camera.created_at else None,
                'role': 'owner', 'can_edit': True})
    for camera in shared_cameras:
        share_info = db.query(CameraShare).filter(
            CameraShare.camera_id == camera.id,
            CameraShare.shared_with_user_id == user.id).first()
        all_cameras.append({'id': camera.id, 'camera_id': camera.camera_id,
                'name': camera.name, 'location': camera.location, 'is_active': camera.is_active,
                'last_seen': camera.last_seen.isoformat() if camera.last_seen else None,
                'created_at': camera.created_at.isoformat() if camera.created_at else None,
                'role': 'viewer', 'can_edit': share_info.can_edit if share_info else False})
    return templates.TemplateResponse('dashboard.html', {'request': request,
                'session': request.session, 'user': user, 'cameras': all_cameras})

@app.get('/cameras/new', response_class=HTMLResponse)
async def new_camera_page(request: Request, user: User = Depends(require_login)):
    return templates.TemplateResponse('edit_camera.html', {'request': request,
                'session': request.session, 'user': user, 'camera': None, 'action': 'Add'})

@app.post('/cameras/new')
async def create_camera(request: Request, user: User = Depends(require_login), db: Session = Depends(get_db)):
    form = await request.form()
    camera_id, name, location = form.get('camera_id'), form.get('name'), form.get('location')
    if db.query(Camera).filter(Camera.camera_id == camera_id).first():
        return templates.TemplateResponse('edit_camera.html', {'request': request,
                'session': request.session, 'user': user, 'camera': None, 'action': 'Add',
                'error': 'Camera ID already exists'})
    db.add(Camera(camera_id=camera_id, name=name, location=location, user_id=user.id))
    db.commit()
    return RedirectResponse(url='/dashboard', status_code=302)

@app.post('/cameras/{camera_id}/delete')
async def delete_camera(camera_id: str, user: User = Depends(require_login), db: Session = Depends(get_db)):
    camera = db.query(Camera).filter(Camera.camera_id == camera_id, Camera.user_id == user.id).first()
    if not camera: raise HTTPException(status_code=404, detail='Camera not found or not yours')
    db.query(CameraShare).filter(CameraShare.camera_id == camera.id).delete()
    db.delete(camera); db.commit()
    return RedirectResponse(url='/dashboard', status_code=302)

@app.post('/upload')
async def upload_image(camera_id: str = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db)):
    print(f'\n📸 UPLOAD from Camera ID: {camera_id}')
    try:
        camera = db.query(Camera).filter(Camera.camera_id == camera_id).first()
        if not camera:
            camera = Camera(camera_id=camera_id, name=f'Camera {camera_id}',
                    location='Auto-detected', user_id=1)
            db.add(camera); db.flush()
        camera.last_seen = datetime.utcnow()
        db.commit()
        
        file_content = await file.read()
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'{camera_id}/{timestamp}.jpg'
        
        success = upload_to_s3(file_content, filename)
        if success:
            # This now uses IMAGES_PER_CAMERA from config (5000)
            delete_old_images(camera_id)
            return JSONResponse({'status': 'success', 'message': 'Image uploaded'})
        return JSONResponse({'status': 'error', 'message': 'S3 upload failed'}, status_code=500)
    except Exception as e:
        traceback.print_exc()
        return JSONResponse({'status': 'error', 'message': str(e)}, status_code=500)

@app.get('/api/images/{camera_id}')
async def get_camera_images(
    camera_id: str, 
    user: User = Depends(require_login), 
    db: Session = Depends(get_db)
):
    """Get images for dashboard - returns only 6 most recent"""
    camera = db.query(Camera).filter(Camera.camera_id == camera_id).first()
    if not camera: 
        raise HTTPException(status_code=404, detail='Camera not found')
    
    is_owner = camera.user_id == user.id
    is_shared = db.query(CameraShare).filter(
        CameraShare.camera_id == camera.id,
        CameraShare.shared_with_user_id == user.id).first() is not None
    
    if not (is_owner or is_shared): 
        raise HTTPException(status_code=403, detail='Access denied')
    
    # Pass display_limit=6 to show only 6 images
    images = list_camera_images(camera_id, display_limit=6, max_storage=5000)
    
    image_data = []
    for img in images:
        url = get_presigned_url(img['key'])
        if url:
            image_data.append({
                'url': url, 
                'timestamp': img['timestamp'].isoformat(),
                'size': img['size'], 
                'key': img['key']
            })
    
    return JSONResponse({'images': image_data, 'camera_id': camera_id})

@app.get('/api/images/all/{camera_id}')
async def get_all_camera_images(
    camera_id: str, 
    limit: int = 50,
    user: User = Depends(require_login), 
    db: Session = Depends(get_db)
):
    """Get all images for a camera (for modal view)"""
    camera = db.query(Camera).filter(Camera.camera_id == camera_id).first()
    if not camera: 
        raise HTTPException(status_code=404, detail='Camera not found')
    
    is_owner = camera.user_id == user.id
    is_shared = db.query(CameraShare).filter(
        CameraShare.camera_id == camera.id,
        CameraShare.shared_with_user_id == user.id).first() is not None
    
    if not (is_owner or is_shared): 
        raise HTTPException(status_code=403, detail='Access denied')
    
    # Get up to 'limit' images for display
    images = list_camera_images(camera_id, display_limit=limit, max_storage=5000)
    
    image_data = []
    for img in images:
        url = get_presigned_url(img['key'])
        if url:
            image_data.append({
                'url': url, 
                'timestamp': img['timestamp'].isoformat(),
                'size': img['size'], 
                'key': img['key']
            })
    
    return JSONResponse({'images': image_data, 'camera_id': camera_id})

@app.get('/api/camera/{camera_id}/status')
async def get_camera_status(camera_id: str, user: User = Depends(require_login), db: Session = Depends(get_db)):
    camera = db.query(Camera).filter(Camera.camera_id == camera_id).first()
    if not camera: raise HTTPException(status_code=404, detail='Camera not found')
    is_owner = camera.user_id == user.id
    is_shared = db.query(CameraShare).filter(
        CameraShare.camera_id == camera.id,
        CameraShare.shared_with_user_id == user.id).first() is not None
    if not (is_owner or is_shared): raise HTTPException(status_code=403, detail='Access denied')
    
    status = 'inactive'; last_seen_text = 'Never'
    if camera.last_seen:
        time_diff = datetime.utcnow() - camera.last_seen
        timeout = timedelta(minutes=CAMERA_TIMEOUT_MINUTES)
        status = 'active' if time_diff < timeout else 'inactive'
        seconds = int(time_diff.total_seconds())
        if seconds < 60: last_seen_text = f'{seconds}s ago'
        elif seconds < 3600: last_seen_text = f'{seconds // 60}m ago'
        elif seconds < 86400: last_seen_text = f'{seconds // 3600}h ago'
        else: last_seen_text = f'{seconds // 86400}d ago'
    
    can_edit = is_owner or (is_shared and db.query(CameraShare).filter(
        CameraShare.camera_id == camera.id,
        CameraShare.shared_with_user_id == user.id,
        CameraShare.can_edit == True).first() is not None)
    
    return JSONResponse({'status': status, 'last_seen': last_seen_text,
            'last_seen_datetime': camera.last_seen.isoformat() if camera.last_seen else None,
            'is_owner': is_owner, 'can_edit': can_edit})

@app.get('/test-s3')
async def test_s3():
    """Test S3 connection --- visit /test-s3 to verify everything works"""
    try:
        from s3_helper import s3_client
        from config import AWS_BUCKET, IMAGES_PER_CAMERA
        
        # Test bucket access
        try: 
            s3_client.head_bucket(Bucket=AWS_BUCKET)
            bucket_exists = True
        except: 
            bucket_exists = False
        
        # List objects
        response = s3_client.list_objects_v2(Bucket=AWS_BUCKET, MaxKeys=10)
        objects = [{'key': o['Key'], 'size': o['Size']} for o in response.get('Contents', [])]
        
        return {
            'bucket': AWS_BUCKET, 
            'bucket_exists': bucket_exists,
            'objects_found': len(objects), 
            'objects': objects,
            'images_per_camera': IMAGES_PER_CAMERA,
            'credentials_valid': True
        }
    except Exception as e:
        return {'error': str(e)}

@app.get('/debug')
async def debug_session(request: Request):
    return {'session': dict(request.session), 'cookies': request.cookies}

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=5000)

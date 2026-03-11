from fastapi import FastAPI, Request, HTTPException, Depends, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Optional
import os
import traceback

from config import SECRET_KEY, IMAGES_PER_CAMERA, CAMERA_TIMEOUT_MINUTES
from models import Base, User, Camera, CameraShare, engine, get_db
from auth import hash_password, verify_password
from s3_helper import upload_to_s3, get_presigned_url, list_camera_images

# Initialize FastAPI
app = FastAPI(title="Surveillance Cam")

# Add session middleware
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, max_age=86400)  # 24 hours

# Templates
templates = Jinja2Templates(directory="templates")

# Create database tables
Base.metadata.create_all(bind=engine)

# Create default admin user
def create_default_admin():
    db = next(get_db())
    admin = db.query(User).filter(User.username == "admin").first()
    if not admin:
        admin_user = User(
            username="admin",
            email="admin@example.com",
            password_hash=hash_password("admin123")
        )
        db.add(admin_user)
        db.commit()
        print("✓ Default admin user created")
    db.close()

create_default_admin()

# Health check endpoint (optional)
@app.get("/health")
async def health():
    return {"status": "ok"}

# Helper function to get current user
def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id).first()

# Helper function to require login
def require_login(request: Request, db: Session = Depends(get_db)) -> User:
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse(url="/dashboard", status_code=302)
    return RedirectResponse(url="/login", status_code=302)

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {
        "request": request,
        "session": request.session
    })

@app.post("/login")
async def login(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    username = form.get("username")
    password = form.get("password")
    
    user = db.query(User).filter(User.username == username).first()
    
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse("login.html", {
            "request": request,
            "session": request.session,
            "error": "Invalid username or password"
        })
    
    request.session["user_id"] = user.id
    request.session["username"] = user.username
    return RedirectResponse(url="/dashboard", status_code=302)

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {
        "request": request,
        "session": request.session
    })

@app.post("/register")
async def register(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    username = form.get("username")
    email = form.get("email")
    password = form.get("password")
    confirm_password = form.get("confirm_password")
    
    if password != confirm_password:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "session": request.session,
            "error": "Passwords do not match"
        })
    
    if db.query(User).filter(User.username == username).first():
        return templates.TemplateResponse("register.html", {
            "request": request,
            "session": request.session,
            "error": "Username already exists"
        })
    
    if db.query(User).filter(User.email == email).first():
        return templates.TemplateResponse("register.html", {
            "request": request,
            "session": request.session,
            "error": "Email already registered"
        })
    
    new_user = User(
        username=username,
        email=email,
        password_hash=hash_password(password)
    )
    db.add(new_user)
    db.commit()
    
    request.session["user_id"] = new_user.id
    request.session["username"] = new_user.username
    return RedirectResponse(url="/dashboard", status_code=302)

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login", status_code=302)
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        request.session.clear()
        return RedirectResponse(url="/login", status_code=302)
    
    # Get cameras owned by user
    owned_cameras = db.query(Camera).filter(Camera.user_id == user.id).all()
    
    # Get cameras shared with user
    shared_cameras = db.query(Camera).join(
        CameraShare, Camera.id == CameraShare.camera_id
    ).filter(
        CameraShare.shared_with_user_id == user.id
    ).all()
    
    # Convert all cameras to dictionaries
    all_cameras = []
    
    for camera in owned_cameras:
        all_cameras.append({
            'id': camera.id,
            'camera_id': camera.camera_id,
            'name': camera.name,
            'location': camera.location,
            'last_seen': camera.last_seen.isoformat() if camera.last_seen else None,
            'role': 'owner',
            'can_edit': True
        })
    
    for camera in shared_cameras:
        share_info = db.query(CameraShare).filter(
            CameraShare.camera_id == camera.id,
            CameraShare.shared_with_user_id == user.id
        ).first()
        
        all_cameras.append({
            'id': camera.id,
            'camera_id': camera.camera_id,
            'name': camera.name,
            'location': camera.location,
            'last_seen': camera.last_seen.isoformat() if camera.last_seen else None,
            'role': 'viewer',
            'can_edit': share_info.can_edit if share_info else False
        })
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "session": request.session,
        "user": user,
        "cameras": all_cameras
    })

@app.post("/upload")
async def upload_image(
    camera_id: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Upload image from ESP32-CAM"""
    print(f"\n📸 ===== UPLOAD RECEIVED =====")
    print(f"📸 Camera ID: {camera_id}")
    print(f"📸 Time: {datetime.now().strftime('%H:%M:%S')}")
    
    try:
        # Find or create camera
        camera = db.query(Camera).filter(Camera.camera_id == camera_id).first()
        
        if not camera:
            print(f"📸 Camera {camera_id} not found, creating new...")
            camera = Camera(
                camera_id=camera_id,
                name=f"Camera {camera_id}",
                location="Auto-detected",
                user_id=1  # Assign to admin by default
            )
            db.add(camera)
            db.flush()
        
        # Update last_seen timestamp
        camera.last_seen = datetime.utcnow()
        db.commit()
        
        # Read file content
        file_content = await file.read()
        print(f"📸 Read {len(file_content)} bytes from file")
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{camera_id}/{timestamp}.jpg"
        print(f"📸 Generated filename: {filename}")
        
        # Upload to S3
        success = upload_to_s3(file_content, filename)
        
        if success:
            print(f"✅ Upload successful to S3: {filename}")
            return JSONResponse({"status": "success", "message": "Image uploaded"})
        else:
            print(f"❌ S3 upload failed: {filename}")
            return JSONResponse(
                {"status": "error", "message": "S3 upload failed"},
                status_code=500
            )
            
    except Exception as e:
        print(f"❌ Upload error: {str(e)}")
        traceback.print_exc()
        return JSONResponse(
            {"status": "error", "message": str(e)},
            status_code=500
        )

@app.get("/api/images/{camera_id}")
async def get_camera_images(
    camera_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    """Get images for a camera - shows latest images"""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    
    camera = db.query(Camera).filter(Camera.camera_id == camera_id).first()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    # Check access
    is_owner = camera.user_id == user.id
    is_shared = db.query(CameraShare).filter(
        CameraShare.camera_id == camera.id,
        CameraShare.shared_with_user_id == user.id
    ).first() is not None
    
    if not (is_owner or is_shared):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Get images from S3
    images = list_camera_images(camera_id, IMAGES_PER_CAMERA)
    
    response = JSONResponse({
        "images": images,
        "camera_id": camera_id,
        "count": len(images),
        "timestamp": datetime.now().isoformat()
    })
    
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response

@app.get("/api/camera/{camera_id}/status")
async def get_camera_status(
    camera_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    
    camera = db.query(Camera).filter(Camera.camera_id == camera_id).first()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    # Check access
    is_owner = camera.user_id == user.id
    is_shared = db.query(CameraShare).filter(
        CameraShare.camera_id == camera.id,
        CameraShare.shared_with_user_id == user.id
    ).first() is not None
    
    if not (is_owner or is_shared):
        raise HTTPException(status_code=403, detail="Access denied")
    
    status = "inactive"
    last_seen_text = "Never"
    
    if camera.last_seen:
        time_diff = datetime.utcnow() - camera.last_seen
        timeout = timedelta(minutes=CAMERA_TIMEOUT_MINUTES)
        status = "active" if time_diff < timeout else "inactive"
        
        seconds = int(time_diff.total_seconds())
        if seconds < 60:
            last_seen_text = f"{seconds}s ago"
        elif seconds < 3600:
            last_seen_text = f"{seconds // 60}m ago"
        elif seconds < 86400:
            last_seen_text = f"{seconds // 3600}h ago"
        else:
            last_seen_text = f"{seconds // 86400}d ago"
    
    return JSONResponse({
        "status": status,
        "last_seen": last_seen_text,
        "timestamp": datetime.now().isoformat()
    })

# ... (include all other routes: share, edit, delete etc. from your original app.py)
# For brevity, I'm not repeating them here, but they should be the same as before.
# Make sure none of them call delete_old_images.

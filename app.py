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
from s3_helper import upload_to_s3, get_presigned_url, list_camera_images, delete_old_images

# Initialize FastAPI
app = FastAPI(title="Surveillance Cam")

# Add session middleware
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

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

# Routes
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
async def dashboard(request: Request, user: User = Depends(require_login), db: Session = Depends(get_db)):
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
    
    # Add owned cameras
    for camera in owned_cameras:
        all_cameras.append({
            'id': camera.id,
            'camera_id': camera.camera_id,
            'name': camera.name,
            'location': camera.location,
            'is_active': camera.is_active,
            'last_seen': camera.last_seen.isoformat() if camera.last_seen else None,
            'created_at': camera.created_at.isoformat() if camera.created_at else None,
            'role': 'owner',
            'can_edit': True
        })
    
    # Add shared cameras
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
            'is_active': camera.is_active,
            'last_seen': camera.last_seen.isoformat() if camera.last_seen else None,
            'created_at': camera.created_at.isoformat() if camera.created_at else None,
            'role': 'viewer',
            'can_edit': share_info.can_edit if share_info else False
        })
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "session": request.session,
        "user": user,
        "cameras": all_cameras
    })

@app.get("/cameras/new", response_class=HTMLResponse)
async def new_camera_page(request: Request, user: User = Depends(require_login)):
    return templates.TemplateResponse("edit_camera.html", {
        "request": request,
        "session": request.session,
        "user": user,
        "camera": None,
        "action": "Add"
    })

@app.post("/cameras/new")
async def create_camera(
    request: Request,
    user: User = Depends(require_login),
    db: Session = Depends(get_db)
):
    form = await request.form()
    camera_id = form.get("camera_id")
    name = form.get("name")
    location = form.get("location")
    
    # Check if camera_id already exists
    if db.query(Camera).filter(Camera.camera_id == camera_id).first():
        return templates.TemplateResponse("edit_camera.html", {
            "request": request,
            "session": request.session,
            "user": user,
            "camera": None,
            "action": "Add",
            "error": "Camera ID already exists"
        })
    
    new_camera = Camera(
        camera_id=camera_id,
        name=name,
        location=location,
        user_id=user.id
    )
    db.add(new_camera)
    db.commit()
    
    return RedirectResponse(url="/dashboard", status_code=302)

@app.get("/cameras/{camera_id}/edit", response_class=HTMLResponse)
async def edit_camera_page(
    camera_id: str,
    request: Request,
    user: User = Depends(require_login),
    db: Session = Depends(get_db)
):
    # Check if user owns this camera
    camera = db.query(Camera).filter(
        Camera.camera_id == camera_id,
        Camera.user_id == user.id
    ).first()
    
    if not camera:
        # Check if shared with edit permission
        shared = db.query(CameraShare).join(Camera).filter(
            Camera.camera_id == camera_id,
            CameraShare.shared_with_user_id == user.id,
            CameraShare.can_edit == True
        ).first()
        
        if shared:
            camera = shared.camera
        else:
            raise HTTPException(status_code=404, detail="Camera not found or no edit permission")
    
    return templates.TemplateResponse("edit_camera.html", {
        "request": request,
        "session": request.session,
        "user": user,
        "camera": camera,
        "action": "Edit"
    })

@app.post("/cameras/{camera_id}/edit")
async def update_camera(
    camera_id: str,
    request: Request,
    user: User = Depends(require_login),
    db: Session = Depends(get_db)
):
    # Check if user owns this camera
    camera = db.query(Camera).filter(
        Camera.camera_id == camera_id,
        Camera.user_id == user.id
    ).first()
    
    if not camera:
        # Check if shared with edit permission
        shared = db.query(CameraShare).join(Camera).filter(
            Camera.camera_id == camera_id,
            CameraShare.shared_with_user_id == user.id,
            CameraShare.can_edit == True
        ).first()
        
        if shared:
            camera = shared.camera
        else:
            raise HTTPException(status_code=404, detail="Camera not found or no edit permission")
    
    form = await request.form()
    camera.name = form.get("name")
    camera.location = form.get("location")
    db.commit()
    
    return RedirectResponse(url="/dashboard", status_code=302)

@app.post("/cameras/{camera_id}/delete")
async def delete_camera(
    camera_id: str,
    user: User = Depends(require_login),
    db: Session = Depends(get_db)
):
    # Only owner can delete
    camera = db.query(Camera).filter(
        Camera.camera_id == camera_id,
        Camera.user_id == user.id
    ).first()
    
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found or not yours")
    
    # Delete all shares first
    db.query(CameraShare).filter(CameraShare.camera_id == camera.id).delete()
    
    # Delete camera
    db.delete(camera)
    db.commit()
    
    return RedirectResponse(url="/dashboard", status_code=302)

# ========== CAMERA SHARING ROUTES ==========

@app.get("/cameras/{camera_id}/share", response_class=HTMLResponse)
async def share_camera_page(
    camera_id: str,
    request: Request,
    user: User = Depends(require_login),
    db: Session = Depends(get_db)
):
    """Page to manage who can see this camera"""
    # Check if user owns this camera
    camera = db.query(Camera).filter(
        Camera.camera_id == camera_id,
        Camera.user_id == user.id
    ).first()
    
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found or not yours")
    
    # Get all users this camera is shared with
    shares = db.query(CameraShare).filter(
        CameraShare.camera_id == camera.id
    ).all()
    
    # Get all other users (to show in sharing dropdown)
    other_users = db.query(User).filter(User.id != user.id).all()
    
    return templates.TemplateResponse("share_camera.html", {
        "request": request,
        "session": request.session,
        "user": user,
        "camera": camera,
        "shares": shares,
        "other_users": other_users
    })

@app.post("/cameras/{camera_id}/share")
async def share_camera(
    camera_id: str,
    request: Request,
    user: User = Depends(require_login),
    db: Session = Depends(get_db)
):
    """Share camera with another user"""
    form = await request.form()
    shared_user_id = form.get("user_id")
    can_edit = form.get("can_edit") == "on"
    
    # Check if user owns this camera
    camera = db.query(Camera).filter(
        Camera.camera_id == camera_id,
        Camera.user_id == user.id
    ).first()
    
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found or not yours")
    
    # Check if already shared
    existing = db.query(CameraShare).filter(
        CameraShare.camera_id == camera.id,
        CameraShare.shared_with_user_id == shared_user_id
    ).first()
    
    if existing:
        # Update existing share
        existing.can_edit = can_edit
    else:
        # Create new share
        share = CameraShare(
            camera_id=camera.id,
            shared_with_user_id=shared_user_id,
            can_edit=can_edit
        )
        db.add(share)
    
    db.commit()
    
    return RedirectResponse(url=f"/cameras/{camera_id}/share", status_code=302)

@app.post("/cameras/{camera_id}/unshare/{user_id}")
async def unshare_camera(
    camera_id: str,
    user_id: int,
    user: User = Depends(require_login),
    db: Session = Depends(get_db)
):
    """Remove sharing from a user"""
    # Check if user owns this camera
    camera = db.query(Camera).filter(
        Camera.camera_id == camera_id,
        Camera.user_id == user.id
    ).first()
    
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found or not yours")
    
    # Delete the share
    db.query(CameraShare).filter(
        CameraShare.camera_id == camera.id,
        CameraShare.shared_with_user_id == user_id
    ).delete()
    
    db.commit()
    
    return RedirectResponse(url=f"/cameras/{camera_id}/share", status_code=302)

# ========== API ROUTES ==========

@app.post("/upload")
async def upload_image(
    camera_id: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Upload image from ESP32-CAM"""
    print(f"\n📸 ===== UPLOAD RECEIVED =====")
    print(f"📸 Camera ID: {camera_id}")
    print(f"📸 File name: {file.filename}")
    
    try:
        # Find or create camera
        camera = db.query(Camera).filter(Camera.camera_id == camera_id).first()
        
        if not camera:
            print(f"📸 Camera {camera_id} not found, creating new...")
            # Auto-create camera if it doesn't exist
            camera = Camera(
                camera_id=camera_id,
                name=f"Camera {camera_id}",
                location="Auto-detected",
                user_id=1  # Assign to admin
            )
            db.add(camera)
            db.flush()
            print(f"📸 Created new camera with ID: {camera.id}")
        else:
            print(f"📸 Found existing camera: {camera.name} (ID: {camera.id})")
            print(f"📸 Old last_seen: {camera.last_seen}")
        
        # Update last_seen timestamp
        old_last_seen = camera.last_seen
        camera.last_seen = datetime.utcnow()
        print(f"📸 Updated last_seen from {old_last_seen} to {camera.last_seen}")
        
        db.commit()
        print(f"📸 Database committed successfully")
        
        # Read file content
        file_content = await file.read()
        print(f"📸 Read {len(file_content)} bytes from file")
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{camera_id}/{timestamp}.jpg"
        print(f"📸 Generated filename: {filename}")
        
        # Upload to S3
        print(f"📸 Uploading to S3...")
        success = upload_to_s3(file_content, filename)
        
        if success:
            print(f"✅ Upload successful to S3: {filename}")
            # Delete old images
            delete_old_images(camera_id, IMAGES_PER_CAMERA)
            print(f"✅ Upload complete for camera {camera_id}")
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
    user: User = Depends(require_login),
    db: Session = Depends(get_db)
):
    # Check if user has access to this camera
    camera = db.query(Camera).filter(Camera.camera_id == camera_id).first()
    
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    # Check access (owner or shared)
    is_owner = camera.user_id == user.id
    is_shared = db.query(CameraShare).filter(
        CameraShare.camera_id == camera.id,
        CameraShare.shared_with_user_id == user.id
    ).first() is not None
    
    if not (is_owner or is_shared):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Get images from S3
    images = list_camera_images(camera_id, IMAGES_PER_CAMERA)
    
    # Generate presigned URLs
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
    
    return JSONResponse({
        "images": image_data,
        "camera_id": camera_id
    })

@app.get("/api/camera/{camera_id}/status")
async def get_camera_status(
    camera_id: str,
    user: User = Depends(require_login),
    db: Session = Depends(get_db)
):
    # Check if user has access to this camera
    camera = db.query(Camera).filter(Camera.camera_id == camera_id).first()
    
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    # Check access (owner or shared)
    is_owner = camera.user_id == user.id
    is_shared = db.query(CameraShare).filter(
        CameraShare.camera_id == camera.id,
        CameraShare.shared_with_user_id == user.id
    ).first() is not None
    
    if not (is_owner or is_shared):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Determine if camera is active
    status = "inactive"
    last_seen_text = "Never"
    
    if camera.last_seen:
        time_diff = datetime.utcnow() - camera.last_seen
        timeout = timedelta(minutes=CAMERA_TIMEOUT_MINUTES)
        
        status = "active" if time_diff < timeout else "inactive"
        
        # Format last seen time
        seconds = int(time_diff.total_seconds())
        if seconds < 60:
            last_seen_text = f"{seconds}s ago"
        elif seconds < 3600:
            last_seen_text = f"{seconds // 60}m ago"
        elif seconds < 86400:
            last_seen_text = f"{seconds // 3600}h ago"
        else:
            last_seen_text = f"{seconds // 86400}d ago"
    
    # Check edit permission
    can_edit = is_owner or (is_shared and db.query(CameraShare).filter(
        CameraShare.camera_id == camera.id,
        CameraShare.shared_with_user_id == user.id,
        CameraShare.can_edit == True
    ).first() is not None)
    
    return JSONResponse({
        "status": status,
        "last_seen": last_seen_text,
        "last_seen_datetime": camera.last_seen.isoformat() if camera.last_seen else None,
        "is_owner": is_owner,
        "can_edit": can_edit
    })

@app.get("/debug")
async def debug_session(request: Request):
    """Debug endpoint to check session"""
    return {
        "session": dict(request.session),
        "cookies": request.cookies
    }

@app.get("/debug/camera/{camera_id}")
async def debug_camera(camera_id: str, db: Session = Depends(get_db)):
    """Debug endpoint to check camera details"""
    camera = db.query(Camera).filter(Camera.camera_id == camera_id).first()
    if not camera:
        return {"error": "Camera not found"}
    
    time_diff = (datetime.utcnow() - camera.last_seen).total_seconds() if camera.last_seen else None
    timeout_seconds = CAMERA_TIMEOUT_MINUTES * 60
    
    return {
        "camera_id": camera.camera_id,
        "name": camera.name,
        "location": camera.location,
        "user_id": camera.user_id,
        "last_seen": camera.last_seen.isoformat() if camera.last_seen else None,
        "last_seen_raw": str(camera.last_seen),
        "current_time": datetime.utcnow().isoformat(),
        "time_diff_seconds": time_diff,
        "timeout_seconds": timeout_seconds,
        "is_active": time_diff < timeout_seconds if time_diff else False,
        "CAMERA_TIMEOUT_MINUTES": CAMERA_TIMEOUT_MINUTES
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)

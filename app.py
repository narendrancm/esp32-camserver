from fastapi import FastAPI, Request, HTTPException, Depends, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from datetime import datetime, timedelta
from typing import Optional
import os
from pathlib import Path
import uuid
from config import SECRET_KEY, IMAGES_PER_CAMERA, CAMERA_TIMEOUT_MINUTES
from models import Base, User, Camera, engine, get_db
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
    cameras = db.query(Camera).filter(Camera.user_id == user.id).all()
    
    # Convert cameras to dictionaries for JSON serialization
    cameras_dict = []
    for camera in cameras:
        cameras_dict.append({
            'id': camera.id,
            'camera_id': camera.camera_id,
            'name': camera.name,
            'location': camera.location,
            'is_active': camera.is_active,
            'last_seen': camera.last_seen.isoformat() if camera.last_seen else None,
            'created_at': camera.created_at.isoformat() if camera.created_at else None
        })
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "session": request.session,
        "user": user,
        "cameras": cameras_dict  # Pass dictionaries instead of SQLAlchemy objects
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
    camera = db.query(Camera).filter(
        Camera.camera_id == camera_id,
        Camera.user_id == user.id
    ).first()
    
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    
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
    camera = db.query(Camera).filter(
        Camera.camera_id == camera_id,
        Camera.user_id == user.id
    ).first()
    
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    
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
    camera = db.query(Camera).filter(
        Camera.camera_id == camera_id,
        Camera.user_id == user.id
    ).first()
    
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    db.delete(camera)
    db.commit()
    
    return RedirectResponse(url="/dashboard", status_code=302)

@app.post("/upload")
async def upload_image(
    camera_id: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    try:
        # Find or create camera
        camera = db.query(Camera).filter(Camera.camera_id == camera_id).first()
        
        if not camera:
            # Auto-create camera if it doesn't exist
            camera = Camera(
                camera_id=camera_id,
                name=f"Camera {camera_id}",
                location="Auto-detected",
                user_id=1  # Assign to admin
            )
            db.add(camera)
        
        # Update last_seen timestamp
        camera.last_seen = datetime.utcnow()
        db.commit()
        
        # Read file content
        file_content = await file.read()
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{camera_id}/{timestamp}.jpg"
        
        # Upload to S3
        success = upload_to_s3(file_content, filename)
        
        if success:
            # Delete old images (keep only latest IMAGES_PER_CAMERA)
            delete_old_images(camera_id, IMAGES_PER_CAMERA)
            
            print(f"✓ Uploaded to S3: {filename}")
            return JSONResponse({"status": "success", "message": "Image uploaded"})
        else:
            print(f"✗ S3 upload failed: {filename}")
            return JSONResponse(
                {"status": "error", "message": "S3 upload failed"},
                status_code=500
            )
            
    except Exception as e:
        print(f"✗ Upload error: {str(e)}")
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
    camera = db.query(Camera).filter(
        Camera.camera_id == camera_id,
        Camera.user_id == user.id
    ).first()
    
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    # Get images from S3
    images = list_camera_images(camera_id, IMAGES_PER_CAMERA)
    
    # Generate presigned URLs
    image_data = []
    for img in images:
        url = get_presigned_url(img['key'])
        if url:
            image_data.append({
                'url': url,
                'timestamp': img['timestamp'].isoformat(),  # ✅ Convert to string!
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
    camera = db.query(Camera).filter(
        Camera.camera_id == camera_id,
        Camera.user_id == user.id
    ).first()
    
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    
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
    
    return JSONResponse({
        "status": status,
        "last_seen": last_seen_text,
        "last_seen_datetime": camera.last_seen.isoformat() if camera.last_seen else None
    })

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
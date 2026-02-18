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
from location_helper import location_detector

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
        # Determine which location to show
        if camera.use_manual_location and camera.manual_location:
            display_location = camera.manual_location
            location_source = "manual"
        else:
            display_location = camera.auto_location or "Detecting..."
            location_source = "auto"
        
        camera_dict = {
            'id': camera.id,
            'camera_id': camera.camera_id,
            'name': camera.name,
            'display_location': display_location,
            'location_source': location_source,
            'auto_location': camera.auto_location,
            'manual_location': camera.manual_location,
            'use_manual_location': camera.use_manual_location,
            'auto_city': camera.auto_city,
            'auto_region': camera.auto_region,
            'auto_country': camera.auto_country,
            'manual_city': camera.manual_city,
            'manual_region': camera.manual_region,
            'manual_country': camera.manual_country,
            'auto_latitude': camera.auto_latitude,
            'auto_longitude': camera.auto_longitude,
            'manual_latitude': camera.manual_latitude,
            'manual_longitude': camera.manual_longitude,
            'is_active': camera.is_active,
            'last_seen': camera.last_seen.isoformat() if camera.last_seen else None,
            'created_at': camera.created_at.isoformat() if camera.created_at else None,
            'role': 'owner',
            'can_edit': True
        }
        all_cameras.append(camera_dict)
    
    # Add shared cameras
    for camera in shared_cameras:
        share_info = db.query(CameraShare).filter(
            CameraShare.camera_id == camera.id,
            CameraShare.shared_with_user_id == user.id
        ).first()
        
        # Determine which location to show
        if camera.use_manual_location and camera.manual_location:
            display_location = camera.manual_location
            location_source = "manual"
        else:
            display_location = camera.auto_location or "Detecting..."
            location_source = "auto"
        
        camera_dict = {
            'id': camera.id,
            'camera_id': camera.camera_id,
            'name': camera.name,
            'display_location': display_location,
            'location_source': location_source,
            'auto_location': camera.auto_location,
            'manual_location': camera.manual_location,
            'use_manual_location': camera.use_manual_location,
            'auto_city': camera.auto_city,
            'auto_region': camera.auto_region,
            'auto_country': camera.auto_country,
            'manual_city': camera.manual_city,
            'manual_region': camera.manual_region,
            'manual_country': camera.manual_country,
            'auto_latitude': camera.auto_latitude,
            'auto_longitude': camera.auto_longitude,
            'manual_latitude': camera.manual_latitude,
            'manual_longitude': camera.manual_longitude,
            'is_active': camera.is_active,
            'last_seen': camera.last_seen.isoformat() if camera.last_seen else None,
            'created_at': camera.created_at.isoformat() if camera.created_at else None,
            'role': 'viewer',
            'can_edit': share_info.can_edit if share_info else False
        }
        all_cameras.append(camera_dict)
    
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
    
    # Check if camera_id already exists
    existing_camera = db.query(Camera).filter(Camera.camera_id == camera_id).first()
    
    if existing_camera:
        # Check if this camera is already shared with the user
        is_shared = db.query(CameraShare).filter(
            CameraShare.camera_id == existing_camera.id,
            CameraShare.shared_with_user_id == user.id
        ).first() is not None
        
        if is_shared:
            return RedirectResponse(url="/dashboard", status_code=302)
        else:
            return templates.TemplateResponse("edit_camera.html", {
                "request": request,
                "session": request.session,
                "user": user,
                "camera": None,
                "action": "Add",
                "error": f"Camera '{camera_id}' is registered by another user. Please ask them to share it with you."
            })
    
    # Auto-detect location
    client_ip = request.client.host if request else None
    location_data = location_detector.detect_location_from_ip(client_ip)
    
    new_camera = Camera(
        camera_id=camera_id,
        name=name,
        auto_location=location_data.get("detected_location"),
        auto_city=location_data.get("city"),
        auto_region=location_data.get("region"),
        auto_country=location_data.get("country"),
        auto_country_code=location_data.get("country_code"),
        auto_latitude=location_data.get("latitude"),
        auto_longitude=location_data.get("longitude"),
        ip_address=client_ip,
        first_seen_ip=client_ip,
        user_id=user.id,
        use_manual_location=False
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
    
    # Update basic info
    camera.name = form.get("name")
    
    # Update manual location if provided
    manual_location = form.get("manual_location")
    manual_city = form.get("manual_city")
    manual_region = form.get("manual_region")
    manual_country = form.get("manual_country")
    manual_latitude = form.get("manual_latitude")
    manual_longitude = form.get("manual_longitude")
    
    # Only update if at least one field is provided
    if manual_location or manual_city or manual_region or manual_country or manual_latitude or manual_longitude:
        camera.manual_location = manual_location if manual_location else None
        camera.manual_city = manual_city if manual_city else None
        camera.manual_region = manual_region if manual_region else None
        camera.manual_country = manual_country if manual_country else None
        
        try:
            if manual_latitude:
                camera.manual_latitude = float(manual_latitude)
            if manual_longitude:
                camera.manual_longitude = float(manual_longitude)
        except ValueError:
            pass
    
    # Update location source preference
    use_manual = form.get("use_manual_location") == "on"
    camera.use_manual_location = use_manual
    
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

# ========== LOCATION DETECTION ROUTES ==========

@app.post("/camera/{camera_id}/detect-location")
async def detect_camera_location(
    camera_id: str,
    request: Request,
    user: User = Depends(require_login),
    db: Session = Depends(get_db)
):
    """Manually trigger location detection for a camera"""
    camera = db.query(Camera).filter(
        Camera.camera_id == camera_id,
        Camera.user_id == user.id
    ).first()
    
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    client_ip = camera.ip_address or request.client.host
    location_data = location_detector.detect_location_from_ip(client_ip)
    
    if location_data.get("success", False):
        camera.auto_location = location_data.get("detected_location")
        camera.auto_city = location_data.get("city")
        camera.auto_region = location_data.get("region")
        camera.auto_country = location_data.get("country")
        camera.auto_country_code = location_data.get("country_code")
        camera.auto_latitude = location_data.get("latitude")
        camera.auto_longitude = location_data.get("longitude")
        
        db.commit()
        
        return {
            "success": True,
            "detected_location": camera.auto_location,
            "city": camera.auto_city,
            "region": camera.auto_region,
            "country": camera.auto_country
        }
    
    return {"success": False, "error": location_data.get("error", "Unknown error")}

@app.get("/camera/{camera_id}/reset-location")
async def reset_camera_location(
    camera_id: str,
    user: User = Depends(require_login),
    db: Session = Depends(get_db)
):
    """Reset to auto-detected location (clear manual override)"""
    camera = db.query(Camera).filter(
        Camera.camera_id == camera_id,
        Camera.user_id == user.id
    ).first()
    
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    camera.use_manual_location = False
    camera.manual_location = None
    camera.manual_city = None
    camera.manual_region = None
    camera.manual_country = None
    camera.manual_latitude = None
    camera.manual_longitude = None
    
    db.commit()
    
    return RedirectResponse(url=f"/cameras/{camera_id}/edit", status_code=302)

# ========== CAMERA SHARING ROUTES ==========

@app.get("/cameras/{camera_id}/share", response_class=HTMLResponse)
async def share_camera_page(
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
        raise HTTPException(status_code=404, detail="Camera not found or not yours")
    
    shares = db.query(CameraShare).filter(
        CameraShare.camera_id == camera.id
    ).all()
    
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
    form = await request.form()
    shared_user_id = form.get("user_id")
    can_edit = form.get("can_edit") == "on"
    
    camera = db.query(Camera).filter(
        Camera.camera_id == camera_id,
        Camera.user_id == user.id
    ).first()
    
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found or not yours")
    
    existing = db.query(CameraShare).filter(
        CameraShare.camera_id == camera.id,
        CameraShare.shared_with_user_id == shared_user_id
    ).first()
    
    if existing:
        existing.can_edit = can_edit
    else:
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
    camera = db.query(Camera).filter(
        Camera.camera_id == camera_id,
        Camera.user_id == user.id
    ).first()
    
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found or not yours")
    
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
    request: Request = None,
    db: Session = Depends(get_db)
):
    print(f"\n📸 ===== UPLOAD RECEIVED =====")
    print(f"📸 Camera ID: {camera_id}")
    print(f"📸 File name: {file.filename}")
    
    client_ip = request.client.host if request else None
    print(f"📸 Client IP: {client_ip}")
    
    try:
        camera = db.query(Camera).filter(Camera.camera_id == camera_id).first()
        
        if not camera:
            print(f"📸 Camera {camera_id} not found, creating new with auto-detection...")
            
            location_data = location_detector.detect_location_from_ip(client_ip)
            
            camera = Camera(
                camera_id=camera_id,
                name=f"Camera {camera_id}",
                auto_location=location_data.get("detected_location"),
                auto_city=location_data.get("city"),
                auto_region=location_data.get("region"),
                auto_country=location_data.get("country"),
                auto_country_code=location_data.get("country_code"),
                auto_latitude=location_data.get("latitude"),
                auto_longitude=location_data.get("longitude"),
                ip_address=client_ip,
                first_seen_ip=client_ip,
                user_id=1,
                use_manual_location=False
            )
            db.add(camera)
            db.flush()
            print(f"📸 Created new camera with auto-location: {location_data.get('detected_location')}")
        else:
            if camera.ip_address != client_ip:
                print(f"📸 IP changed from {camera.ip_address} to {client_ip}")
                camera.ip_address = client_ip
        
        camera.last_seen = datetime.utcnow()
        db.commit()
        
        file_content = await file.read()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{camera_id}/{timestamp}.jpg"
        
        success = upload_to_s3(file_content, filename)
        
        if success:
            print(f"✅ Upload successful to S3: {filename}")
            return JSONResponse({
                "status": "success", 
                "message": "Image uploaded",
                "camera": {
                    "id": camera.camera_id,
                    "name": camera.name,
                    "auto_location": camera.auto_location,
                    "manual_location": camera.manual_location,
                    "use_manual": camera.use_manual_location
                }
            })
        else:
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
    camera = db.query(Camera).filter(Camera.camera_id == camera_id).first()
    
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    is_owner = camera.user_id == user.id
    is_shared = db.query(CameraShare).filter(
        CameraShare.camera_id == camera.id,
        CameraShare.shared_with_user_id == user.id
    ).first() is not None
    
    if not (is_owner or is_shared):
        raise HTTPException(status_code=403, detail="Access denied")
    
    images = list_camera_images(camera_id, 6)
    
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
    camera = db.query(Camera).filter(Camera.camera_id == camera_id).first()
    
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    
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
    
    can_edit = is_owner or (is_shared and db.query(CameraShare).filter(
        CameraShare.camera_id == camera.id,
        CameraShare.shared_with_user_id == user.id,
        CameraShare.can_edit == True
    ).first() is not None)
    
    # Determine which location to return
    if camera.use_manual_location and camera.manual_location:
        display_location = camera.manual_location
        location_source = "manual"
    else:
        display_location = camera.auto_location
        location_source = "auto"
    
    return JSONResponse({
        "status": status,
        "last_seen": last_seen_text,
        "last_seen_datetime": camera.last_seen.isoformat() if camera.last_seen else None,
        "is_owner": is_owner,
        "can_edit": can_edit,
        "display_location": display_location,
        "location_source": location_source
    })

@app.get("/debug")
async def debug_session(request: Request):
    return {
        "session": dict(request.session),
        "cookies": request.cookies
    }

@app.get("/debug/camera/{camera_id}")
async def debug_camera(camera_id: str, db: Session = Depends(get_db)):
    camera = db.query(Camera).filter(Camera.camera_id == camera_id).first()
    if not camera:
        return {"error": "Camera not found"}
    
    time_diff = (datetime.utcnow() - camera.last_seen).total_seconds() if camera.last_seen else None
    timeout_seconds = CAMERA_TIMEOUT_MINUTES * 60
    
    return {
        "camera_id": camera.camera_id,
        "name": camera.name,
        "auto_location": camera.auto_location,
        "manual_location": camera.manual_location,
        "use_manual_location": camera.use_manual_location,
        "auto_city": camera.auto_city,
        "auto_region": camera.auto_region,
        "auto_country": camera.auto_country,
        "manual_city": camera.manual_city,
        "manual_region": camera.manual_region,
        "manual_country": camera.manual_country,
        "auto_latitude": camera.auto_latitude,
        "auto_longitude": camera.auto_longitude,
        "manual_latitude": camera.manual_latitude,
        "manual_longitude": camera.manual_longitude,
        "ip_address": camera.ip_address,
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

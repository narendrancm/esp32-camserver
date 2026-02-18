from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, ForeignKey, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime

# Database setup
DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Models
class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    cameras = relationship("Camera", back_populates="owner", cascade="all, delete-orphan")
    shared_cameras = relationship("CameraShare", back_populates="shared_user", cascade="all, delete-orphan")

class Camera(Base):
    __tablename__ = "cameras"
    
    id = Column(Integer, primary_key=True, index=True)
    camera_id = Column(String, unique=True, index=True, nullable=False)
    
    # User-defined name
    name = Column(String, nullable=False, default="New Camera")
    
    # Auto-detected location (from IP)
    auto_location = Column(String)  # Auto-detected full location
    auto_city = Column(String)
    auto_region = Column(String)
    auto_country = Column(String)
    auto_country_code = Column(String)
    auto_latitude = Column(Float, nullable=True)
    auto_longitude = Column(Float, nullable=True)
    
    # Manually edited location (user can override)
    manual_location = Column(String)  # Manual location if user overrides
    manual_city = Column(String)
    manual_region = Column(String)
    manual_country = Column(String)
    manual_latitude = Column(Float, nullable=True)
    manual_longitude = Column(Float, nullable=True)
    
    # Which location to display (auto or manual)
    use_manual_location = Column(Boolean, default=False)
    
    # Technical info
    ip_address = Column(String)
    first_seen_ip = Column(String)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    is_active = Column(Boolean, default=True)
    last_seen = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    owner = relationship("User", back_populates="cameras")
    shares = relationship("CameraShare", back_populates="camera", cascade="all, delete-orphan")

class CameraShare(Base):
    __tablename__ = "camera_shares"
    
    id = Column(Integer, primary_key=True, index=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"))
    shared_with_user_id = Column(Integer, ForeignKey("users.id"))
    can_edit = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    camera = relationship("Camera", back_populates="shares")
    shared_user = relationship("User", back_populates="shared_cameras")

# Create tables
Base.metadata.create_all(bind=engine)

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

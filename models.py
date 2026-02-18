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
    cameras = relationship("Camera", back_populates="owner")
    shared_cameras = relationship("CameraShare", back_populates="shared_user")

class Camera(Base):
    __tablename__ = "cameras"
    
    id = Column(Integer, primary_key=True, index=True)
    camera_id = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    location = Column(String)  # Auto-detected or manual
    city = Column(String)      # Auto-detected city
    region = Column(String)     # Auto-detected region/state
    country = Column(String)   # Auto-detected country
    latitude = Column(Float, nullable=True)   # GPS coordinates
    longitude = Column(Float, nullable=True)  # GPS coordinates
    ip_address = Column(String) # Last known IP
    first_seen_ip = Column(String)  # IP on first connection
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    is_active = Column(Boolean, default=True)
    last_seen = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    owner = relationship("User", back_populates="cameras")
    shares = relationship("CameraShare", back_populates="camera")

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

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

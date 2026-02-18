import requests
import socket
from typing import Dict, Optional

class LocationDetector:
    """Auto-detect camera location based on IP and network info"""
    
    def __init__(self):
        self.ip_api_url = "http://ip-api.com/json/"  # Free IP geolocation API
        self.fallback_url = "https://ipapi.co/json/"  # Backup API
    
    def get_public_ip(self) -> Optional[str]:
        """Get the public IP address"""
        try:
            response = requests.get("https://api.ipify.org?format=json", timeout=5)
            if response.status_code == 200:
                return response.json().get("ip")
        except Exception as e:
            print(f"IP detection error: {e}")
        return None
    
    def detect_location_from_ip(self, ip_address: str = None) -> Dict:
        """Detect location from IP address"""
        if not ip_address or ip_address.startswith("127.") or ip_address.startswith("192.168."):
            # Private IP, try to get public IP
            ip_address = self.get_public_ip()
            if not ip_address:
                return {
                    "ip": ip_address or "unknown",
                    "city": "Local Network",
                    "country": "Private",
                    "latitude": None,
                    "longitude": None,
                    "error": "Private IP - using network location"
                }
        
        try:
            # Try primary API
            response = requests.get(f"{self.ip_api_url}{ip_address}", timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    return {
                        "ip": ip_address,
                        "city": data.get("city", "Unknown"),
                        "region": data.get("regionName", "Unknown"),
                        "country": data.get("country", "Unknown"),
                        "country_code": data.get("countryCode", ""),
                        "latitude": data.get("lat"),
                        "longitude": data.get("lon"),
                        "isp": data.get("isp", "Unknown"),
                        "source": "ip-api.com",
                        "success": True
                    }
        except Exception as e:
            print(f"Primary API error: {e}")
        
        try:
            # Try fallback API
            response = requests.get(self.fallback_url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                return {
                    "ip": data.get("ip", ip_address),
                    "city": data.get("city", "Unknown"),
                    "region": data.get("region", "Unknown"),
                    "country": data.get("country_name", "Unknown"),
                    "country_code": data.get("country_code", ""),
                    "latitude": data.get("latitude"),
                    "longitude": data.get("longitude"),
                    "source": "ipapi.co",
                    "success": True
                }
        except Exception as e:
            print(f"Fallback API error: {e}")
        
        return {
            "ip": ip_address,
            "city": "Unknown",
            "country": "Unknown",
            "latitude": None,
            "longitude": None,
            "success": False,
            "error": "Could not detect location"
        }
    
    def generate_location_name(self, location_data: Dict) -> str:
        """Generate a human-readable location name"""
        if not location_data.get("success", False):
            return "Unknown Location"
        
        parts = []
        if location_data.get("city") and location_data["city"] != "Unknown":
            parts.append(location_data["city"])
        if location_data.get("region") and location_data["region"] != "Unknown":
            parts.append(location_data["region"])
        if location_data.get("country") and location_data["country"] != "Unknown":
            parts.append(location_data["country"])
        
        if parts:
            return ", ".join(parts)
        return "Unknown Location"
    
    def generate_camera_name(self, location_data: Dict, camera_id: str) -> str:
        """Generate a friendly camera name based on location"""
        if not location_data.get("success", False):
            return f"Camera {camera_id}"
        
        if location_data.get("city") and location_data["city"] != "Unknown":
            return f"{location_data['city']} Camera"
        elif location_data.get("country") and location_data["country"] != "Unknown":
            return f"{location_data['country']} Camera"
        else:
            return f"Camera {camera_id}"

# Global instance
location_detector = LocationDetector()

import requests
import socket
from typing import Dict, Optional

class LocationDetector:
    """Auto-detect camera location based on IP and network info"""
    
    def __init__(self):
        self.ip_api_url = "http://ip-api.com/json/"
        self.fallback_url = "https://ipapi.co/json/"
    
    def get_public_ip(self) -> Optional[str]:
        """Get the public IP address of the server"""
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
            ip_address = self.get_public_ip()
            if not ip_address:
                return {
                    "ip": ip_address or "unknown",
                    "city": "Local Network",
                    "region": "Local",
                    "country": "Network",
                    "country_code": "N/A",
                    "latitude": None,
                    "longitude": None,
                    "success": False,
                    "error": "Private IP - using network location",
                    "detected_location": "Local Network"
                }
        
        # Try primary API
        try:
            response = requests.get(f"{self.ip_api_url}{ip_address}", timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    location_parts = []
                    if data.get("city"):
                        location_parts.append(data["city"])
                    if data.get("regionName"):
                        location_parts.append(data["regionName"])
                    if data.get("country"):
                        location_parts.append(data["country"])
                    
                    detected_location = ", ".join(location_parts) if location_parts else "Unknown Location"
                    
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
                        "success": True,
                        "detected_location": detected_location
                    }
        except Exception as e:
            print(f"Primary API error: {e}")
        
        # Try fallback API
        try:
            response = requests.get(self.fallback_url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                
                location_parts = []
                if data.get("city"):
                    location_parts.append(data["city"])
                if data.get("region"):
                    location_parts.append(data["region"])
                if data.get("country_name"):
                    location_parts.append(data["country_name"])
                
                detected_location = ", ".join(location_parts) if location_parts else "Unknown Location"
                
                return {
                    "ip": data.get("ip", ip_address),
                    "city": data.get("city", "Unknown"),
                    "region": data.get("region", "Unknown"),
                    "country": data.get("country_name", "Unknown"),
                    "country_code": data.get("country_code", ""),
                    "latitude": data.get("latitude"),
                    "longitude": data.get("longitude"),
                    "source": "ipapi.co",
                    "success": True,
                    "detected_location": detected_location
                }
        except Exception as e:
            print(f"Fallback API error: {e}")
        
        return {
            "ip": ip_address,
            "city": "Unknown",
            "region": "Unknown",
            "country": "Unknown",
            "country_code": "",
            "latitude": None,
            "longitude": None,
            "success": False,
            "error": "Could not detect location",
            "detected_location": "Location Unknown"
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

# Global instance
location_detector = LocationDetector()

import requests
import os
import logging
from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Fetch API key from environment variables
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
if not OPENWEATHER_API_KEY:
    raise ValueError("Missing OPENWEATHER_API_KEY in .env file")

app = FastAPI()

class LocationData(BaseModel):
    lat: float
    lon: float

def is_daytime(sunrise, sunset):
    """Determine if it's currently daytime based on sunrise and sunset times."""
    current_time = datetime.now().timestamp()
    return sunrise <= current_time <= sunset

def get_weather_data(lat, lon):
    """Fetch real-time weather data from OpenWeather API."""
    url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}"
    response = requests.get(url).json()

    logger.info(f"Fetching weather data for {lat}, {lon}")

    if response.get("cod") != 200:
        logger.warning(f"⚠️ Error fetching weather data: {response.get('message')}")
        return None

    rain = response.get("rain", {}).get("1h", 0)
    snow = response.get("snow", {}).get("1h", 0)

    # Get sunrise and sunset times
    sunrise = response.get("sys", {}).get("sunrise", 0)
    sunset = response.get("sys", {}).get("sunset", 0)
    
    # Get location and country
    location = response.get("name", "Unknown")
    country = response.get("sys", {}).get("country", "")
    
    # Get weather description and main condition
    weather_description = response.get("weather", [{}])[0].get("description", "Clear sky")
    weather_main = response.get("weather", [{}])[0].get("main", "Clear")

    return {
        "temp": response.get("main", {}).get("temp", 293.15),
        "feels_like": response.get("main", {}).get("feels_like", 293.15),
        "wind_speed": response.get("wind", {}).get("speed", 0),
        "humidity": response.get("main", {}).get("humidity", 50),
        "precipitation": rain + snow,
        "clouds": response.get("clouds", {}).get("all", 20),
        "visibility": response.get("visibility", 10000),
        "weather_main": weather_main,
        "description": weather_description,
        "location": location,
        "country": country,
        "is_day": is_daytime(sunrise, sunset)
    }

def get_air_quality(lat, lon):
    """Fetch air quality data from OpenWeather API."""
    url = f"http://api.openweathermap.org/data/2.5/air_pollution?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}"
    response = requests.get(url).json()

    logger.info(f"Fetching air quality data for {lat}, {lon}")

    if "list" not in response or not response["list"]:
        logger.warning("⚠️ Air quality data missing. Assuming good air quality.")
        return {"so2": 0, "no2": 0, "pm10": 0, "pm2_5": 0, "o3": 0, "co": 0}

    pollutants = response["list"][0]["components"]

    return {key: pollutants.get(key, 0) for key in ["so2", "no2", "pm10", "pm2_5", "o3", "co"]}

def classify_air_quality(pollutants):
    """Classify air quality using provided matrix."""
    air_quality_matrix = {
        "Good": {"so2": 20, "no2": 40, "pm10": 20, "pm2_5": 10, "o3": 60, "co": 4400},
        "Fair": {"so2": 80, "no2": 70, "pm10": 50, "pm2_5": 25, "o3": 100, "co": 9400},
        "Moderate": {"so2": 250, "no2": 150, "pm10": 100, "pm2_5": 50, "o3": 140, "co": 12400},
        "Poor": {"so2": 350, "no2": 200, "pm10": 200, "pm2_5": 75, "o3": 180, "co": 15400},
        "Very Poor": {"so2": float("inf"), "no2": float("inf"), "pm10": float("inf"), "pm2_5": float("inf"), "o3": float("inf"), "co": float("inf")}
    }

    for quality, limits in air_quality_matrix.items():
        if any(pollutants[pollutant] >= limit for pollutant, limit in limits.items()):
            return quality

    return "Good"

def classify_weather(weather_data, air_quality_category):
    """Classify pet-friendly weather conditions, considering air quality."""
    temp_c = weather_data["temp"] - 273.15
    feels_like_c = weather_data["feels_like"] - 273.15
    wind_kmh = weather_data["wind_speed"] * 3.6  # Convert m/s to km/h

    if air_quality_category in ["Poor", "Very Poor"]:
        return {
            "recommendation": f"Take Precaution (Air Quality: {air_quality_category})",
            "triggered_by": "Air Pollution",
            "value": air_quality_category
        }

    if temp_c > 35 or temp_c < -5 or feels_like_c > 35 or feels_like_c < -5:
        return {
            "recommendation": "Do Not Go Out (Extreme Temperature)",
            "triggered_by": "Temperature",
            "value": f"{temp_c:.2f}°C / Feels Like: {feels_like_c:.2f}°C"
        }

    if wind_kmh > 40:
        return {
            "recommendation": "Do Not Go Out (High Wind Speed)",
            "triggered_by": "Wind Speed",
            "value": f"{wind_kmh:.2f} km/h"
        }

    if weather_data["precipitation"] > 5:
        return {
            "recommendation": "Do Not Go Out (Heavy Rain/Snow)",
            "triggered_by": "Precipitation",
            "value": f"{weather_data['precipitation']} mm"
        }

    if temp_c < 0 or temp_c > 30 or feels_like_c < 0 or feels_like_c > 30:
        return {
            "recommendation": "Take Precaution (Temperature Warning)",
            "triggered_by": "Temperature",
            "value": f"{temp_c:.2f}°C / Feels Like: {feels_like_c:.2f}°C"
        }

    return {
        "recommendation": "No Worries (Good Weather for a Walk)",
        "triggered_by": "General Weather Conditions",
        "value": "All parameters within safe range"
    }

@app.post("/check-weather")
def check_weather(location: LocationData):
    """Fetch weather & air quality data dynamically and return classification."""
    weather_data = get_weather_data(location.lat, location.lon)
    pollutants = get_air_quality(location.lat, location.lon)

    if not weather_data:
        return {"error": "Failed to fetch weather data."}

    air_quality_category = classify_air_quality(pollutants)
    classification = classify_weather(weather_data, air_quality_category)
    
    # Convert Kelvin to Celsius for temperature values
    temp_c = weather_data["temp"] - 273.15
    feels_like_c = weather_data["feels_like"] - 273.15
    
    # Add additional fields needed by the WeatherCard component
    classification.update({
        "location": weather_data["location"],
        "country": weather_data["country"],
        "temp": round(temp_c, 1),
        "feels_like": round(feels_like_c, 1),
        "description": weather_data["description"],
        "main": weather_data["weather_main"],
        "humidity": weather_data["humidity"],
        "wind_speed": round(weather_data["wind_speed"] * 3.6, 1),  # Convert m/s to km/h
        "air_quality": air_quality_category,
        "is_day": weather_data["is_day"]
    })

    return classification
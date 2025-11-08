"""Data transformation functions for ETL pipeline"""

import re
from typing import Optional, Tuple
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
from tenacity import retry, stop_after_attempt, wait_exponential
from loguru import logger

from src.config import GEOCODING_CONFIG


# Initialize geocoder
geolocator = Nominatim(
    user_agent=GEOCODING_CONFIG["user_agent"],
    timeout=GEOCODING_CONFIG["timeout"]
)


def parse_economic_loss(loss_string: Optional[str]) -> Optional[int]:
    """
    Parse economic loss strings to numeric values in USD.

    Examples:
        "10.5K" -> 10500
        "5.2M" -> 5200000
        "1.5B" -> 1500000000
        "1000" -> 1000

    Args:
        loss_string: String representation of economic loss (e.g., "10.5M")

    Returns:
        Numeric value in USD, or None if parsing fails
    """
    if not loss_string or loss_string in ["", "None", "nan"]:
        return None

    try:
        loss_string = str(loss_string).strip().upper()

        # Define multipliers
        multipliers = {
            'K': 1_000,
            'M': 1_000_000,
            'B': 1_000_000_000,
        }

        # Check if last character is a suffix
        if loss_string[-1] in multipliers:
            suffix = loss_string[-1]
            numeric_part = loss_string[:-1].strip()
            multiplier = multipliers[suffix]
        else:
            # No suffix, direct numeric value
            numeric_part = loss_string
            multiplier = 1

        # Convert to float and apply multiplier
        value = float(numeric_part) * multiplier
        return int(value)

    except (ValueError, IndexError) as e:
        logger.debug(f"Failed to parse economic loss '{loss_string}': {e}")
        return None


@retry(
    stop=stop_after_attempt(GEOCODING_CONFIG["max_retries"]),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=False
)
def geocode_location(location_text: str) -> Optional[Tuple[float, float]]:
    """
    Convert textual location to latitude/longitude coordinates using Nominatim.

    Args:
        location_text: Location string (e.g., "Gurdaspur, Punjab, India")

    Returns:
        Tuple of (latitude, longitude) or None if geocoding fails
    """
    if not location_text or location_text.strip() == "":
        return None

    try:
        location = geolocator.geocode(location_text)

        if location:
            logger.debug(f"Geocoded '{location_text}' -> ({location.latitude}, {location.longitude})")
            return (location.latitude, location.longitude)
        else:
            logger.debug(f"No geocoding result for '{location_text}'")
            return None

    except (GeocoderTimedOut, GeocoderUnavailable) as e:
        logger.warning(f"Geocoding failed for '{location_text}': {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected geocoding error for '{location_text}': {e}")
        return None


def extract_country_iso3(location_text: str) -> Optional[str]:
    """
    Extract ISO3 country code from location text using geocoding.

    Args:
        location_text: Location string

    Returns:
        3-letter ISO country code or None
    """
    if not location_text:
        return None

    try:
        location = geolocator.geocode(location_text, language='en', addressdetails=True)

        if location and location.raw:
            address = location.raw.get('address', {})
            country_code = address.get('country_code', '').upper()

            # Convert ISO2 to ISO3 (simple mapping for common countries)
            iso2_to_iso3 = {
                'US': 'USA', 'IN': 'IND', 'CN': 'CHN', 'JP': 'JPN',
                'GB': 'GBR', 'FR': 'FRA', 'DE': 'DEU', 'IT': 'ITA',
                'BR': 'BRA', 'MX': 'MEX', 'CA': 'CAN', 'AU': 'AUS',
                'ID': 'IDN', 'PK': 'PAK', 'BD': 'BGD', 'NP': 'NPL',
                # Add more mappings as needed
            }

            iso3 = iso2_to_iso3.get(country_code)
            if iso3:
                return iso3

            # If not in mapping, try using pycountry if available
            try:
                import pycountry
                country = pycountry.countries.get(alpha_2=country_code)
                if country:
                    return country.alpha_3
            except ImportError:
                pass

            return None

    except Exception as e:
        logger.debug(f"Failed to extract country code from '{location_text}': {e}")
        return None


def classify_disaster_type(disaster_text: str) -> Tuple[str, str, Optional[str]]:
    """
    Classify disaster into group, type, and subtype based on text.

    Args:
        disaster_text: Disaster description

    Returns:
        Tuple of (disaster_group, disaster_type, disaster_subtype)
    """
    if not disaster_text:
        return ("Unknown", "Unknown", None)

    disaster_text_lower = disaster_text.lower()

    # Classification rules
    if any(term in disaster_text_lower for term in ["earthquake", "seismic", "tremor"]):
        return ("Geophysical", "Earthquake", "Ground Shaking")

    elif any(term in disaster_text_lower for term in ["tsunami"]):
        return ("Geophysical", "Earthquake", "Tsunami")

    elif any(term in disaster_text_lower for term in ["volcano", "volcanic", "eruption"]):
        return ("Geophysical", "Volcano", "Volcanic Activity")

    elif any(term in disaster_text_lower for term in ["landslide", "mudslide"]):
        return ("Geophysical", "Mass Movement", "Landslide")

    elif any(term in disaster_text_lower for term in ["cyclone", "hurricane", "typhoon"]):
        return ("Meteorological", "Storm", "Tropical Cyclone")

    elif any(term in disaster_text_lower for term in ["tornado", "twister"]):
        return ("Meteorological", "Storm", "Tornado")

    elif any(term in disaster_text_lower for term in ["storm", "thunderstorm"]):
        return ("Meteorological", "Storm", "Severe Storm")

    elif any(term in disaster_text_lower for term in ["flood", "flooding"]):
        if "flash" in disaster_text_lower:
            return ("Hydrological", "Flood", "Flash Flood")
        elif "coastal" in disaster_text_lower:
            return ("Hydrological", "Flood", "Coastal Flood")
        else:
            return ("Hydrological", "Flood", "Riverine Flood")

    elif any(term in disaster_text_lower for term in ["drought", "dry"]):
        return ("Climatological", "Drought", None)

    elif any(term in disaster_text_lower for term in ["wildfire", "fire", "forest fire"]):
        return ("Climatological", "Wildfire", None)

    elif any(term in disaster_text_lower for term in ["heat wave", "extreme heat"]):
        return ("Meteorological", "Extreme Temperature", "Heat Wave")

    elif any(term in disaster_text_lower for term in ["cold wave", "extreme cold", "freeze"]):
        return ("Meteorological", "Extreme Temperature", "Cold Wave")

    # Default
    return ("Unknown", disaster_text, None)


def normalize_magnitude_unit(magnitude_value: Optional[float], disaster_type: str) -> Tuple[Optional[float], Optional[str]]:
    """
    Normalize magnitude units based on disaster type.

    Args:
        magnitude_value: Raw magnitude value
        disaster_type: Type of disaster

    Returns:
        Tuple of (magnitude_value, magnitude_unit)
    """
    if magnitude_value is None:
        return (None, None)

    disaster_type_lower = disaster_type.lower()

    if "earthquake" in disaster_type_lower:
        return (magnitude_value, "Richter")
    elif "storm" in disaster_type_lower or "wind" in disaster_type_lower:
        return (magnitude_value, "km/h")
    elif "flood" in disaster_type_lower:
        return (magnitude_value, "m")  # Water level in meters
    else:
        return (magnitude_value, "unknown")

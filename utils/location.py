import random

# ── Location pools ────────────────────────────────────────────────
# Each location carries its coordinates so the risk scorer can
# calculate real distances with Haversine. No more string comparisons.

HOME_LOCATION = {
    "name": "Bangalore, India",
    "lat": 12.97,
    "lng": 77.59
}

NEARBY_LOCATIONS = [
    {"name": "Chennai, India",    "lat": 13.08, "lng": 80.27},
    {"name": "Hyderabad, India",  "lat": 17.38, "lng": 78.47},
    {"name": "Pune, India",       "lat": 18.52, "lng": 73.85},
]

DISTANT_LOCATIONS = [
    {"name": "Mumbai, India",     "lat": 19.07, "lng": 72.87},
    {"name": "Delhi, India",      "lat": 28.61, "lng": 77.21},
    {"name": "Kolkata, India",    "lat": 22.57, "lng": 88.36},
    {"name": "Ahmedabad, India",  "lat": 23.02, "lng": 72.57},
]

INTERNATIONAL_LOCATIONS = [
    {"name": "New York, USA",   "lat": 40.71, "lng": -74.00},
    {"name": "Paris, France",   "lat": 48.85, "lng":   2.35},
    {"name": "London, UK",      "lat": 51.51, "lng":  -0.13},
    {"name": "Tokyo, Japan",    "lat": 35.68, "lng": 139.69},
    {"name": "Tehran, Iran",    "lat": 35.69, "lng":  51.39},
]

# Flat lookup for risk scorer (name → coords)
LOCATION_COORDS: dict[str, tuple[float, float]] = {
    loc["name"]: (loc["lat"], loc["lng"])
    for loc in (
        [HOME_LOCATION]
        + NEARBY_LOCATIONS
        + DISTANT_LOCATIONS
        + INTERNATIONAL_LOCATIONS
    )
}


def get_location(username, inject_fraud=False):
    """
    Returns a location name string (compatible with your existing DB schema).

    Tiered probability — why this matters:
      Pure random across all cities = unusual location fires 40% of the time.
      With tiers = unusual location fires ~15% of the time.
      That makes the signal meaningful when it does appear.

    Tiers:
      70% → home city (Bangalore)
      15% → nearby city  (< 500km, same region)
       8% → distant Indian city
       7% → international city

    inject_fraud=True → always picks international to stack the signal.
    """
    if inject_fraud:
        return random.choice(INTERNATIONAL_LOCATIONS)["name"]

    r = random.random()

    if r < 0.70:
        return HOME_LOCATION["name"]
    elif r < 0.85:
        return random.choice(NEARBY_LOCATIONS)["name"]
    elif r < 0.93:
        return random.choice(DISTANT_LOCATIONS)["name"]
    else:
        return random.choice(INTERNATIONAL_LOCATIONS)["name"]
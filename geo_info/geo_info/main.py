import json
import math
import os
from contextlib import asynccontextmanager
from enum import Enum
from itertools import chain

import numpy as np
import redis.asyncio as redis
from fastapi import FastAPI


R = None
KM_PER_DEGREE = 6378.137 * math.pi * 2 / 360
RING_PATHS = {ring: np.array(path) for ring, path in json.load(open('/app/geo_info/rings.json')).items()}
NUCLEAR_COORDS = np.array([
    [55.794292740049116, 37.46184091892137],  # АО "ВНИИНМ"
    [55.80470737517172, 37.48252144123297],  # НИЦ Курчатовский Институт
    [55.64860834071022, 37.66742255325257],  # НИЯУ МИФИ
    #[],  # Московский филиал ФГУП "РАДОН"
], dtype=np.float64)

@asynccontextmanager
async def lifespan(app: FastAPI):
    global R
    R = redis.Redis(host=os.getenv("HOUSEPRICEESTIMATOR_REDIS_MASTER_SERVICE_HOST", "geoinfo-redis"), max_connections=10)
    yield
    await R.close()

app = FastAPI(lifespan=lifespan)


class OrganizationTypeEnum(Enum):
    food = 'food'
    subway = 'subway'
    railroad = 'railroad'
    sport = 'sport'

    def __str__(self):
        return self.name


def _compute_distance_to_path(path, point):
    distances = np.sum(np.power(point - path, 2), axis=1)
    indices = np.argpartition(distances, 2)
    a, b = path[indices[0]], path[indices[1]]
    return float(np.abs(np.diff((b - a)*(a - point))) / np.sqrt(np.sum(np.power(b - a, 2))))


def compute_distance_to_ring(ring: str, lat: float, lon: float) -> float:
    assert ring in RING_PATHS.keys()
    path = RING_PATHS[ring]
    pos = np.array([lat, lon])
    return KM_PER_DEGREE * _compute_distance_to_path(path, pos)


def _nearest_point(points, point):
    return np.min(np.sqrt(np.sum(np.power(points - point, 2), axis=1)))


async def count_organizations_within_radius(type: OrganizationTypeEnum, lon: float, lat: float, radius: float) -> int:
    results = await R.geosearch(f"organization:{type}", longitude=lon, latitude=lat, radius=radius)
    return len(results)


async def count_food_within_radius_for_price_bounds(lon: float, lat: float, radius: float, price_bounds: list[float]):
    results = list(map(json.loads, await R.geosearch(f"organization:food", longitude=lon, latitude=lat, radius=radius, unit='m')))
    return {f"food_count_{radius}_price_{price_bound if price_bound != math.inf else 'more'}": len(list(filter(lambda x: "mean_price" in x and float(x["mean_price"]) <= price_bound, results))) for price_bound in price_bounds}


# shopping_center, big_market, fitness, swim_pool, ice_rink(каток), stadium, basketball, hospice, detention_facility, detention_facility, public_healthcare, university, workplaces, office, additional_education, preschool, school, big_church, church_synagogue, mosque, theater, museum, exhibition, catering, ecology
async def nearest_organization(type: OrganizationTypeEnum, lon: float, lat: float, return_org: bool = False) -> float:
    results = await R.geosearch(f"organization:{type}", longitude=lon, latitude=lat, radius=200, unit='km', sort='DESC', count=1, withdist=True)
    org, distance = results[0] if len(results) > 0 else (None, math.nan)
    return (json.loads(org), distance) if return_org else distance


@app.get('/describe_area')
async def describe_area(longitude: float, latitude: float) -> dict:
    distances_to_rings = {f"{ring}_km": compute_distance_to_ring(ring, lat=latitude, lon=longitude) for ring in ("sadovoe", "trr", "mkad")}
    nearest_nuclear_distance = _nearest_point(NUCLEAR_COORDS, np.array([latitude, longitude], dtype=np.float64))
    nearest_subway, nearest_subway_distance = await nearest_organization(OrganizationTypeEnum.subway, lon=longitude, lat=latitude, return_org=True)
    nearest_subway_line = nearest_subway['line']
    nearest_subway_name = nearest_subway['name']
    nearest_railroad, nearest_railroad_distance = await nearest_organization(OrganizationTypeEnum.railroad, lon=longitude, lat=latitude, return_org=True)
    nearest_railroad_id = nearest_railroad['platform_id']
    nearest_railroad_route_ids = nearest_railroad['route_id']
    # nearest_kindergarten_distance = nearest_organization(OrganizationTypeEnum.kindergarten, lon=longitude, lat=latitude)
    organizations_count_distances = (500, 1000, 1500, 2000, 3000, 5000)
    food_price_bounds = (500, 1000, 1500, 2500, 4000, math.inf)
    organizations_count_info = dict(chain.from_iterable([
        chain(
            (await count_food_within_radius_for_price_bounds(lon=longitude, lat=latitude, radius=distance, price_bounds=food_price_bounds)).items(),
            (
                (f"food_count_{distance}", await count_organizations_within_radius(OrganizationTypeEnum.food, lon=longitude, lat=latitude, radius=distance)),
                (f"sport_count_{distance}", await count_organizations_within_radius(OrganizationTypeEnum.sport, lon=longitude, lat=latitude, radius=distance)),
            )
        )
        for distance in organizations_count_distances
    ]))
    f = lambda x: print(x) or x
    return f(distances_to_rings  | dict(
        nuclear_km=nearest_nuclear_distance,
        subway_line=nearest_subway_line,
        subway_name=nearest_subway_name,
        subway_km=nearest_subway_distance,
        railroad_id=nearest_railroad_id,
        railroad_routes=nearest_railroad_route_ids,
        railroad_km=nearest_railroad_distance,
        # kindergarten_km=nearest_kindergarten_distance,
    ) | organizations_count_info)
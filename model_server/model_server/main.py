import os
from dataclasses import asdict, dataclass, make_dataclass
from typing import Annotated, Literal

import httpx
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException

from model_server.common import MODEL_REGISTRY
from model_server.literals import APARTMENT_TYPES, BUILDING_TYPES, DECORATING_TYPES, DISTRICTS


Coords = make_dataclass('Coords', [('latitude', float), ('longitude', float)])

@dataclass
class SaleInfo:
    build_year: int
    num_room: str
    height: float
    floor: int
    max_floor: int
    apartment_type: Literal[APARTMENT_TYPES]
    building_type: Literal[BUILDING_TYPES]
    decorating: Literal[DECORATING_TYPES]
    full_sq: float
    live_sq: float
    kitch_sq: float
    district: Literal[DISTRICTS]


app = FastAPI()


@app.post('/predict_price')
async def predict_price(
    coords: Coords,
    sale_info: SaleInfo,
    top_features: int,
) -> dict:
    async with httpx.AsyncClient() as client:
        geoinfo_resp = await client.get(f"{os.getenv('GEOINFO_BASE_URL')}/describe_area", params=asdict(coords))
        if geoinfo_resp.status_code != 200:
            raise HTTPException(status_code=500, detail="GeoInfo service fails")
        sale_features = asdict(sale_info) | geoinfo_resp.json()
        print(sale_features)

    price_predictor_model = MODEL_REGISTRY['price_predictor']
    feature_names = price_predictor_model.feature_names_
    top_features_indices = np.argsort(price_predictor_model.feature_importance_)[:top_features]
    feature_impact = dict(zip(feature_names[top_features_indices], price_predictor_model.feature_importance_[top_features_indices]))

    sale_df = pd.DataFrame({f: [sale_features[f]] for f in feature_names}, columns=feature_names)
    predicted_price = price_predictor_model.predict(sale_df)
    return dict(total=predicted_price[0], details=feature_impact)


@app.post('/find_similar')
async def  find_similar(
    coords: Coords,
    sale_info: SaleInfo,
    similar_items: int,
    top_features: int
):
    async with httpx.AsyncClient() as client:
        geoinfo_resp = await client.get(f"{os.getenv('GEOINFO_BASE_URL')}/describe_area", params=asdict(coords))
        if geoinfo_resp.status_code != 200:
            raise HTTPException(status_code=500, detail="GeoInfo service fails")
        sale_features = asdict(sale_info) | geoinfo_resp.json()
    price_predictor_model = MODEL_REGISTRY['price_predictor']
    feature_names = price_predictor_model.feature_names_
    top_features_indices = np.argsort(price_predictor_model.feature_importance_)[:top_features]
    feature_impact = dict(zip(feature_names[top_features_indices], price_predictor_model.feature_importance_[top_features_indices]))

    sale_df = pd.DataFrame({f: [sale_features[f]] for f in feature_names}, columns=feature_names)
    predicted_price = price_predictor_model.predict(sale_df)

    similarity_ranker = MODEL_REGISTRY['similarity_ranker']
    return dict(similar_sales='')

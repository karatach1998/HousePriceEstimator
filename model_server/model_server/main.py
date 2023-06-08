import os
import re
from dataclasses import asdict, dataclass, make_dataclass
from typing import Annotated, Literal

import httpx
import numpy as np
import pandas as pd
from cachetools import cached, TTLCache
from fastapi import FastAPI, HTTPException

from model_server.common import CATEGORICAL_FEATURES, COLUMNS, MODEL_REGISTRY, preprocess_data, filter_data
from model_server.literals import APARTMENT_TYPES, BUILDING_TYPES, DECORATING_TYPES, DISTRICTS


@cached(cache=TTLCache(maxsize=1, ttl=300))
def get_sales():
    import clickhouse_connect
    client = clickhouse_connect.get_client(
        host=os.getenv('CLICKHOUSE_HOST'),
        user=os.getenv('CLICKHOUSE_USERNAME'),
        password=os.getenv('CLICKHOUSE_PASSWORD')
    )
    df = client.query_df(f"""
SELECT coords.latitude AS latitude, coords.longitude AS longitude, {','.join(COLUMNS)}
FROM sales_info
""")
    df = preprocess_data(df)
    df = filter_data(df)
    return df


Coords = make_dataclass('Coords', [('latitude', float), ('longitude', float)])

@dataclass
class SaleInfo:
    build_year: int
    num_room: int
    apartment_type: Literal[APARTMENT_TYPES]
    building_type: Literal[BUILDING_TYPES]
    decorating: Literal[DECORATING_TYPES]
    height: float
    floor: int
    max_floor: int
    full_sq: float
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
    feature_names = np.array(price_predictor_model.feature_names_, dtype=object)
    top_features_indices = np.argsort(-price_predictor_model.feature_importances_)[:top_features]
    feature_impact = dict(zip(feature_names[top_features_indices], price_predictor_model.feature_importances_[top_features_indices] / 100))

    sale_df = pd.DataFrame({f: [sale_features[f]] for f in feature_names}, columns=feature_names)
    sale_df[CATEGORICAL_FEATURES] = sale_df[CATEGORICAL_FEATURES].astype('category')
    predicted_price = price_predictor_model.predict(sale_df)
    return dict(total=int(predicted_price[0]), details=feature_impact)


def get_ranking_features(sample, df, feature_importances):
    features = {}
    features['distance'] = np.exp(-np.sqrt(np.sum(np.power(np.array([df.longitude-sample.longitude, df.latitude-sample.latitude]), 2))))
    quantitative_features = ('num_room', 'price', 'full_sq', 'height', 'floor', 'build_year')
    for f in quantitative_features:
        features[f'{f}_div'] = feature_importances[f] * (-(df[f] - sample[f]).abs()).apply(np.exp)
    unordered_qualitative_features = ('district', 'apartment_type', 'building_type', 'decorating')
    for f in unordered_qualitative_features:
        features[f'{f}_is_different'] = feature_importances[f] * (df[f] == sample[f])
    return pd.DataFrame(features)


def estimate_similarity_score(sample, df, feature_importances):
    ranking_features = get_ranking_features(sample, df, feature_importances)
    return ranking_features.values.sum(axis=1)


@app.post('/find_similar')
async def  find_similar(
    coords: Coords,
    sale_info: SaleInfo,
    top_similar_items: int,
    top_features: int
) -> dict:
    async with httpx.AsyncClient() as client:
        geoinfo_resp = await client.get(f"{os.getenv('GEOINFO_BASE_URL')}/describe_area", params=asdict(coords))
        if geoinfo_resp.status_code != 200:
            raise HTTPException(status_code=500, detail="GeoInfo service fails")
        sale_features = asdict(coords) | asdict(sale_info) | geoinfo_resp.json()
    price_predictor_model = MODEL_REGISTRY['price_predictor']
    feature_names = np.array(price_predictor_model.feature_names_, dtype=object)
    feature_importances = dict(zip(feature_names, price_predictor_model.feature_importances_))
    top_features_indices = np.argsort(-price_predictor_model.feature_importances_)[:top_features]
    most_important_features_impact = dict(zip(feature_names[top_features_indices], price_predictor_model.feature_importances_[top_features_indices] / 100))

    sale_df = pd.DataFrame({f: [sale_features[f]] for f in feature_names}, columns=feature_names)
    sale_df[CATEGORICAL_FEATURES] = sale_df[CATEGORICAL_FEATURES].astype('category')
    sale_df['price'] = pd.Series(price_predictor_model.predict(sale_df), name='price').astype(np.int32)

    df = get_sales()
    sale_df['longitude'] = np.array([coords.longitude])
    sale_df['latitude'] = np.array([coords.latitude])
    sale = sale_df.iloc[0]
    feature_importances['price'] = 0.8
    scores = estimate_similarity_score(sale, df, feature_importances)
    most_similar_sales = df.iloc[np.argsort(-scores)[:top_similar_items]]

    def _build_sale_desc(sale):
        return dict(price=int(sale.price), details={f: dict(impact=impact, originalPrice=int(sale.price*impact)) for f, impact in most_important_features_impact.items()})

    return dict(
        target=_build_sale_desc(sale),
        similar=[_build_sale_desc(s) for _, s in most_similar_sales.iterrows()]
    )

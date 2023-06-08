import pickle
import re
from operator import attrgetter

import boto3
import numpy as np
import pandas as pd
from cachetools import cachedmethod, TTLCache


class ModelRegistry:
    bucket_name = 'housepriceestimator'

    def __init__(self):
        self._session = boto3.session.Session()
        self._s3 = self._session.client(service_name='s3', endpoint_url="https://storage.yandexcloud.net")
        self.ttl_cache = TTLCache(maxsize=10, ttl=300)
        self._store = {}

    @cachedmethod(attrgetter('ttl_cache'))
    def __getitem__(self, model_name):
        resp = self._s3.get_object(Bucket=self.bucket_name, Key=f'{model_name}.pkl')
        if model_name not in self._store or resp['ETag'] != self._store[model_name][0]:
            self._store[model_name] = (resp['ETag'], pickle.loads(resp['Body'].read()))
        return self._store[model_name][1]

    def __setitem__(self, model_name, model):
        resp = self._s3.put_object(Bucket=self.bucket_name, Key=f'{model_name}.pkl', Body=pickle.dumps(model))
        self._store[model_name] = (resp['ETag'], model)


MODEL_REGISTRY = ModelRegistry()


COLUMNS = [
    "sale_id", "timestamp",
    "district", "num_room ", "price", "price_currency", "apartment_type", "building_type", "decorating",
    "full_sq", "life_sq", "kitch_sq", "height", "floor", "max_floor", "build_year",
    "subway_line", "subway_name", "subway_km", "railroad_id", "railroad_routes", "railroad_km",
    "sadovoe_km", "trr_km", "mkad_km", "nuclear_reactor_km",
    "food_count_500_price_500", "food_count_500_price_1000", "food_count_500_price_1500", "food_count_500_price_2500", "food_count_500_price_4000", "food_count_500_price_more", "food_count_500", "sport_count_500",
    "food_count_1000_price_500", "food_count_1000_price_1000", "food_count_1000_price_1500", "food_count_1000_price_2500", "food_count_1000_price_4000", "food_count_1000_price_more", "food_count_1000", "sport_count_1000",
    "food_count_1500_price_500", "food_count_1500_price_1000", "food_count_1500_price_1500", "food_count_1500_price_2500", "food_count_1500_price_4000", "food_count_1500_price_more", "food_count_1500", "sport_count_1500",
    "food_count_2000_price_500", "food_count_2000_price_1000", "food_count_2000_price_1500", "food_count_2000_price_2500", "food_count_2000_price_4000", "food_count_2000_price_more", "food_count_2000", "sport_count_2000",
    "food_count_3000_price_500", "food_count_3000_price_1000", "food_count_3000_price_1500", "food_count_3000_price_2500", "food_count_3000_price_4000", "food_count_3000_price_more", "food_count_3000", "sport_count_3000",
    "food_count_5000_price_500", "food_count_5000_price_1000", "food_count_5000_price_1500", "food_count_5000_price_2500", "food_count_5000_price_4000", "food_count_5000_price_more", "food_count_5000", "sport_count_5000",
]

CATEGORICAL_FEATURES = ['district', 'apartment_type', 'building_type', 'decorating', 'subway_line', 'subway_name', 'railroad_id']


def preprocess_data(df):
    df.num_room = df.num_room.map(lambda x: x if re.match(r"\d+", x) else 0).astype(np.uint8)
    df.apartment_type = df.apartment_type.str.replace(r"\s*Апартаменты", "", regex=True)
    df.decorating = df.decorating.replace(["Описание квартиры", "Неизвестно", "С отделкой"], "")
    df.replace(r"^\s*$", pd.NA, regex=True, inplace=True)
    df.price = df.price.astype('Int32').replace(0, None)
    df.max_floor = df.max_floor.astype('UInt8').replace(0, None)
    nullable_real_features = ['full_sq', 'life_sq', 'kitch_sq', 'height']
    df[nullable_real_features] = df[nullable_real_features].replace(0.0, np.nan)
    df[CATEGORICAL_FEATURES] = df[CATEGORICAL_FEATURES].astype('category')
    assert [b'RUB'] == df.price_currency.unique()
    df.drop(columns=['price_currency', 'railroad_routes'], inplace=True)
    return df


def filter_data(df):
    df = df.drop(columns=['life_sq', 'kitch_sq'])
    df = df[~df.isna().any(axis=1)]
    return df

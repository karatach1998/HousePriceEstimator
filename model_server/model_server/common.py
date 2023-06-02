import pickle
from operator import attrgetter

import boto3
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


class DummyModel:
    def predict(self, _):
        return [1]

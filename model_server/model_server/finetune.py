import os
import sys
print(sys.path)

import clickhouse_connect
from catboost import CatBoostRegressor

from model_server.common import CATEGORICAL_FEATURES, COLUMNS, MODEL_REGISTRY, preprocess_data, filter_data


def finetune_price_predictor():
    client = clickhouse_connect.get_client(
        host=os.getenv('CLICKHOUSE_HOST'),
        user=os.getenv('CLICKHOUSE_USERNAME'),
        password=os.getenv('CLICKHOUSE_PASSWORD')
    )
    df = client.query_df(f"""
SELECT {','.join(COLUMNS)}
FROM sales_info
""")
    df = preprocess_data(df)
    df = filter_data(df)
    features_df = df.drop(complex=['sales_id', 'timestamp'])
    params = dict(loss_function='RMSE', depth=5, eval_metric='MSLE', task_type='CPU')
    model = CatBoostRegressor(**params, cat_features=CATEGORICAL_FEATURES)
    model.fit(features_df.drop(columns=['price']), features_df.price)
    MODEL_REGISTRY['price_predictor'] = model


if __name__ == '__main__':
    finetune_price_predictor()
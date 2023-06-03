import sys
print(sys.path)

from model_server.common import MODEL_REGISTRY, DummyModel


if __name__ == '__main__':
    MODEL_REGISTRY['price_predictor'] = DummyModel()
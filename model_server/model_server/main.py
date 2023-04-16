from fastapi import FastAPI

app = FastAPI()


@app.get('/estimate_price')
def estimate_price_with_details(top_features: int):
    print(type(top_features))
    features = ('apartment_type', 'building_type', 'full_sq', 'life_sq', 'kitch_sq', 'num_room')
    # complete = features <= kwargs
    # print(complete)
    return {'impact': {'build_year': 0.60, 'num_room': 0.30, 'floor': 0.10}, 'price': 5400000}
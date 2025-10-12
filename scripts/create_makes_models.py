import json


def get_json_data():
    with open('cars_filters.json') as f:
        return json.load(f)

def read_makes_models():
    data = get_json_data()

    makes = data['makes']

    vehicle_types = set()

    for make, info in makes.items():
        is_valid = info.get('is_valid')
        models = info.get('models')
        for model, model_info in models.items():
            if model_info.get('is_valid'):
                vehicle_types.add(model_info.get('vehicle_type'))



    print(vehicle_types)

if __name__ == '__main__':
    read_makes_models()
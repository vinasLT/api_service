import os

from dotenv import load_dotenv
load_dotenv()

AUCTION_API_KEY = os.getenv('AUCTION_API_KEY')
REDIS_URL = os.getenv('REDIS_URL')
DEBUG = os.getenv('DEBUG') == 'true'
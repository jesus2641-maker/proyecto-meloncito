import os
from dotenv import load_dotenv, find_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev")
    
    # Flask-WTF CSRF Configuration
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None
    WTF_CSRF_SSL_STRICT = False

    DATABASE_HOST = os.getenv("DATABASE_HOST", "localhost")
    DATABASE_USER = os.getenv("DATABASE_USER", "root")
    DATABASE_PASSWORD = os.getenv("DATABASE_PASSWORD", "")
    DATABASE_NAME = os.getenv("DATABASE_NAME", "beerhouse_db")

    @staticmethod
    def get_db_config():
        return {
            "host": Config.DATABASE_HOST,
            "user": Config.DATABASE_USER,
            "password": Config.DATABASE_PASSWORD,
            "database": Config.DATABASE_NAME
        }

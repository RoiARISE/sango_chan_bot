import os

from dotenv import load_dotenv


env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=env_path)

# --- Misskey API関連 ---
TOKEN = os.getenv('TOKEN')
INSTANCE_URL = os.getenv('INSTANCE')
WS_URL = f'wss://{INSTANCE_URL}/streaming?i={TOKEN}'

# --- Bot設定 ---
ADMIN_ID = os.getenv('ADMIN_ID')
MAX_NICKNAME_LENGTH = 15

# --- ファイルパス ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NICKNAME_FILE = os.path.join(BASE_DIR, "nickname.json")
import os

from dotenv import load_dotenv


def get_env_variable(name: str) -> str:
    value = os.getenv(name)
    if value is None:
        raise ValueError(f"{name} environment variable is not set.")
    return value


env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=env_path)

# --- Misskey API関連 ---
TOKEN = get_env_variable('TOKEN')

INSTANCE_URL = get_env_variable('INSTANCE')

WS_URL = f'wss://{INSTANCE_URL}/streaming?i={TOKEN}'

# --- Bot設定 ---
ADMIN_ID = os.getenv('ADMIN_ID')
MAX_NICKNAME_LENGTH = 15

# --- ファイルパス ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NICKNAME_FILE = os.path.join(BASE_DIR, "nickname.json")

import os

from dotenv import load_dotenv


def get_env_variable(name: str) -> str:
    value = os.getenv(name)
    if value is None:
        raise ValueError(f"{name} environment variable is not set.")
    return value


_TRUE_VALUES = {"1", "true", "yes", "on"}


def get_bool_env(name: str, default: bool = False) -> bool:
    """環境変数を真偽値として読む。空文字や 0/false/off/no は False。"""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in _TRUE_VALUES


env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(dotenv_path=env_path)

# --- Misskey API関連 ---
TOKEN = get_env_variable('TOKEN')

INSTANCE_URL = get_env_variable('INSTANCE')

WS_URL = f'wss://{INSTANCE_URL}/streaming?i={TOKEN}'
SAFE_WS_URL = f'wss://{INSTANCE_URL}/streaming?i=***'

# --- LLM関連 ---
LLM_ENABLE = get_bool_env('LLM_ENABLE')
LLM_ENDPOINT = os.getenv('LLM_ENDPOINT')
LLM_API_KEY = os.getenv('LLM_API_KEY')
LLM_MODEL = os.getenv('LLM_MODEL')
try:
    LLM_TIMEOUT = float(os.getenv('LLM_TIMEOUT', '60.0'))
except ValueError:
    LLM_TIMEOUT = 60.0


# --- Bot設定 ---
ADMIN_ID = os.getenv('ADMIN_ID')
MAX_NICKNAME_LENGTH = 10

# --- ファイルパス ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USER_DATA_FILE = os.path.join(BASE_DIR, '..', 'data', 'user_data.json')

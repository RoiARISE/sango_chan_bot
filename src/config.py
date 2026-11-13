import os

from dotenv import load_dotenv


def get_env_variable(name: str) -> str:
    value = os.getenv(name)
    if value is None:
        raise ValueError(f"{name} environment variable is not set.")
    return value


env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(dotenv_path=env_path)

# --- Misskey API関連 ---
TOKEN = get_env_variable('TOKEN')

INSTANCE_URL = get_env_variable('INSTANCE')

WS_URL = f'wss://{INSTANCE_URL}/streaming?i={TOKEN}'

# --- LLM関連 ---
LLM_ENABLE = os.getenv('LLM_ENABLE')
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
# 同時に保持できるTodoリマインダー。1人あたりと全体の両方で制限する。
MAX_ACTIVE_TODOS_PER_USER = 5
MAX_ACTIVE_TODOS = 100

# --- ファイルパス ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 旧JSONデータ。SQLiteへの移行元としてのみ使用する。
USER_DATA_FILE = os.path.join(BASE_DIR, '..', 'data', 'user_data.json')
USER_DB_FILE = os.getenv(
    'USER_DB_FILE', os.path.join(BASE_DIR, '..', 'data', 'user_data.sqlite3')
)

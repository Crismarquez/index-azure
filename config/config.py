from pathlib import Path
import sys
import os
import logging
import logging.config

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

from rich.logging import RichHandler
from dotenv import dotenv_values, load_dotenv

BASE_DIR = Path(__file__).parent.parent.absolute()
CONFIG_DIR = Path(BASE_DIR, "config")
LOGS_DIR = Path(BASE_DIR, "logs")
SQLAGENT_DIR = Path(BASE_DIR, "agents","sqlagent")

DATA_DIR = Path(BASE_DIR, "data")

LOGS_DIR.mkdir(parents=True, exist_ok=True)

ENV_VARIABLES = {
    **dotenv_values(BASE_DIR / ".env"),  # load environment variables from .env file
    **os.environ,  # load environment variables from the system
}

load_dotenv(BASE_DIR / ".env")

KEY_VAULT_URL = os.getenv("KEY_VAULT_URL")

if not KEY_VAULT_URL:
    raise RuntimeError("KEY_VAULT_URL no está definido en .env o variables de entorno.")


credential = DefaultAzureCredential()
client = SecretClient(vault_url=KEY_VAULT_URL, credential=credential)

# List of secrets you want to load
SECRETS_TO_LOAD = [
    "AZURE-AI-FOUNDRY-CONNECTION",
    "APP-REGISTRATION-TENANT-ID",
    "APP-REGISTRATION-CLIENT-SECRET",
    "APP-REGISTRATION-CLIENT-ID"
]

for secret_name in SECRETS_TO_LOAD:
    try:
        secret = client.get_secret(secret_name)
        value = secret.value

        # Set in os.environ and ENV_VARIABLES
        os.environ[secret_name] = value
        ENV_VARIABLES[secret_name] = value

    except Exception as e:
        print(f"⚠️ Could not load secret '{secret_name}': {e}")


#Logger
logging_config = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "minimal": {"format": "%(message)s"},
        "detailed": {
            "format": "%(levelname)s %(asctime)s [%(name)s:%(filename)s:%(funcName)s:%(lineno)d]\n%(message)s\n"
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "stream": sys.stdout,
            "formatter": "minimal",
            "level": logging.DEBUG,
        },
        "info": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": Path(LOGS_DIR, "info.log"),
            "maxBytes": 10485760,  # 1 MB
            "backupCount": 10,
            "formatter": "detailed",
            "level": logging.INFO,
        },
        "error": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": Path(LOGS_DIR, "error.log"),
            "maxBytes": 10485760,  # 1 MB
            "backupCount": 10,
            "formatter": "detailed",
            "level": logging.ERROR,
        },
    },
    "root": {
        "handlers": ["console", "info", "error"],
        "level": logging.INFO,
        "propagate": True,
    },
}

logging.config.dictConfig(logging_config)
logger = logging.getLogger()
logger.handlers[0] = RichHandler(markup=True)

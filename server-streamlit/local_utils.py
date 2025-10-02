"""
Utility functions for the greenhouse project.
"""
from dotenv import load_dotenv


def get_config() -> bool:
    """
    Load environment variables from a .env file.

    Returns:
        bool: True if the .env file was loaded successfully, False otherwise.
    """
    conf: bool = load_dotenv(dotenv_path=".env")
    return conf

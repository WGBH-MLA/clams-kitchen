"""
ci_url.py

Python reimplementation of Kevin's Bash script.

Used Gemini 3.1 Pro with the Bash script in the prompt to create
the initial draft.

"""
import os
from pathlib import Path

import yaml
import requests
from requests.exceptions import RequestException

# Path to the config file that contains the secrets
# On a Linux machine, it should live in /home/myuser/.clams-kitchen/secrets/ci.yml
CONFIG_FILE_PATH = Path.home() / ".clams-kitchen" / "secrets" / "ci.yml"


class SonyCiError(Exception):
    """
    Custom exception for Sony Ci API errors.
    """
    pass


def _get_new_access_token(config: dict, token_filepath: Path) -> str:
    """
    Authenticates with the Sony Ci API and retrieves a new access token.
    """

    auth_url = "https://api.cimediacloud.com/oauth2/token"
    
    headers = {
        "Authorization": f"Basic {config.get('cred_string')}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    data = {
        "grant_type": "password",
        "client_id": config.get('client_id'),
        "client_secret": config.get('client_secret')
    }
    
    try:
        response = requests.post(auth_url, headers=headers, data=data, timeout=10)
    except RequestException as e:
        # This catches offline errors, timeouts, etc.
        raise SonyCiError(f"Network error during authentication: {e}")
        
    if response.status_code != 200:
        error_msg = response.json().get('error_description', 'Unknown authentication error')
        raise SonyCiError(f"Authentication failed: {error_msg}")
        
    token_data = response.json()
    access_token = token_data.get('access_token')
    
    # Store the token for persistent re-use
    token_filepath.write_text(access_token)
    
    return access_token


def get_ci_media_url(media_item_id: str) -> str:
    """
    Retrieves the download URL for a given Sony media item ID.
    """
    # 1. Load Configuration
    try:
        with open(CONFIG_FILE_PATH, 'r') as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        raise SonyCiError(f"Config file not found at {CONFIG_FILE_PATH}")
    except yaml.YAMLError as e:
        raise SonyCiError(f"Failed to parse YAML config: {e}")

    workspace_id = config.get('workspace_id')
    if not workspace_id:
        raise SonyCiError("workspace_id is missing from the config file.")

    token_filepath = Path(f"/tmp/{workspace_id}")

    # 2. Retrieve or Generate Access Token
    access_token = None
    if token_filepath.exists():
        access_token = token_filepath.read_text().strip()

    if not access_token:
        access_token = _get_new_access_token(config, token_filepath)

    # 3. Define the Media Request
    def fetch_media(token: str):
        url = f"https://api.cimediacloud.com/assets/{media_item_id}/download"
        headers = {"Authorization": f"Bearer {token}"}
        try:
            return requests.get(url, headers=headers, timeout=10) 
        except RequestException as e:
            raise SonyCiError(f"Network error while fetching media data: {e}")

    # 4. Attempt to fetch media data
    response = fetch_media(access_token)

    # 5. Handle Expired Token Retry (as seen in the bash script)
    if response.status_code != 200:
        access_token = _get_new_access_token(config, token_filepath)
        response = fetch_media(access_token)

    # 6. Final Error Check
    if response.status_code != 200:
        error_msg = f"Status Code: {response.status_code}. Raw Response Text: {response.text}"
        raise SonyCiError(f"Failed to fetch Ci URL. {error_msg}")

    # 7. Return the Location URL
    return response.json().get('location')
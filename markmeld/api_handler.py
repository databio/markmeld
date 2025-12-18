"""API handler for interacting with remote markdown services like HackMD/HedgeDoc."""

import logging
import subprocess
from typing import Dict, List, Optional

import requests

_LOGGER = logging.getLogger(__name__)


def get_pass_secret(pass_secret_name: str) -> Optional[str]:
    """Retrieve a secret using the `pass` password manager.

    Args:
        pass_secret_name: The name/path of the secret in the pass store.

    Returns:
        The secret value if successful, None otherwise.
    """
    try:
        result = subprocess.run(
            ["pass", pass_secret_name], capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error retrieving secret from pass: {e}")
        return None


class APIHandler:
    """Handler for interacting with remote markdown APIs like HackMD or HedgeDoc.

    This class provides methods to authenticate with and fetch notes from
    markdown collaboration services.

    Attributes:
        api_base: The base URL for the API.
    """

    def __init__(
        self,
        api_base: str = "https://api.hackmd.io/v1",
        pass_secret_name: str = "hackmd/api_token",
    ) -> None:
        """Initialize the API handler.

        Args:
            api_base: The base URL for the API.
            pass_secret_name: The name of the secret in the pass store containing
                the API token.
        """
        self._token = get_pass_secret(pass_secret_name)
        self.api_base = api_base

    def set_token(self, token: str) -> None:
        """Set the API authentication token.

        Args:
            token: The API bearer token.
        """
        self._token = token

    @property
    def token(self) -> Optional[str]:
        """Get the API authentication token.

        Returns:
            The API token, or None if not set.
        """
        return getattr(self, "_token", None)

    def list_notes(self) -> Optional[List[Dict]]:
        """List all notes available on the API.

        Returns:
            List of note dictionaries if successful, None otherwise.
        """
        url = f"{self.api_base}/notes"
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Error: {response.status_code}")
                print(response.text)
                return None
        except requests.RequestException as e:
            print(f"Error making API request: {e}")
            return None

    def fetch_note(self, note_id: str) -> Optional[Dict]:
        """Fetch a note from the API.

        Args:
            note_id: The ID of the note to retrieve.

        Returns:
            The note data as a dictionary if successful, None otherwise.
        """
        if not self.token:
            print("Failed to retrieve the token. Must authenticate first!")
            return None

        url = f"{self.api_base}/notes/{note_id}"
        headers = {"Authorization": f"Bearer {self.token}"}

        try:
            _LOGGER.info(f"Fetching note with ID: {note_id}")
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Error: {response.status_code}")
                print(response.text)
                return None
        except requests.RequestException as e:
            print(f"Error making API request: {e}")
            return None

    def fetch_note_content(self, note_id: str) -> Optional[str]:
        """Fetch only the content of a note.

        Args:
            note_id: The ID of the note to retrieve.

        Returns:
            The note content as a string if successful, None if the note
            couldn't be fetched.
        """
        note = self.fetch_note(note_id)
        if note is None:
            return None
        return note.get("content")

import subprocess
import requests
import logging

_LOGGER = logging.getLogger(__name__)

# Function to retrieve the token using `pass hackmd`
def get_pass_secret(pass_secret_name):
    """
    Retrieve a secret using the `pass` command.
    """
    try:
        # Execute the shell command
        result = subprocess.run(["pass", pass_secret_name], capture_output=True, text=True, check=True)
        return result.stdout.strip()  # Remove any leading/trailing whitespace
    except subprocess.CalledProcessError as e:
        print(f"Error retrieving secret from pass: {e}")
        return None


class APIHandler(object):
    """
    Class for interacting with a remote API that serves MD files, such as HackMD or HedgeDoc.
    """

    def __init__(self, api_base="https://api.hackmd.io/v1", pass_secret_name="hackmd/api_token"):
        self._token = get_pass_secret(pass_secret_name)
        self.api_base = api_base

    def set_token(self, token) -> None:
        self._token = token

    @property
    def token(self) -> str:
        if not hasattr(self, "_token"):
            self._token = get_pass_secret(pass_secret_name)
        return self._token

    def list_notes(self) -> list:
        """
        List all notes available on the API.
        """
        url = f"{self.api_base}/notes"
        headers = {
            "Authorization": f"Bearer {self.token}"
        }
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

    def fetch_note(self, note_id) -> dict:
        """
        Fetch a note from the HackMD API using the provided note ID.
        
        Args:
            note_id (str): The ID of the note to retrieve.
            
        Returns:
            dict or None: The note data as a dictionary if successful, None otherwise.
        """
        # Retrieve the token
        if not self.token:
            print("Failed to retrieve the token. Must authenticate first!")
            return None
        # API endpoint
        url = f"{self.api_base}/notes/{note_id}"
        headers = {
            "Authorization": f"Bearer {self.token}"
        }
        # Make the GET request
        try:
            _LOGGER.info(f"Fetching note with ID: {note_id}")
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                return response.json()  # Assuming the response is in JSON format
            else:
                print(f"Error: {response.status_code}")
                print(response.text)
                return None
        except requests.RequestException as e:
            print(f"Error making API request: {e}")
            return None

    def fetch_note_content(self, note_id) -> str:
        note = self.fetch_note(note_id)
        return note["content"]



# # Usage:

# apih = APIHandler(api_base="https://api.hackmd.io/v1", pass_secret_name="hackmd/api_token")
# notes = apih.list_notes()
# note = apih.fetch_note(notes[0]["id"])

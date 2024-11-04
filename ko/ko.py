import json
import os

class Ko:
    def __init__(self, metadata_file='metadata.json'):
        self.metadata_file = metadata_file
        self.metadata = self._load_metadata()
       
    def _load_metadata(self):
        if os.path.exists(self.metadata_file):
            with open(self.metadata_file, 'r') as file:
                return json.load(file)
        else:
            raise FileNotFoundError(f"{self.metadata_file} not found")

    def get_version(self):
        return self.metadata.get('version', 'Unknown version')
    
    def get_metadata(self):
        return self.metadata
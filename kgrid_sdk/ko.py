
import importlib.resources as resources
import json



class Ko:
    METADATA_FILE = "metadata.json"  # by default it is located in the root of the ko

    def __init__(self, package_name, metadata_file=METADATA_FILE):
        self.package_name = package_name
        self.metadata_file = metadata_file
        self.metadata = self._load_metadata()
        

    def _load_metadata(self):
        try:
            package_root = resources.files(self.package_name)
            metadata_path = package_root.parent / self.metadata_file
            if metadata_path.exists():
                with open(metadata_path, "r") as file:
                    return json.load(file)
            else:
                raise FileNotFoundError(f"{metadata_path} not found")
        except ModuleNotFoundError:
            raise ModuleNotFoundError(f"Package '{self.package_name}' not found")

    def get_version(self):
        return self.metadata.get("version", "Unknown version")

    def get_metadata(self):
        return self.metadata

    
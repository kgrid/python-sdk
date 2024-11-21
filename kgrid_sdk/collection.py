
import importlib.resources as resources
import json
from kgrid_sdk.ko import Ko

class Collection:
    METADATA_FILE = "metadata.json"
    def __init__(self, coolection_name,metadata_file=METADATA_FILE):
        self.package_name = coolection_name
        #self.metadata_file = metadata_file
        #self.metadata = self._load_metadata()
        self.knowledge_objects: dict[str, Ko] = {}
        
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

    def add_knowledge_object(self, knowledge_object:Ko):
        if not isinstance(knowledge_object, Ko):
            raise TypeError("Object must inherit from Ko")
        self.knowledge_objects[knowledge_object.package_name] = knowledge_object

    def calculate_for_all(self, patient_data):
        results = {}
        for name, knowledge_object in self.knowledge_objects.items():
            results[name] = knowledge_object.execute(patient_data)
        return results
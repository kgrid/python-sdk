
import importlib.resources as resources
import json



class Ko:
    METADATA_FILE = "metadata.json"  # by default it is located in the root of the ko

    def __init__(self,  metadata_file=METADATA_FILE):
        self.metadata_file = metadata_file
        self.metadata = self.get_metadata()   
    
    @classmethod
    def get_version(cls, metadata_file=METADATA_FILE):
        return cls.get_metadata().get("dc:version", "Unknown version")
    
    @classmethod
    def get_id(cls, metadata_file=METADATA_FILE):
        return cls.get_metadata().get("@id", "Unknown id")
    
    @classmethod
    def get_metadata(cls, metadata_file=METADATA_FILE):
        module = cls.__module__
        
        # Retrieve the package name from the module (assumes single package)
        package = module.split('.')[0]  # Assuming the package is the top-level module
        

        try:
            # Check if the resource exists and get its contents
            package_root = resources.files(package)
            metadata_path = package_root / metadata_file
            if not metadata_path.exists():
                metadata_path = package_root.parent / metadata_file

            if metadata_path.exists():
                with open(metadata_path, "r") as file:
                    return json.load(file)
            else:
                raise FileNotFoundError(f"{metadata_path} not found")
        except Exception as e:
            raise FileNotFoundError(f"Error finding {metadata_file}: {str(e)}")

    
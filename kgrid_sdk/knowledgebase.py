
from kgrid_sdk.ko import Ko

class KnowledgeBase(Ko):
    METADATA_FILE = "metadata.json"
    def __init__(self, knowledgebase_name,metadata_file=METADATA_FILE):
        super().__init__(metadata_file)
        self.knowledgebase_name = knowledgebase_name
        self.metadata_file = metadata_file
        self.knowledge_objects: dict[str, Ko] = {}      
    

    def add_knowledge_object(self, knowledge_object:Ko):
        if not isinstance(knowledge_object, Ko):
            raise TypeError("Object must inherit from Ko")
        self.knowledge_objects[knowledge_object.get_id()] = knowledge_object

    def calculate_for_all(self, patient_data):
        results = {}
        for name, knowledge_object in self.knowledge_objects.items():
            results[name] = knowledge_object.execute(patient_data)
        return results
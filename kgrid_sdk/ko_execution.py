
import inspect
from typing import Callable
from kgrid_sdk.ko import Ko


class Ko_Execution(Ko):
    METADATA_FILE = "metadata.json" 
    def __init__(self,  knowledges, metadata_file=METADATA_FILE):
        super().__init__(metadata_file) # , **kwargs
        self.knowledges = {func.__name__: func for func in knowledges}

    def create_wrapper(self, func: Callable):
        # Get the expected parameter names of the function
        signature = inspect.signature(func)
        param_names = list(signature.parameters.keys())

        def wrapper(input: dict):
            # Extract the required parameters from `input` dict
            kwargs = {name: input.get(name) for name in param_names}
            return func(**kwargs)

        return wrapper

    def execute(
        self, input: dict, knowledge_function: str = None
    ):  # if multiple knowledge functions, mention the function name
        wrapper = self.create_wrapper(self.knowledges[knowledge_function] if knowledge_function else next(iter(self.knowledges.values())))
        
        return wrapper(input)
        # fn = self.knowledges[knowledge_function] if knowledge_function else next(iter(self.knowledges.values()))
        # return fn(**input) #possible solution without wrapper
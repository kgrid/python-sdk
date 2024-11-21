import argparse
import importlib.resources as resources
import inspect
import json
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse


class Ko_copy:
    METADATA_FILE = "metadata.json"  # by default it is located in the root of the ko

    def __init__(self, package_name, knowledges, metadata_file=METADATA_FILE):
        self.package_name = package_name
        self.metadata_file = metadata_file
        self.metadata = self._load_metadata()
        self.knowledges = {func.__name__: func for func in knowledges}
        self.app = FastAPI(
            title=package_name,
            description=self.metadata.get("dc:description", "Unknown description"),
            version=self.get_version(),
            contact={"name": self.metadata.get("koio:contributors", "Unknown contact")},
        )
        self._setup_routes()
        self.parser = None

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
        wrapper = self.create_wrapper(
            self.knowledges[knowledge_function]
            if knowledge_function
            else next(iter(self.knowledges.values()))
        )
        return wrapper(input)


    ### API service methods
    def _setup_routes(self):
        # Root route to redirect to docs
        @self.app.get("/", include_in_schema=False)
        async def root(request: Request):
            return RedirectResponse(url="/docs")

    def add_endpoint(
        self, path: str, knowledge_function: str = None, methods=["POST"], tags=None
    ):  # if multiple knowledge functions, mention the function name
        # Add a custom endpoint to the app
        self.app.add_api_route(
            path,
            self.create_wrapper(
                self.knowledges[knowledge_function]
                if knowledge_function
                else next(iter(self.knowledges.values()))
            ),
            methods=methods,
            tags=tags,
        )

    ###

    ### CLI service methods
    def define_cli(self):
        self.parser = argparse.ArgumentParser(
            description=self.metadata["dc:description"],
            formatter_class=argparse.RawTextHelpFormatter,
        )

    def add_argument(self, *args, **kwargs):
        if not self.parser:
            raise ValueError(
                "CLI parser is not defined. Call define_cli() before adding arguments."
            )
        self.parser.add_argument(*args, **kwargs)

    def execute_cli(self, knowledge_function: str = None):
        if not self.parser:
            raise ValueError(
                "CLI parser is not defined. Call define_cli() and add arguments before executing."
            )
        args = self.parser.parse_args()
        input = vars(args)
        result = self.execute(input, knowledge_function)
        print(json.dumps(result, indent=4))

    ###

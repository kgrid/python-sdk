try:
    from fastapi import FastAPI, Request
    from fastapi.responses import RedirectResponse
except ImportError:
    print("API functionality not installed. Install with `-E api`.")

from kgrid_sdk.ko_execution import Ko_Execution


class Ko_API(Ko_Execution):
    METADATA_FILE = "metadata.json" 
    def __init__(self,  knowledges, metadata_file=METADATA_FILE):
        super().__init__(knowledges,metadata_file)
        
        self.app = FastAPI(
            title=self.metadata.get("dc:title", "Unknown title"),
            description=self.metadata.get("dc:description", "Unknown description"),
            version=self.get_version(),
            contact={"name": self.metadata.get("koio:contributors", "Unknown contact")},
        )
        self._setup_routes()       
    


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

    
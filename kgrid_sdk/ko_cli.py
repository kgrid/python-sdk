import argparse
import json

from kgrid_sdk.ko_execution import Ko_Execution


class Ko_CLI(Ko_Execution):
    METADATA_FILE = "metadata.json" 
    def __init__(self, knowledges, metadata_file=METADATA_FILE):
        super().__init__(knowledges,metadata_file)
        self.parser = None

   
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

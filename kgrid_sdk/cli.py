import importlib.metadata
import json
import tarfile
from pathlib import Path
from typing import Optional

import typer

cli = typer.Typer()


@cli.callback(invoke_without_command=True, no_args_is_help=True)
def no_command(
    version: Optional[bool] = typer.Option(None, "-v", "--version", is_eager=True),
):
    if version:
        try:
            v_str = importlib.metadata.version("kgrid_sdk")
        except AttributeError as e:
            print("N/A ({}) Are you running from source?".format(e.__doc__))
        except Exception as e:
            print("Version: N/A ({})".format(e.__doc__))
        else:
            print("Version: {}".format(v_str))
        finally:
            raise typer.Exit()


@cli.command()
def package(metadata_path: str = "", output: str = "output.tar.gz"):
    """packages the content of the given path using metadata"""
    package_ko(metadata_path, output)


def package_ko(metadata_path, output):
    """
    Packages files and folders referenced in the metadata into a .tar.gz archive.

    :param metadata_path: Path to the metadata JSON file.
    :param output: Path to the output .tar.gz file.
    """
    # Resolve the directory of the metadata file
    metadata_dir = Path(metadata_path).parent.resolve()

    # Load metadata JSON
    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    # Collect all `implementedBy` @ids
    elements_to_package = []
    if "koio:hasKnowledge" in metadata:
        for item in metadata["koio:hasKnowledge"]:
            if "implementedBy" in item and "@id" in item["implementedBy"]:
                relative_path = item["implementedBy"]["@id"]
                full_path = metadata_dir / Path(relative_path)
                elements_to_package.append(full_path)

    # Add documentation files
    if "koio:hasDocumentation" in metadata:
        for doc in metadata["koio:hasDocumentation"]:
            if "@id" in doc:
                relative_path = doc["@id"]
                full_path = metadata_dir / Path(relative_path)
                elements_to_package.append(full_path)

    # Create the .tar.gz archive
    with tarfile.open(output, "w:gz") as tar:
        for path in elements_to_package:
            if path.exists():
                tar.add(path, arcname=path.relative_to(metadata_dir))
            else:
                print(f"Warning: {path} does not exist and will be skipped.")

    print(f"Package created at {output}")


if __name__ == "__main__":
    cli()

import importlib.metadata
import json
import os
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import git
import requests
import typer
from jinja2 import Environment
from pyld import jsonld

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
def package(
    metadata_path: str = "metadata.json", output: str = None, nested: bool = False
):
    """
    packages the content of the given path using metadata.

    Args:
        metadata-path (str): The location of the metadata file. Defaults to metadata.json in the current directory.
        output (str): Location and name to create the package. If it is not provided the name of the parent directory where the metadata file is located and the version name will be used as the name of the output file and the output package will be saved in directory of the metadata file.
        nested (bool): Use this option to have all the files and folders copied in a folder in the created package with the name of the parent directory and the version. By default all the file and folders will be added to the root of the package file.
    """

    # Resolve the directory of the metadata file
    metadata_dir = Path(metadata_path).parent.resolve()

    # Load metadata JSON
    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    elements_to_package = [Path(metadata_path)]
    ids = extract_ids(metadata)
    for relative_path in ids:
        full_path = metadata_dir / Path(relative_path)
        elements_to_package.append(full_path)

    if metadata.get("dc:license", {}).get("@id"):
        elements_to_package.append(metadata_dir / metadata["dc:license"]["@id"])
    cleaned_elements_to_package = filter_files(elements_to_package)

    if not output:
        output = metadata_dir / (
            metadata_dir.name + "-" + metadata["dc:version"] + ".tar.gz"
        )

    # Create the .tar.gz archive
    with tarfile.open(
        output,
        "w:gz",
    ) as tar:
        for path in cleaned_elements_to_package:
            if path.exists():
                tar.add(
                    path,
                    arcname=Path(
                        Path(metadata_path).parent.resolve().name.replace("-", "_")
                        + "_"
                        + metadata["dc:version"].replace("-", "_"),
                        path.relative_to(metadata_dir),
                    )
                    if nested
                    else path.relative_to(metadata_dir),
                )
            else:
                print(
                    f"\033[31mWarning:\033[0m {path} does not exist and will be skipped."
                )

    print(f"\033[32m- Package created\033[0m at {output}")


def extract_ids(metadata):
    ids = []  # List to store all @id values

    # Check if the current data is a dictionary
    if isinstance(metadata, dict):
        # If '@id' is in the dictionary, add its value to the list
        if "@id" in metadata:
            ids.append(metadata["@id"])
        # Recursively search through the dictionary values
        for value in metadata.values():
            ids.extend(extract_ids(value))

    # Check if the current data is a list
    elif isinstance(metadata, list):
        # Recursively search through each item in the list
        for item in metadata:
            ids.extend(extract_ids(item))

    return ids


def filter_files(paths):
    # Convert all paths to pathlib.Path objects
    paths = [Path(p).resolve() for p in paths]

    # Separate files and folders
    folders = {p for p in paths if p.is_dir()}
    files = {p for p in paths if p.is_file()}

    # Filter out files that are already part of a folder
    filtered_files = {
        file
        for file in files
        if not any(file.is_relative_to(folder) for folder in folders)
    }

    # Combine folders and the filtered files
    result = list(folders | filtered_files)
    return result


# Define a custom filter to extract the filename from a URL or path
def get_filename(url):
    if url:
        parsed_url = urlparse(url)
        return os.path.basename(parsed_url.path)
    return "undefined"


@cli.command()
def information_page(
    metadata_path: str = "metadata.json",
    output: str = "index.html",
    include_relative_paths: bool = False,
):
    """
    creates knowledge object information page using metadata

    Args:
        metadata_path (str): Specifies the path to the metadata file. If not provided, the command will look for a file named `metadata.json` in the current directory.
        output (str): Specifies the output path and file name for the generated information page. If not provided, the page will be saved as `index.html` in the current directory.
        include_relative_paths (bool): Indicates whether to include links to local files or to the remote GitHub repository, based on the path where the metadata is located.
    """

    # Load metadata JSON
    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    # Expand metadata using JSON-LD for context required expantions
    base_iri = "."
    expanded_metadata = jsonld.expand(metadata, {"base": base_iri})

    context = {"@context": metadata["@context"]}
    # Check if context["@context"] is a URL then load it
    if isinstance(context["@context"], str):
        # Fetch the external context
        external_context_url = context["@context"]
        response = requests.get(external_context_url)
        external_context = response.json()

        # Replace the external URL in your original context with the external one
        context["@context"] = external_context
        
    # Check if context["@context"] is an array then go through each item
    if isinstance(context["@context"], list):
        new_context = []
        for item in context["@context"]:
            # Check if item is a URL then load it otherwise add it as is
            if isinstance(item, str):
                # Fetch the external context
                external_context_url = item
                response = requests.get(external_context_url)
                external_context = response.json()

                # add the external context 
                new_context.append({"@context":external_context })
            else:
                new_context.append({"@context":item })
        context["@context"] = new_context 
    # Get the branch URL for links
    base_iri = get_github_branch_url(metadata_path)

    if base_iri and not include_relative_paths:
        if not isinstance(context["@context"], list):
            metadata = expand_ids(metadata, {"base": base_iri, "expandContext": context})
        if isinstance(context["@context"], list):
            for ctx in context["@context"]:
                metadata = expand_ids(metadata, {"base": base_iri, "expandContext": ctx})
    else:
        base_iri = "./"
    env = Environment()
    env.filters["filename"] = get_filename
    # Jinja2 template
    template = env.from_string("""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{{ metadata.get("dc:title", "Metadata Page") }}</title>
        <style>
        body {
            font-family: Arial, sans-serif;
            margin: 20px;
        }
        .container {
            max-width: 1000px;
            margin: auto;
            display: flex;
            width: 100%;
        }
        .left-column {
            width: 70%;
            background-color: #f0f0f0;
            padding: 20px;
        }

        /* Right Column */
        .right-column {
            width: 30%;
            background-color: #e9e9e9;
            padding: 20px;
            box-sizing: border-box;
            display: flex;
            flex-direction: column;
            gap: 20px;
        }
        h1 {
            color: #333;
        }
        .metadata {
            background-color: #f9f9f9;
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        .metadata p {
            margin: 5px 0;
        }
        .doc-section, .test-section {
            
            right: 20px;
            width: 250px;
            color: black;
            padding: 10px;
            border-radius: 8px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            max-width: 250px;
            font-size: 16px;
        }
        .doc-section {
            top: 20px;
            background-color: #97c8ed;
        }
        .doc-section h3 {
            margin-top: 0;
        }
        .doc-section a {
            text-decoration: underline;
        }
        .doc-section p {
            margin-top: 5px;
        }
        
        .test-section {
            
            background-color: #96d6b7;
        }
        .test-section h3 {
            margin-top: 0;
        }
        
        .test-section a {
            text-decoration: underline;
        }
        
        .test-section p {
            margin-top: 5px;
        }
    </style>
    </head>
    <body>
        <div class="container">
        <div class="left-column">
            <div class="metadata" id="metadata">
            <h1>{{ metadata.get("dc:title", "Untitled") }}</h1>
            <p>{{ metadata.get("dc:description", "").replace("\n", "<br>") }}</p>
            <p><strong>Id:</strong> <a href="{{base_iri}}" target='_blank'> 
                {{ metadata.get("@id", "Undefined").split('/')[-1] }}
            </a></p>
            <p><strong>Identifier:</strong> {{ metadata.get("dc:identifier", "Undefined") }}</p>
            <p><strong>Type:</strong> <a href="{{ expanded_metadata[0].get('@type', [''])[0] }}" target='_blank'>{{ metadata.get('@type', 'Undefined') }}</a></p>
            <p><strong>Version:</strong> {{ metadata.get("dc:version", "Undefined") }}</p>
            <p><strong>Date:</strong> {{ metadata.get("dc:date", "Undefined") }}</p>
            {% if metadata.get("dc:license") %}
            <p><strong>License:</strong> 
                    <a href="{{ metadata.get("dc:license", {}).get("@id", "undefined") }}" target='_blank'>
                        {{ metadata.get("dc:license", {}).get("@id", "undefined")| filename }}
                    </a></p>
            {% endif %}
            {% if metadata.get("dc:source") %}
                <p><strong>Source:</strong> 
                    <a href="{{ metadata.get("dc:source", "Undefined") }}" target='_blank'>
                        {{ metadata.get("dc:source", "Undefined") }}
                    </a>
                </p>
            {% endif %}
            <hr>
            <h2>Creator Information</h2>
            <p><strong>Name:</strong> {{ metadata.get("schema:creator", {}).get("schema:givenName", "") }}
                {{ metadata.get("schema:creator", {}).get("schema:familyName", "") }} {{ metadata.get("schema:creator", {}).get("schema:name", "") }}</p>
            <p><strong>Affiliation:</strong> {{ metadata.get("schema:creator", {}).get("schema:affiliation", "Undefined") }}</p>
            <p><strong>Email:</strong> 
                <a href="mailto:{{ metadata.get('schema:creator', {}).get('schema:email', 'Undefined') }}" target='_blank'>
                    {{ metadata.get('schema:creator', {}).get('schema:email', 'Undefined') }}
                </a>
            </p>
            <p><strong>Website:</strong> 
                <a href="{{ metadata.get('schema:creator', {}).get('@id', 'Undefined') }}" target='_blank'>
                    {{ metadata.get('schema:creator', {}).get('@id', 'Undefined') }}
                </a>
            </p>

            {% if metadata.get("koio:hasService") %}
            <hr>
            <h2>Services</h2>
            {% for service in metadata.get("koio:hasService", []) %}
                <p><h3> {{ service.get("@id", "").split('/')[-1] }}</h3></p>
                <p><strong>Type:</strong> {{ service.get("@type", ["Undefined"])[0] }}</p>
                <p><strong>Depends on:</strong> {{ service.get("dependsOn", "Undefined") }}</p>
                <p><strong>Implemented by:</strong> 
                    {% if service.get("implementedBy", {}).get("@id", "Undefined") | filename == "" or service.get("implementedBy", {}).get("@id", "Undefined") | filename == "." %}
                        <a href="{{ service.get("implementedBy", {}).get("@id", "Undefined") }}" target='_blank'>
                            {{ service.get("@id", "").replace("_:","")}}
                        </a>
                    {% else%}
                        <a href="{{ service.get("implementedBy", {}).get("@id", "Undefined") }}" target='_blank'>
                            {{ service.get("implementedBy", {}).get("@id", "Undefined") | filename}}
                        </a>                                 
                    {% endif %}                     
                </p>
            {% endfor %}
            {% endif %}
            
            
            {% if metadata.get("koio:hasKnowledge") %}
            <hr>
            <h2>Knowledge</h2>
            {% for knowledge in metadata.get("koio:hasKnowledge", []) %}
                <p><h3> {{ knowledge.get("@id", "").split('/')[-1] }}</h3></p>
                <p><strong>Type:</strong> {{ knowledge.get("@type", ["Undefined"]) }}</p>
                {% if knowledge.get("dc:description") %}
                    <p><strong>Description:</strong> {{ knowledge.get("dc:description", "") }}</p>
                {% endif %}
                {% set implemented_by = knowledge.get("implementedBy", [{}]) %}
                {% set implemented_by = [implemented_by] if implemented_by is mapping else implemented_by %}
                <p><strong>Implemented by:</strong> 
                <ul>
                {% for implementation in implemented_by %}
                    <li>
                    <a href="{{ implementation.get("@id", "Undefined") }}" target='_blank'>
                        {{ implementation.get("dc:title") if implementation.get("dc:title") else implementation.get("@id", "Undefined") | filename}}
                    </a>(type: {{ implementation.get("@type", "Undefined") }})
                    </li>
                {% endfor %}
                </ul>
                </p>
                {% if knowledge.get("dependsOn") %}
                    <p><strong>Depends on:</strong> {{ knowledge.get("dependsOn", "Undefined") }}</p>
                {% endif %}
                {% if knowledge.get("dc:source") %}
                <p><strong>Source:</strong> 
                    <a href="{{ knowledge.get("dc:source", "Undefined") }}" target='_blank'>
                        {{ knowledge.get("dc:source", "Undefined") }}
                    </a>
                </p>
                {% endif %}
                {% if knowledge.get("dc:format") %}
                <p><strong>Format:</strong> 
                    {{ knowledge.get("dc:format", "Undefined") }}
                </p>
                {% endif %}
                {% if knowledge.get("dc:date") %}
                <p><strong>Date:</strong> 
                    {{ knowledge.get("dc:date", "Undefined") }}
                </p>
                {% endif %}
                <b>Creator Information:</b>
                {% if knowledge.get("schema:creator") %}
                <p><strong>Name:</strong> 
                   {{ knowledge.get("schema:creator", {}).get("schema:givenName", "") }} {{ knowledge.get("schema:creator", {}).get("schema:lastName", "") }} {{ knowledge.get("schema:creator", {}).get("schema:name", "") }}
                </p>
                {% if knowledge.get("schema:creator", {}).get("schema:affiliation")%}
                <p><strong>Affiliation:</strong> 
                   {{ knowledge.get("schema:creator", {}).get("schema:affiliation", "") }} 
                </p>
                {% endif %}
                {% if knowledge.get("schema:creator", {}).get("schema:email")%}
                <p><strong>Email:</strong> 
                    <a href="mailto:{{ knowledge.get("schema:creator", {}).get("schema:email", "Undefined") }}" target='_blank'>
                        {{ knowledge.get("schema:creator", {}).get("schema:email", "Undefined") }}
                    </a>
                </p>
                {% endif %}
                {% if knowledge.get("schema:creator", {}).get("@id")%}
                <p><strong>Website:</strong> 
                    <a href="mailto:{{ knowledge.get("schema:creator", {}).get("@id", "Undefined") }}" target='_blank'>
                        {{ knowledge.get("schema:creator", {}).get("@id", "Undefined") }}
                    </a>
                </p>
                {% endif %}
                {% endif %}
            {% endfor %}
            {% endif %}
        </div>            
        </div>
        <div class="right-column">
            <div class="doc-section" id="doc-section">
            {% if documentation %}
                <h2>Documentation</h2>
                {% for doc in documentation %}
                    <h3><a href="{{ doc.get('@id', '#') }}" target='_blank'>{{ doc.get('dc:title', 'Untitled') }}</a></h3>
                    <p>{{ doc.get('dc:description', 'No description') }}</p>
                {% endfor %}
            {% else %}
                <p>No documentation available</p>
            {% endif %}
        </div>

            <div class="test-section" id="test-section">
            {% if tests %}
                <h2>Tests</h2>
                {% for test in tests %}
                    <h3><a href="{{ test.get('implementedBy', {}).get('@id', '#') }}" target='_blank'>{{ test.get('dc:title', 'Untitled') }}</a></h3>
                    <p>{{ test.get('dc:description', 'No description') }}</p>
                {% endfor %}
            {% else %}
                <p>No tests available</p>
            {% endif %}
            </div>
        </div>
        </div>
    </body>
    </html>
    """)

    results = []
    # Find documentation and tests
    documentation = find_item(metadata, "koio:hasDocumentation", results)
    results = []
    tests = find_item(metadata, "koio:hasTest", results)

    # Render the template
    html = template.render(
        metadata=metadata,
        expanded_metadata=expanded_metadata,
        documentation=documentation,
        tests=tests,
        base_iri=os.path.dirname(base_iri),
    )
    with open(output, "w") as f:
        f.write(html)

    print(f"\033[32m- Knowledge object information page created\033[0m at {output}")


def expand_ids(data, base_context):
    if isinstance(data, dict):
        new_data = {}
        for key, value in data.items():
            if key == "@id" and isinstance(value, str):
                # Properly format as a JSON-LD document with context
                jsonld_doc = {"@id": value, "koio:kgrid": "2"}
                # Expand and extract the updated @id
                expanded = jsonld.expand(jsonld_doc, base_context)
                new_data["@id"] = expanded[0].get("@id", value) if expanded else value
            else:
                new_data[key] = expand_ids(value, base_context)  # Recursively process
        return new_data
    elif isinstance(data, list):
        return [expand_ids(item, base_context) for item in data]
    return data  # Return as-is if not a dict or list


def find_item(obj, key, results: list):
    """Recursively find all items with the given key in a nested dictionary."""

    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                if isinstance(v, (list)):
                    for item in v:
                        results.append(item)
                else:
                    results.append(v)
            elif isinstance(v, (dict, list)):
                results = find_item(v, key, results)
    elif isinstance(obj, list):
        for item in obj:
            results = find_item(item, key, results)
    return results


def get_github_branch_url(file_path):
    try:
        folder_path = os.path.dirname(file_path)

        repo = git.Repo(folder_path, search_parent_directories=True)
        repo_root = repo.working_tree_dir
        relative_path = os.path.relpath(file_path, repo_root)

        # Get the remote URL (origin)
        origin_url = repo.remotes.origin.url if repo.remotes else None
        if origin_url and origin_url.endswith(".git"):
            origin_url = origin_url[:-4]  # Remove the last 4 characters

        # Get the current branch name
        branch = repo.active_branch.name

        if origin_url:
            # Convert to GitHub HTTPS URL for the current branch
            if origin_url.startswith("git@github.com:"):
                # If the origin URL is SSH format
                origin_url = origin_url.replace(
                    "git@github.com:", "https://github.com/"
                )

            # Construct the full URL to the current branch
            branch_url = f"{origin_url}/blob/{branch}/{relative_path}"
            return branch_url
        else:
            return None
    except git.exc.InvalidGitRepositoryError:
        return None


@cli.command()
def init(name: str):
    """
    Adds metadata, readme, license and KO information page to a ko folder.

    Args:
        name (str): Knowledge Object name.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(script_dir, "templates", "metadata.json")

    with open(template_path, "r") as file:
        metadata = json.load(file)

    # Update the KO_Title
    metadata["@id"] = name.replace(" ", "-").replace("_", "-")
    metadata["dc:title"] = name
    metadata["dc:date"] = datetime.now().strftime("%Y-%m-%d")
    metadata["dc:version"] = "v1.0"
    metadata["dc:identifier"] = "ark:" + metadata["@id"]
    metadata["dc:license"]["@id"] = "license.md"
    metadata["koio:hasDocumentation"][0]["@id"] = "README.md"
    metadata["koio:hasDocumentation"][0]["dc:title"] = "README.md"
    metadata["koio:hasDocumentation"][0]["dc:description"] = "KO readme file."
    metadata["koio:hasDocumentation"].append(
        {
            "@id": "index.html",
            "@type": "InformationArtifact",
            "dc:title": "Knowledge Object Information Page",
            "dc:description": "Knowledge object information page.",
        }
    )

    # Determine the output path
    save_path = os.getcwd()
    metadata_file = os.path.join(save_path, "metadata.json")

    # Save the modified metadata
    with open(metadata_file, "w") as file:
        json.dump(metadata, file, indent=4)

    print(f"\033[32m- Metadata file saved\033[0m at {metadata_file}")
    license_file = os.path.join(save_path, "license.md")
    with open(license_file, "w") as file:
        file.write("KO's license content goes here.")
    print(f"\033[32m- License file saved\033[0m at {license_file}")

    readme_file = os.path.join(save_path, "README.md")
    with open(readme_file, "w") as file:
        file.write("KO's readme content goes here.")

    print(f"\033[32m- Readme file saved\033[0m at {readme_file}")

    KOInfo_page = os.path.join(save_path, "index.html")
    information_page(os.path.join(save_path, "metadata.json"), KOInfo_page)


# package("/home/faridsei/dev/code/knowledge-base/metadata.json", nested=True)
# package(
#     "metadata.json",
#     nested=True,
# )
# package("/home/faridsei/dev/code/USPSTF-collection/abdominal-aortic-aneurysm-screening/metadata.json", nested=True)

# information_page(
#     "/home/faridsei/dev/code/USPSTF-collection/abdominal-aortic-aneurysm-screening/metadata.json",
#     "/home/faridsei/dev/code/USPSTF-collection/abdominal-aortic-aneurysm-screening/index.html",
#     False,
# )
# information_page(
#     "/home/faridsei/dev/code/knowledge-base-mpog/metadata.json",
#     "/home/faridsei/dev/code/knowledge-base-mpog/index.html",
#     False,
# )
# information_page(
#     "/home/faridsei/dev/code/knowledge-base/metadata.json",
#     "/home/faridsei/dev/code/knowledge-base/index.html",
#     False,
# )
# information_page(
#     "/home/faridsei/dev/code/koio/examples/tobacco_v_2/metadata.json",
#     "/home/faridsei/dev/code/koio/examples/tobacco_v_2/index.html",
#     False,
# )
# init("test")

if __name__ == "__main__":
    cli()

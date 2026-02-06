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
    unexpanded_metadata = metadata
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


    if not base_iri or include_relative_paths:
        base_iri = "./"
    if not isinstance(context["@context"], list):
        metadata = expand_metadata(metadata, {"base": base_iri, "expandContext": context})
    if isinstance(context["@context"], list):
        for ctx in context["@context"]:
            metadata = expand_metadata(metadata, {"base": base_iri, "expandContext": ctx})    

    env = Environment()
    env.filters["filename"] = get_filename
    # Jinja2 template
    template = env.from_string("""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{{ metadata.get("http://purl.org/dc/elements/1.1/title", [{"@value":"Metadata Page"}])[0]["@value"] }}</title>
        <style>
        body {
            font-family: Arial, sans-serif;
            margin: 20px;
        }
        .container {
            max-width: 1400px;
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
            <h1>{{ metadata.get("http://purl.org/dc/elements/1.1/title", [{"@value":"Untitled"}])[0]["@value"] }}</h1>
            <p>{{ metadata.get("http://purl.org/dc/elements/1.1/description", [{"@value":"Untitled"}])[0]["@value"].replace("\n", "<br>") }}</p>
            <p><strong>ID:</strong> <a href="{{unexpanded_metadata.get("@id", "Undefined") if "http" in unexpanded_metadata.get("@id", "Undefined") else base_iri  }}" target='_blank'> 
                {{ unexpanded_metadata.get("@id", "Undefined") if "http" in unexpanded_metadata.get("@id", "Undefined") else metadata.get("@id", "Undefined").split("/")[-1] }}
            </a></p>
            <p><strong>Information page metadata:</strong> <a href="{{base_iri}}/metadata.json" target='_blank'> 
                metadata.json 
            </a></p>
            
            {% set identifiers = metadata.get("http://purl.org/dc/elements/1.1/identifier", [{}]) %}
            {% if identifiers != [{}] %}
                <strong>Identifier:</strong>
                {% set identifiers = [identifiers] if identifiers is mapping else identifiers %}                 
                {% for identifier in identifiers %}                     
                    {{ identifier["@value"]}}{% if not loop.last %}, {% endif %}      
                {% endfor %}
            {% endif %}
            
            
            
            <p><strong>Type:</strong> <a href="{{ expanded_metadata[0].get('@type', [''])[0] }}" target='_blank'>{{ metadata.get('@type', ['Undefined'])[0].replace("https://kgrid.org/koio#","") }}</a></p>
            <p><strong>Version:</strong> {{ metadata.get("http://purl.org/dc/elements/1.1/version", [{"@value":"Undefined"}])[0]["@value"] }}</p>
            <p><strong>Date:</strong> {{ metadata.get("http://purl.org/dc/elements/1.1/date", [{"@value":"Undefined"}])[0]["@value"] }}</p>
            {%if metadata.get("http://schema.org/funder", [{"@value":"Undefined"}]) != [{"@value":"Undefined"}]%}
                <p><strong>Funder:</strong> {{ metadata.get("http://schema.org/funder", [{"@value":"Undefined"}])[0]["@value"] }}</p>
            {% endif %}
            {% if metadata.get("http://purl.org/dc/elements/1.1/license") %}
            <p><strong>License:</strong> 
                    <a href="{{ metadata.get("http://purl.org/dc/elements/1.1/license", [{}])[0].get("@id", "undefined") }}" target='_blank'>
                        {{ metadata.get("http://purl.org/dc/elements/1.1/license", [{}])[0].get("@id", "undefined")| filename }}
                    </a></p>
            {% endif %}
            {% if metadata.get("http://purl.org/dc/elements/1.1/source") %}
                <p><strong>Source:</strong> 
                    <a href="{{ metadata.get("http://purl.org/dc/elements/1.1/source", [{"@value":"Undefined"}])[0]["@value"] }}" target='_blank'>
                        {{ metadata.get("http://purl.org/dc/elements/1.1/source", [{"@value":"Undefined"}])[0]["@value"] }}
                    </a>
                </p>
            {% endif %}
            <hr>
            
            {% set creators = metadata.get("http://schema.org/creator", [{}]) %}
            {% if creators != [{}] %}
                <h2>Creator</h2>
                {% set creators = [creators] if creators is mapping else creators %} 
                <ul>  
                {% for creator in creators %} 
                    <li>
                        <h3> {{ creator.get("http://schema.org/givenName", [{"@value":""}])[0]["@value"] }}
                            {{ creator.get("http://schema.org/familyName",[{"@value":""}])[0]["@value"] }} {{ creator.get("http://schema.org/name", [{"@value":""}])[0]["@value"] }}</h3>
                        <p><strong>Affiliation:</strong> {{ creator.get("http://schema.org/affiliation", [{"@value":"Undefined"}])[0]["@value"] }}</p>
                        {% if creator.get('http://schema.org/roleName', [{"@value":"Undefined"}]) != [{"@value":"Undefined"}] %}
                            <p><strong>Role:</strong>                                
                                {{ creator.get('http://schema.org/roleName', [{"@value":"Undefined"}])[0]["@value"] }}
                            </p>
                        {% endif %}
                        {% if creator.get('http://schema.org/email', [{"@value":"Undefined"}]) != [{"@value":"Undefined"}] %}
                            <p><strong>Email:</strong> 
                                <a href="mailto:{{ creator.get('http://schema.org/email', [{"@value":"Undefined"}])[0]["@value"] }}" target='_blank'>
                                    {{ creator.get('http://schema.org/email', [{"@value":"Undefined"}])[0]["@value"] }}
                                </a>
                            </p>
                        {% endif %}
                        <p><strong>Website:</strong> 
                            <a href="{{ creator.get('@id', 'Undefined') }}" target='_blank'>
                                {{ creator.get('@id', 'Undefined') }}
                            </a>
                        </p>
                    </li>
                {% endfor %}   
                </ul>
            {% endif %}
            {% if metadata.get("http://schema.org/contributor") %}
                <h2>Contributor</h2>
                <p><strong>Name:</strong> {{ metadata.get("http://schema.org/contributor",  [{}])[0].get("http://schema.org/givenName", [{"@value":""}])[0]["@value"] }}
                    {{ metadata.get("http://schema.org/contributor", [{}])[0].get("http://schema.org/familyName",[{"@value":""}])[0]["@value"] }} {{ metadata.get("http://schema.org/contributor", [{}])[0].get("http://schema.org/name", [{"@value":""}])[0]["@value"] }}</p>
                <p><strong>Affiliation:</strong> {{ metadata.get("http://schema.org/contributor", [{}])[0].get("http://schema.org/affiliation", [{"@value":"Undefined"}])[0]["@value"] }}</p>
                <p><strong>Email:</strong> 
                    <a href="mailto:{{ metadata.get('http://schema.org/contributor',  [{}])[0].get('http://schema.org/email', [{"@value":"Undefined"}])[0]["@value"] }}" target='_blank'>
                        {{ metadata.get('http://schema.org/contributor',  [{}])[0].get('http://schema.org/email', [{"@value":"Undefined"}])[0]["@value"] }}
                    </a>
                </p>
                <p><strong>Website:</strong> 
                    <a href="{{ metadata.get('http://schema.org/contributor', [{}])[0].get('@id', 'Undefined') }}" target='_blank'>
                        {{ metadata.get('http://schema.org/contributor',  [{}])[0].get('@id', 'Undefined') }}
                    </a>
                </p>
            {% endif %}
            
            {% if metadata.get("http://purl.org/dc/elements/1.1/publisher") %}
                <p><h2>Publisher</h2> 
                    {{ metadata.get("http://purl.org/dc/elements/1.1/publisher", [{"@value":"Undefined"}])[0]["@value"] }}
                </p>
            {% endif %}
            
            {% set isReferencedBys = metadata.get("http://purl.org/dc/elements/1.1/isReferencedBy", [{}]) %}                  
            {% if isReferencedBys != [{}] %}
                </p><b>Is referenced by:</b></p>
                {% set isReferencedBys = [isReferencedBys] if isReferencedBys is mapping else isReferencedBys %}   
                <ul>                 
                {% for isReferencedBy in isReferencedBys %} 
                    <li>     
                    <a href="{{ isReferencedBy["@id"] }}" target='_blank'>
                        {{ isReferencedBy["http://purl.org/dc/elements/1.1/bibliographicCitation"][0]["@value"] }}
                    </a>
                    </li>
                {% endfor %}   
                </ul>
            {% endif %}

            {% if knowledge_items!=[] %}
                <hr>
                <h2>Knowledge</h2>
                {% for knowledge in knowledge_items %}
                    {% set hasKnowledgeObject = knowledge.get("https://kgrid.org/koio#hasKnowledgeObject", [{}]) %}
                    {% set knowledgeType = knowledge.get("@type", ["Undefined"])[0]%}
                    {% if knowledgeType ==  "https://kgrid.org/koio#KnowledgeSet" and hasKnowledgeObject ==  [{}]%}  
                        <p><a href='{{ knowledge.get("@id", "") }}' target='_blank'>
                            <h3> {{ knowledge.get("http://purl.org/dc/elements/1.1/title", [{"@value": knowledge.get("@id", "").split('/')[-1]}])[0]["@value"] }}</h3>
                        </a>
                    {% else%}</p>
                        <p><h3> {{ knowledge.get("http://purl.org/dc/elements/1.1/title", [{"@value": knowledge.get("@id", "").split('/')[-1]}])[0]["@value"] }}</h3></p>
                    {% endif %}     
                    <p><strong>ID:</strong> 
                        {{ knowledge.get("@id", "").split('/')[-1] }}
                    </p>

                    <p><strong>Type:</strong> 
                            <a href="{{ knowledge.get("@type", ["Undefined"])[0] }}" target='_blank'>
                                {{ knowledge.get("@type", ["Undefined"])[0].replace("https://kgrid.org/koio#","") }}
                            </a>
                    </p>
                    {% if knowledge.get("http://purl.org/dc/elements/1.1/description") %}
                        <p><strong>Description:</strong> {{ knowledge.get("http://purl.org/dc/elements/1.1/description", [{"@value":""}])[0]["@value"] }}</p>
                    {% endif %}
                    {% if knowledge.get("http://purl.org/dc/elements/1.1/publisher") %}
                        <p><strong>Publisher:</strong> 
                            {{ knowledge.get("http://purl.org/dc/elements/1.1/publisher", [{"@value":"Undefined"}])[0]["@value"] }}
                        </p>
                    {% endif %}
                    {% if knowledge.get("http://purl.org/dc/elements/1.1/date") %}
                        <p><strong>Date:</strong> 
                            {{ knowledge.get("http://purl.org/dc/elements/1.1/date", [{"@value":"Undefined"}])[0]["@value"] }}
                        </p>
                    {% endif %}
                    {% set creators = knowledge.get("http://schema.org/creator", [{}]) %}
                    {% if creators != [{}] %}
                        <b>Creator:</b>
                        {% set creators = [creators] if creators is mapping else creators %}   
                        <ul>                 
                        {% for creator in creators %} 
                            <li>  
                                <p>
                                {{ creator.get("http://schema.org/givenName",[{"@value":""}])[0]["@value"] }} {{ creator.get("http://schema.org/lastName", [{"@value":""}])[0]["@value"] }} {{ creator.get("http://schema.org/name",[{"@value":""}])[0]["@value"] }}
                                </p>
                                {% if creator.get("http://schema.org/affiliation")%}
                                <p><strong>Affiliation:</strong> 
                                {{ creator.get("http://schema.org/affiliation",[{"@value":""}])[0]["@value"] }} 
                                </p>
                                {% endif %}
                                {% if knowledge.get("http://schema.org/creator",[{}])[0].get("http://schema.org/email")%}
                                <p><strong>Email:</strong> 
                                    <a href="mailto:{{ creator.get("http://schema.org/email", [{"@value":"Undefined"}])[0]["@value"] }}" target='_blank'>
                                        {{ creator.get("http://schema.org/email", [{"@value":"Undefined"}])[0]["@value"] }}
                                    </a>
                                </p>
                                {% endif %}
                                {% if creator.get("@id")%}
                                <p><strong>Website:</strong> 
                                    <a href="mailto:{{ creator.get("@id", "Undefined") }}" target='_blank'>
                                        {{ creator.get("@id", "Undefined") }}
                                    </a>
                                </p>
                            </li>      
                            {% endif %}
                        {% endfor %}   
                        </ul>
                    {% endif %}
                    {% if knowledge.get("http://purl.org/dc/elements/1.1/source") %}
                        <p><strong>Source:</strong> 
                            <a href="{{ knowledge.get("http://purl.org/dc/elements/1.1/source", [{"@value":"Undefined"}])[0]["@value"] }}" target='_blank'>
                                {{ knowledge.get("http://purl.org/dc/elements/1.1/source", [{"@value":"Undefined"}])[0]["@value"] }}
                            </a>
                        </p>
                    {% endif %}            
                    {% set isReferencedBys = knowledge.get("http://purl.org/dc/elements/1.1/isReferencedBy", [{}]) %}                  
                    {% if isReferencedBys != [{}] %}
                        </p><b>Is referenced by:</b></p>
                        {% set isReferencedBys = [isReferencedBys] if isReferencedBys is mapping else isReferencedBys %}   
                        <ul>                 
                        {% for isReferencedBy in isReferencedBys %} 
                            <li>     
                            <a href="{{ isReferencedBy["@value"] }}" target='_blank'>
                                {{ isReferencedBy["@value"] }}
                            </a>
                            </li>
                        {% endfor %}   
                        </ul>
                    {% endif %}
                    {% if knowledge.get("http://schema.org/endorsers") %}
                        <p><strong>Endorsers:</strong> 
                            {{ knowledge.get("http://schema.org/endorsers", [{"@value":"Undefined"}])[0]["@value"] }}
                        </p>
                    {% endif %}
                    {% set implemented_by = knowledge.get("http://www.ebi.ac.uk/swo/SWO_0000085", [{}]) %}                   
                    {% if implemented_by != [{}]%}
                        {% set implemented_by = [implemented_by] if implemented_by is mapping else implemented_by %}
                        <p><strong>Implemented by:</strong> 
                        <ul>
                        {% for implementation in implemented_by %}
                            <li>
                            <a href="{{ implementation.get("@id", "Undefined") }}" target='_blank'>
                                {{ implementation.get("http://purl.org/dc/elements/1.1/title") if implementation.get("http://purl.org/dc/elements/1.1/title") else implementation.get("@id", "Undefined") | filename}}
                            </a><br/>(type: 
                                {% set imp_types = implementation.get("@type", "Undefined")%}
                                {% for imp_type in imp_types %}<a href="{{ imp_type }}" target='_blank'>{{ imp_type.replace(base_iri , "").replace("/" , "")}}</a>{% if not loop.last %}, {% endif %}{% endfor %})
                            </li>
                        {% endfor %}
                        </ul>
                        </p>
                    {% endif %}                  
                    {% if hasKnowledgeObject != [{}]%}
                        <p><strong>Knowledge Objects:</strong> 
                        <ul>
                        {% for ko in hasKnowledgeObject %}
                            <li>
                            <a href="{{ ko.get("@id", ko.get("@value", "Undefined")) }}" target='_blank'>
                                {{ ko.get("@id", ko.get("@value", "Undefined")) }}
                            </a>
                            </li>
                        {% endfor %}
                        </ul>
                        </p>
                    {% endif %}                    
                    {% if knowledge.get("http://purl.obolibrary.org/obo/RO_0002502") %}
                        <p><strong>Depends on:</strong> {{ knowledge.get("http://purl.obolibrary.org/obo/RO_0002502",  [{}])[0].get("@id", "Undefined").split('/')[-1] }}</p>
                    {% endif %}
                    
                    {% if knowledge.get("http://purl.org/dc/elements/1.1/format") %}
                    <p><strong>Format:</strong> 
                        {{ knowledge.get("http://purl.org/dc/elements/1.1/format", [{"@value":"Undefined"}])[0]["@value"] }}
                    </p>
                    {% endif %}                   
                {% endfor %}
            {% endif %}

            {% if services != [] %}
            <hr>
            <h2>Services</h2>
            
            {% for service in services %}

                <p><h3> {{ service.get("@id", "").split('/')[-1] }}</h3></p>
                <p><strong>Type:</strong> 
                        <a href="{{ service.get("@type", ["Undefined"])[0] }}" target='_blank'>
                            {{ service.get("@type", ["Undefined"])[0].replace("https://kgrid.org/koio#","") }}
                        </a>
                </p>
                <p><strong>Depends on:</strong> 
                
                {% for depend in service.get("http://purl.obolibrary.org/obo/RO_0002502", [{}]) %}
                    {{ depend.get("@id", "Undefined").split('/')[-1] }}{% if not loop.last %}, {% endif %}
                {% endfor %}
                
                </p>
                {% if service.get("http://www.ebi.ac.uk/swo/SWO_0004001") %}
                        <p><strong>Has interface:</strong> 
                            <a href="{{ service.get("http://www.ebi.ac.uk/swo/SWO_0004001", [{"@id":"Undefined"}])[0]["@id"] }}" target='_blank'>
                                {{ service.get("http://www.ebi.ac.uk/swo/SWO_0004001", [{"@value":"Undefined"}])[0]["@id"] }}
                            </a>
                        </p>
                {% endif %} 
                {% set implemented_by = service.get("http://www.ebi.ac.uk/swo/SWO_0000085", [{}]) %}
                {% if implemented_by != [{}]%}
                    <p><strong>Implemented by:</strong> 
                    <ul>
                        {% for implementation in implemented_by %}
                            <li>
                            {% if implementation.get("@id", "Undefined") | filename == "" or implementation.get("@id", "Undefined") | filename == "." %}
                                <a href="{{ implementation.get("@id", "Undefined") }}" target='_blank'>
                                    {{ service.get("@id", "").replace("_:","")}}
                                </a>
                            {% else%}
                                <a href="{{ implementation.get("@id", "Undefined") }}" target='_blank'>
                                    {{ implementation.get("@id", "Undefined") | filename}}
                                </a>                                 
                            {% endif %}   
                            </li>
                        {% endfor %}      
                        </ul>            
                    </p>
                {% endif %}
            {% endfor %}
            {% endif %}
        </div>            
        </div>
        <div class="right-column">
            <div class="doc-section" id="doc-section">
            {% if documentation %}
                <h2>Documentation</h2>
                <ul>
                {% for doc in documentation %}
                    <li>
                        <h3><a href="{{ doc.get('@id', '#') }}" target='_blank'>{{ doc.get('http://purl.org/dc/elements/1.1/title', [{"@value":"Untitled"}])[0]["@value"] }}</a></h3>
                        <p>{{ doc.get('http://purl.org/dc/elements/1.1/description', [{"@value":"No description"}])[0]["@value"] }}</p>
                        {% if doc.get("item_of","")!="" %}
                            <p><strong>Document of:</strong> {{doc.get("item_of","")[0]["@value"]}} ({{ doc.get("type","") }}) </p>
                        {% endif %}
                        <p><strong>Type:</strong> 
                        {% set imp_types = doc.get('@type', '#')%}
                        {% for imp_type in imp_types %}  
                                <a href="{{ imp_type }}" target='_blank'>
                                    {{ imp_type.replace("https://kgrid.org/koio#","").split("/")[-1]}}
                                </a>{% if not loop.last %}, {% endif %}
                        {% endfor %}
                        <br/><br/>
                    </li>
                {% endfor %}
                </ul>
            {% else %}
                <p>No documentation available</p>
            {% endif %}
        </div>

            <div class="test-section" id="test-section">
            {% if tests %}
                <h2>Tests</h2>
                <ul>
                {% for test in tests %}
                    <li>
                        <h3><a href="{{ test.get('http://www.ebi.ac.uk/swo/SWO_0000085', [{}])[0].get('@id', '#') }}" target='_blank'>{{ test.get('http://purl.org/dc/elements/1.1/title', [{"@value":"Untitled"}])[0]["@value"] }}</a></h3>
                        <p>{{ test.get('http://purl.org/dc/elements/1.1/description', [{"@value":"No description"}])[0]["@value"] }}</p>
                        {% if test.get("item_of","")!="" %}
                            <p><strong>Test of:</strong> {{test.get("item_of","")[0]["@value"]}} ({{ test.get("type","") }}) </p>
                        {% endif %}
                        <p><strong>Type:</strong> 
                        {% set imp_types = test.get('http://www.ebi.ac.uk/swo/SWO_0000085', [{}])[0].get('@type', '#')%}
                        {% for imp_type in imp_types %}  
                                <a href="{{ imp_type }}" target='_blank'>
                                    {{ imp_type.split("/")[-1]}}
                                </a>{% if not loop.last %}, {% endif %}
                        {% endfor %}
                    </li>
                {% endfor %}
                </ul>
            {% else %}
                <p>No tests available</p>
            {% endif %}
            </div>
        </div>
        </div>
    </body>
    </html>
    """)

    
    documentation = find_item(metadata, "https://kgrid.org/koio#hasDocumentation", [],metadata.get("http://purl.org/dc/elements/1.1/title", ""), metadata.get("@type", [])[0].split('/')[-1])
    tests = find_item(metadata, "https://kgrid.org/koio#hasTest", [],metadata.get("http://purl.org/dc/elements/1.1/title", ""), metadata.get("@type", {"@value":[]})[0].split('/')[-1])
    knowledge_items = metadata.get("https://kgrid.org/koio#hasKnowledge", [])
    services = metadata.get("https://kgrid.org/koio#hasService", [])
    # Render the template
    html = template.render(
        metadata=metadata,
        expanded_metadata=expanded_metadata,
        unexpanded_metadata=unexpanded_metadata,
        documentation=documentation,
        tests=tests,
        knowledge_items=knowledge_items,
        services=services,
        base_iri=os.path.dirname(base_iri),
    )
    with open(output, "w") as f:
        f.write(html)

    print(f"\033[32m- Knowledge object information page created\033[0m at {output}")


def expand_metadata(data, base_context):
    return jsonld.expand(data, base_context)[0]  # Return as-is if not a dict or list


def find_item(obj, key, results: list, title, obj_type):
    """Recursively find all items with the given key in a nested dictionary."""

    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                if isinstance(v, (list)):
                    for item in v:
                        item["item_of"] = title
                        item["type"] = obj_type
                        results.append(item)
                else:
                    v["item_of"] = title
                    v["type"] = obj_type
                    results.append(v)
            elif isinstance(v, (dict, list)):
                obj_type = get_object_types(obj)
                results = find_item(v, key, results, obj.get("http://purl.org/dc/elements/1.1/title", [{"@value": obj.get("@id", "").split('/')[-1]}]), obj_type)
    elif isinstance(obj, list):
        for item in obj:
            if not isinstance(item, str):
                obj_type = get_object_types(item)
                results = find_item(item, key, results, item.get("http://purl.org/dc/elements/1.1/title", [{"@value": item.get("@id", "").split('/')[-1]}]),  obj_type)
    return results

def get_object_types(obj):
    obj_type = ""
    if isinstance( obj.get("@type"), list):
        types = obj.get("@type", [])
        for i,item in enumerate(types):
            is_last = (i == len(types) - 1)
            obj_type += item.split('/')[-1] + ("" if is_last else ",")
    else:
        obj_type = obj.get("@type", "").split('/')[-1]
    return obj_type

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
    metadata["hasDocumentation"][0]["@id"] = "README.md"
    metadata["hasDocumentation"][0]["dc:title"] = "README.md"
    metadata["hasDocumentation"][0]["dc:description"] = "KO readme file."
    metadata["hasDocumentation"].append(
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
# package("/home/faridsei/dev/code/USPSTF-collection/abdominal-aortic-aneurysm-screening/metadata.json", nested=True)
# information_page(
#     "/home/faridsei/dev/code/USPSTF-collection/abdominal-aortic-aneurysm-screening/metadata.json",
#     "/home/faridsei/dev/code/USPSTF-collection/abdominal-aortic-aneurysm-screening/index.html",
#     False,
# )
# information_page(
#     "/home/faridsei/dev/test/knowledge-base-obi/metadata.json",
#     "/home/faridsei/dev/test/knowledge-base-obi/index.html",
#     False,
# )
# information_page(
#     "/home/faridsei/dev/code/pgx-knowledge-assembly/collection/CPIC_Phenotype_CYP2D6/metadata.json",
#     "/home/faridsei/dev/code/pgx-knowledge-assembly/collection/CPIC_Phenotype_CYP2D6/index.html",
#     False,
# )
# information_page(
#     "/home/faridsei/dev/test/knowledge-base-sandbox/metadata.json",
#     "/home/faridsei/dev/test/knowledge-base-sandbox/index.html",
#     False,
# )

information_page(
    "/home/faridsei/dev/code/ICPSR-ex1-MIHD/metadata.json",
    "/home/faridsei/dev/code/ICPSR-ex1-MIHD/index.html",
    False,
)

# information_page(
#     "/home/faridsei/dev/code/nephroticsyndrome-computablephenotype/metadata.json",
#     "/home/faridsei/dev/code/nephroticsyndrome-computablephenotype/index.html",
#     False,
# )
# init("test")

if __name__ == "__main__":
    cli()

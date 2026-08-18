import importlib.metadata
import json
import os
import tarfile
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional
from urllib.parse import quote, unquote, urlparse, urlencode, urljoin


import git
import requests
import typer
from jinja2 import Environment
from pyld import jsonld

cli = typer.Typer()


class _LinkExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)


def _github_file_url(url):
    parsed = urlparse(url)
    if parsed.netloc == "raw.githubusercontent.com":
        return url
    if parsed.netloc != "github.com":
        return None

    parts = parsed.path.strip("/").split("/")
    if len(parts) < 5 or parts[2] != "blob":
        return None
    return f"https://raw.githubusercontent.com/{parts[0]}/{parts[1]}/{parts[3]}/{'/'.join(parts[4:])}"


def validate_information_page_links(html, output_path, request_get=requests.get):
    """Validate local file links and GitHub blob links from rendered page HTML."""
    parser = _LinkExtractor()
    parser.feed(html)

    checked_links = []
    output_dir = Path(output_path).resolve().parent
    for href in dict.fromkeys(parser.links):
        parsed = urlparse(href)
        github_file_url = _github_file_url(href)
        if github_file_url:
            try:
                response = request_get(github_file_url, timeout=10, stream=True)
                is_valid = response.status_code == 200
                detail = f"HTTP {response.status_code}"
            except requests.RequestException as error:
                is_valid = False
                detail = str(error)
            checked_links.append({
                "link": href,
                "kind": "github",
                "valid": is_valid,
                "detail": detail,
            })
        elif not parsed.scheme and not href.startswith("#"):
            target_path = (output_dir / unquote(parsed.path)).resolve()
            is_valid = target_path.is_file()
            checked_links.append({
                "link": href,
                "kind": "local",
                "valid": is_valid,
                "detail": str(target_path),
            })

    defective_links = [link for link in checked_links if not link["valid"]]
    return {
        "summary": {
            "checked": len(checked_links),
            "valid": len(checked_links) - len(defective_links),
            "defective": len(defective_links),
        },
        "defective_links": defective_links,
    }


def print_link_validation_report(html, output_path):
    report = validate_information_page_links(html, output_path)
    summary = report["summary"]
    print(
        "- Link validation: "
        f"{summary['checked']} checked, {summary['valid']} valid, "
        f"{summary['defective']} defective"
    )
    for link in report["defective_links"]:
        print(f"  - {link['kind']}: {link['link']} ({link['detail']})")
    return report


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

def github_blob_to_binder(url: str, kernel_name: str = "javascript", ref: str = "HEAD") -> str:
    """
    Convert:
    https://github.com/{owner}/{repo}/blob/{branch}/{path}
    ->
    https://mybinder.org/v2/gh/{owner}/{repo}/{ref}?urlpath=lab/tree/{path}%3Fkernel_name%3D...
    """
    if not url:
        return "#"

    parsed = urlparse(url)
    if parsed.netloc != "github.com":
        return "#"

    parts = parsed.path.strip("/").split("/")
    # expected: owner repo blob branch ...path
    if len(parts) < 5 or parts[2] != "blob":
        return "#"

    owner, repo = parts[0], parts[1]
    notebook_path = "/".join(parts[4:])  # skip owner/repo/blob/branch
    urlpath = quote(f"lab/tree/{notebook_path}?kernel_name={kernel_name}", safe="/")

    return f"https://mybinder.org/v2/gh/{owner}/{repo}/{ref}?urlpath={urlpath}"

def github_blob_to_scribbler(url: str, ref: str = "HEAD") -> str:
    if not url:
        return "#"

    parsed = urlparse(url)
    if parsed.netloc != "github.com":
        return "#"

    parts = parsed.path.strip("/").split("/")
    # expected: owner/repo/blob/branch/path...
    if len(parts) < 5 or parts[2] != "blob":
        return "#"

    owner, repo = parts[0], parts[1]
    notebook_path = "/".join(parts[4:])

    raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{notebook_path}"
    return "https://app.scribbler.live/?" + urlencode({"jsnb": raw_url})


def _to_text(value, default=""):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                return item
            if isinstance(item, dict):
                if "@value" in item and item["@value"]:
                    return str(item["@value"])
                if "@id" in item and item["@id"]:
                    return str(item["@id"])
        return default
    if isinstance(value, dict):
        if "@value" in value and value["@value"]:
            return str(value["@value"])
        if "@id" in value and value["@id"]:
            return str(value["@id"])
    return default


def _item_title(item, default="Untitled"):
    if not isinstance(item, dict):
        return default
    return _to_text(item.get("http://purl.org/dc/elements/1.1/title"), default)


def _item_ref(item, default=""):
    if not isinstance(item, dict):
        return default
    return item.get("@id") or _item_title(item, default)


def _ref_aliases(ref):
    aliases = set()
    if not ref:
        return aliases

    ref_str = str(ref)
    aliases.add(ref_str)
    cleaned = ref_str.rstrip("/")
    if cleaned:
        aliases.add(cleaned)
    if "/" in cleaned:
        aliases.add(cleaned.split("/")[-1])
    if "#" in cleaned:
        aliases.add(cleaned.split("#")[-1])
    return aliases


def build_relationship_graph(metadata, knowledge_items, services, tests, documentation, base_iri="."):
    nodes = {}
    node_types = {}
    node_full_labels = {}
    node_links = {}
    edges = set()
    ref_to_node = {}

    def sanitize_label(label):
        return (
            str(label)
            .replace("\\", "\\\\")
            .replace('"', "'")
            .replace("\n", " ")
            .strip()
        )

    def compact_label(label, max_chars=34):
        clean = " ".join(str(label).split())
        if len(clean) <= max_chars:
            return clean
        return clean[: max_chars - 3].rstrip() + "..."

    def add_node(node_key, label, node_type):
        if node_key not in nodes:
            node_id = f"N{len(nodes) + 1}"
            clean_label = sanitize_label(" ".join(str(label).split()))
            nodes[node_key] = (node_id, sanitize_label(compact_label(clean_label)))
            node_types[node_id] = node_type
            node_full_labels[node_id] = clean_label
        return nodes[node_key][0]

    def resolve_link(ref):
        if not ref:
            return None
        ref_str = str(ref).strip()
        if not ref_str or ref_str.startswith("_:"):
            return None
        if ref_str.startswith(("http://", "https://", "mailto:")):
            return ref_str
        if ref_str.startswith(("#", "/", "./", "../")):
            return ref_str
        return urljoin(f"{base_iri.rstrip('/')}/", ref_str)

    def map_ref(ref, node_id):
        for alias in _ref_aliases(ref):
            ref_to_node[alias] = node_id

    def first_artifact_link(item):
        implemented_by = item.get("http://www.ebi.ac.uk/swo/SWO_0000085", [])
        if isinstance(implemented_by, dict):
            implemented_by = [implemented_by]

        for implementation in implemented_by:
            if isinstance(implementation, dict):
                artifact_ref = implementation.get("@id") or implementation.get("@value")
                if artifact_ref:
                    return resolve_link(artifact_ref)
        return None

    ko_title = _item_title(metadata, "Knowledge Object")
    ko_ref = metadata.get("@id", ko_title)
    ko_node = add_node("ko:main", ko_title, "ko")
    node_links[ko_node] = resolve_link(ko_ref)
    map_ref(ko_ref, ko_node)
    map_ref(ko_title, ko_node)

    for idx, knowledge in enumerate(knowledge_items):
        fallback = knowledge.get("@id", f"Knowledge {idx + 1}").split("/")[-1]
        label = _item_title(knowledge, fallback)
        ref = _item_ref(knowledge, f"knowledge-{idx + 1}")
        node_key = f"knowledge:{ref}:{idx}"
        node_id = add_node(node_key, label, "knowledge")
        node_links[node_id] = first_artifact_link(knowledge)
        map_ref(ref, node_id)
        map_ref(label, node_id)
        edges.add((ko_node, node_id, "has"))

    for idx, service in enumerate(services):
        fallback = service.get("@id", f"Service {idx + 1}").split("/")[-1]
        label = _item_title(service, fallback)
        ref = _item_ref(service, f"service-{idx + 1}")
        node_key = f"service:{ref}:{idx}"
        node_id = add_node(node_key, label, "service")
        node_links[node_id] = first_artifact_link(service)
        map_ref(ref, node_id)
        map_ref(label, node_id)
        edges.add((ko_node, node_id, "has"))

    # Service can depend on one or more knowledge items.
    # Add direct service -> knowledge dependency links when the metadata contains RO_0002502.
    for service in services:
        service_ref = _item_ref(service)
        service_node = ref_to_node.get(str(service_ref), None)
        if not service_node:
            continue

        depends_on = service.get("http://purl.obolibrary.org/obo/RO_0002502", [])
        if isinstance(depends_on, dict):
            depends_on = [depends_on]

        for dep in depends_on:
            dep_ref = None
            if isinstance(dep, dict):
                dep_ref = dep.get("@id") or dep.get("@value")
            elif isinstance(dep, str):
                dep_ref = dep

            target_node = None
            for alias in _ref_aliases(dep_ref):
                if alias in ref_to_node:
                    target_node = ref_to_node[alias]
                    break

            if target_node and target_node != service_node:
                edges.add((service_node, target_node, "depends"))

    for idx, test in enumerate(tests):
        fallback = test.get("@id", f"Test {idx + 1}").split("/")[-1]
        label = _item_title(test, fallback)
        ref = _item_ref(test, f"test-{idx + 1}")
        node_key = f"test:{ref}:{idx}"
        node_id = add_node(node_key, label, "test")
        node_links[node_id] = first_artifact_link(test)
        map_ref(ref, node_id)
        map_ref(label, node_id)
        parent_ref = test.get("parent_ref")
        parent_node = ref_to_node.get(str(parent_ref), ko_node)
        edges.add((parent_node, node_id, "has"))

    for idx, doc in enumerate(documentation):
        fallback = doc.get("@id", f"Documentation {idx + 1}").split("/")[-1]
        label = _item_title(doc, fallback)
        ref = _item_ref(doc, f"doc-{idx + 1}")
        node_key = f"doc:{ref}:{idx}"
        node_id = add_node(node_key, label, "doc")
        node_links[node_id] = resolve_link(ref)
        parent_ref = doc.get("parent_ref")
        parent_node = ref_to_node.get(str(parent_ref), ko_node)
        edges.add((parent_node, node_id, "has"))

    graph_nodes = []
    for node_id, label in nodes.values():
        graph_nodes.append({
            "id": node_id,
            "label": label,
            "full_label": node_full_labels.get(node_id, label),
            "type": node_types.get(node_id, "doc"),
            "link": node_links.get(node_id),
        })

    graph_edges = [
        {"source": source, "target": target, "type": edge_type}
        for source, target, edge_type in sorted(edges)
    ]

    type_counts = {"ko": 0, "knowledge": 0, "service": 0, "test": 0, "doc": 0}
    for node in graph_nodes:
        node_type = node.get("type")
        if node_type in type_counts:
            type_counts[node_type] += 1

    edge_counts = {"has": 0, "depends": 0}
    for edge in graph_edges:
        edge_type = edge.get("type")
        if edge_type in edge_counts:
            edge_counts[edge_type] += 1

    return {
        "nodes": graph_nodes,
        "edges": graph_edges,
        "counts": type_counts,
        "edge_counts": edge_counts,
    }

@cli.command()
def information_page(
    metadata_path: str = "metadata.json",
    output: str = "index.html",
    include_relative_paths: bool = False
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
    env.filters["binder_url"] = github_blob_to_binder
    env.filters["scribbler_url"] = github_blob_to_scribbler

    # Jinja2 template
    template = env.from_string("""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{{ metadata.get("http://purl.org/dc/elements/1.1/title", [{"@value":"Metadata Page"}])[0]["@value"] }}</title>
        <style>
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Serif:wght@400;500;600&display=swap');

        :root {
            --bg-a: #eef2f6;
            --bg-b: #edf1f5;
            --ink: #132235;
            --muted: #526274;
            --panel: #ffffff;
            --line: #d9e1ea;
            --brand: #005ea8;
            --brand-2: #0d6b5f;
            --legend-knowledge-stroke: #cc7a00;
            --legend-service-stroke: #2d6ea3;
            --legend-test-stroke: #2b8a3e;
            --legend-doc-stroke: #7a4ab3;
            --surface-soft: #f6f9fc;
            --shadow: 0 2px 10px rgba(19, 34, 53, 0.06);
        }

        * {
            box-sizing: border-box;
        }

        body {
            margin: 0;
            color: var(--ink);
            background: linear-gradient(180deg, var(--bg-a) 0%, var(--bg-b) 100%);
            font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
            line-height: 1.5;
            padding: 32px;
        }

        h1, h2, h3 {
            font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
            letter-spacing: 0.01em;
            line-height: 1.2;
        }

        a {
            color: var(--brand);
            text-decoration-thickness: 2px;
            text-underline-offset: 2px;
        }

        .page-hero {
            max-width: 1400px;
            margin: 0 auto 22px auto;
            border: 1px solid var(--line);
            border-radius: 12px;
            background: #ffffff;
            padding: 24px 26px;
            box-shadow: var(--shadow);
            animation: fade-in-up 300ms ease-out both;
        }

        .page-hero h1 {
            margin: 0 0 10px 0;
            font-size: clamp(1.45rem, 2.2vw, 2rem);
        }

        .page-subtitle {
            margin: 0 0 16px 0;
            color: var(--muted);
            font-size: 0.95rem;
            max-width: 78ch;
        }

        .stat-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(120px, 1fr));
            gap: 12px;
        }

        .stat-pill {
            border: 1px solid var(--line);
            border-radius: 10px;
            background: var(--surface-soft);
            padding: 11px 14px;
            color: #2a3b4f;
            font-size: 0.84rem;
            text-align: left;
            white-space: nowrap;
            font-weight: 600;
        }

        .graph-panel {
            max-width: 1400px;
            margin: 0 auto 22px auto;
            border: 1px solid var(--line);
            border-radius: 12px;
            background: var(--panel);
            box-shadow: var(--shadow);
            padding: 20px;
            animation: fade-in-up 340ms ease-out both;
        }

        .graph-panel > summary {
            cursor: pointer;
            list-style: none;
            display: block;
            position: relative;
            padding: 2px 84px 12px 2px;
            font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
            font-weight: 700;
            font-size: 1.02rem;
        }

        .graph-summary-title {
            display: block;
            margin-bottom: 10px;
        }

        .graph-summary-stats {
            margin-top: 0;
        }

        .graph-panel[open] .graph-summary-stats {
            display: none;
        }

        .graph-panel > summary::-webkit-details-marker {
            display: none;
        }

        .graph-panel > summary::after {
            content: "Show";
            color: var(--brand);
            font-size: 0.82rem;
            border: 1px solid var(--line);
            border-radius: 999px;
            padding: 4px 10px;
            background: var(--surface-soft);
            position: absolute;
            top: 0;
            right: 0;
        }

        .graph-panel[open] > summary::after {
            content: "Hide";
        }

        .graph-panel h2 {
            margin-top: 2px;
            margin-bottom: 10px;
            font-size: 1.08rem;
            border-left: 3px solid var(--brand);
            padding-left: 12px;
        }

        .graph-panel p {
            margin: 0 0 14px 0;
            color: var(--muted);
        }

        .graph-panel .mermaid {
            background: #fcfdfe;
            border: 1px solid var(--line);
            border-radius: 10px;
            padding: 12px 12px 18px 12px;
            max-height: 300px;
            overflow: hidden;
        }

        .graph-panel .mermaid svg {
            font-size: 8px;
            max-width: 100%;
            width: auto;
            height: auto;
            display: block;
            margin: 0 auto;
        }

        .graph-legend {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin: 0 0 12px 0;
            padding: 0;
            list-style: none;
        }

        .graph-node-legend {
            flex-wrap: nowrap;
            gap: 6px;
            overflow-x: auto;
            overflow-y: hidden;
            padding-bottom: 2px;
        }

        .graph-node-legend .graph-legend-item {
            padding: 5px 9px 5px 7px;
            font-size: 0.78rem;
        }

        .graph-node-legend .count {
            font-size: 0.74rem;
        }

        .graph-legend-layout {
            display: flex;
            flex-wrap: wrap;
            gap: 16px;
            align-items: flex-start;
            margin-bottom: 12px;
        }

        .graph-legend-group {
            flex: 1 1 360px;
            min-width: 280px;
        }

        .graph-legend-group-title {
            margin: 0;
            font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
            font-weight: 700;
            font-size: 0.86rem;
            color: var(--muted);
            white-space: nowrap;
        }

        .graph-legend-inline-title {
            display: inline-flex;
            align-items: center;
            margin-right: 2px;
        }

        .graph-legend-item {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            border: 1px solid var(--line);
            border-radius: 999px;
            background: #ffffff;
            padding: 6px 12px 6px 8px;
            font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
            font-size: 0.82rem;
            color: var(--muted);
            cursor: pointer;
            white-space: nowrap;
        }

        .graph-legend-item input {
            width: 18px;
            height: 18px;
            margin: 0;
            accent-color: var(--brand);
        }

        .graph-legend-item input[data-node-type] {
            appearance: none;
            -webkit-appearance: none;
            border: 1px solid var(--node-stroke, var(--brand));
            border-radius: 5px;
            background: var(--node-fill, #ffffff);
            display: inline-grid;
            place-content: center;
        }

        .graph-legend-item input[data-node-type]::before {
            content: "";
            width: 5px;
            height: 10px;
            transform: scale(0);
            transition: transform 120ms ease-in-out;
            border-right: 2px solid rgba(0, 0, 0, 0.55);
            border-bottom: 2px solid rgba(0, 0, 0, 0.55);
            transform-origin: center;
            rotate: 45deg;
        }

        .graph-legend-item input[data-node-type]:checked::before {
            transform: scale(1);
        }

        .graph-legend-item input[data-node-type]:focus-visible {
            outline: 2px solid rgba(0, 94, 168, 0.35);
            outline-offset: 1px;
        }

        .graph-legend-item input[data-node-type="ko"] { --node-fill: #fff3cd; --node-stroke: #b08900; }
        .graph-legend-item input[data-node-type="knowledge"] { --node-fill: #ffd9b3; --node-stroke: #cc7a00; }
        .graph-legend-item input[data-node-type="service"] { --node-fill: #cde8ff; --node-stroke: #2d6ea3; }
        .graph-legend-item input[data-node-type="test"] { --node-fill: #d6f5df; --node-stroke: #2b8a3e; }
        .graph-legend-item input[data-node-type="doc"] { --node-fill: #efe0ff; --node-stroke: #7a4ab3; }

        .graph-legend-item input[data-edge-type] {
            appearance: none;
            -webkit-appearance: none;
            border: 1px solid var(--edge-stroke, var(--brand));
            border-radius: 5px;
            background: #ffffff;
            display: inline-grid;
            place-content: center;
        }

        .graph-legend-item input[data-edge-type]::before {
            content: "";
            width: 5px;
            height: 10px;
            transform: scale(0);
            transition: transform 120ms ease-in-out;
            border-right: 2px solid rgba(0, 0, 0, 0.55);
            border-bottom: 2px solid rgba(0, 0, 0, 0.55);
            transform-origin: center;
            rotate: 45deg;
        }

        .graph-legend-item input[data-edge-type]:checked::before {
            transform: scale(1);
        }

        .graph-legend-item input[data-edge-type]:focus-visible {
            outline: 2px solid rgba(0, 94, 168, 0.35);
            outline-offset: 1px;
        }

        .graph-legend-item input[data-edge-type="has"] { --edge-stroke: #000000; }
        .graph-legend-item input[data-edge-type="depends"] { --edge-stroke: #cc7a00; }

        .graph-legend-item .count {
            color: var(--ink);
            font-weight: 700;
            font-size: 0.78rem;
            display: inline-flex;
            align-items: center;
            line-height: 1;
        }

        .legend-arrow {
            width: 18px;
            height: 0;
            border-top: 3px solid #2b8a3e;
            position: relative;
            margin-right: 2px;
            flex: 0 0 auto;
        }

        .legend-arrow::after {
            content: "";
            position: absolute;
            right: -2px;
            top: -5px;
            border-left: 6px solid currentColor;
            border-top: 4px solid transparent;
            border-bottom: 4px solid transparent;
            color: inherit;
        }

        .legend-arrow-has {
            border-top-color: #000000;
            color: #000000;
        }

        .legend-arrow-depends {
            border-top-color: #cc7a00;
            border-top-style: dashed;
            color: #cc7a00;
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
            display: grid;
            grid-template-columns: minmax(0, 2.2fr) minmax(320px, 1fr);
            width: 100%;
            gap: 24px;
            align-items: start;
        }

        .left-column,
        .right-column {
            border: 1px solid var(--line);
            background: var(--panel);
            border-radius: 12px;
            box-shadow: var(--shadow);
            padding: 22px;
            animation: fade-in-up 360ms ease-out both;
        }

        .metadata {
            background: #ffffff;
            border: 1px solid var(--line);
            border-radius: 12px;
            padding: 22px;
        }

        .metadata .metadata-title {
            margin-top: 0;
            font-size: clamp(1.1rem, 1.6vw, 1.25rem);
            margin-bottom: 12px;
        }

        .metadata p {
            margin: 10px 0;
        }

        .metadata hr {
            border: none;
            border-top: 1px solid var(--line);
            margin: 18px 0;
        }

        .metadata ul {
            margin: 8px 0 16px 0;
            padding-left: 22px;
        }

        .metadata li {
            margin-bottom: 12px;
        }

        .metadata h2 {
            margin-top: 24px;
            margin-bottom: 12px;
            font-size: 1.08rem;
            border-left: 3px solid var(--brand);
            padding-left: 12px;
        }

        .metadata h2.section-emphasis,
        .doc-section h2.section-emphasis,
        .test-section h2.section-emphasis {
            margin-top: 26px;
            margin-bottom: 14px;
            font-size: 1.24rem;
            font-weight: 700;
            letter-spacing: 0.01em;
            border-left-width: 5px;
            background: #f6f9fc;
            border-radius: 8px;
            padding: 8px 12px;
        }

        .section-emphasis.section-knowledge {
            border-left-color: var(--legend-knowledge-stroke);
        }

        .section-emphasis.section-service {
            border-left-color: var(--legend-service-stroke);
        }

        .section-emphasis.section-doc {
            border-left-color: var(--legend-doc-stroke);
        }

        .section-emphasis.section-test {
            border-left-color: var(--legend-test-stroke);
        }

        .metadata h3 {
            margin: 8px 0;
            font-size: 1rem;
        }

        .right-column {
            display: flex;
            flex-direction: column;
            gap: 20px;
            position: sticky;
            top: 16px;
        }

        .doc-section,
        .test-section {
            color: var(--ink);
            border-radius: 12px;
            border: 1px solid var(--line);
            box-shadow: 0 2px 8px rgba(19, 34, 53, 0.04);
            font-size: 0.96rem;
            padding: 16px;
        }

        .doc-section {
            background: #fdfefe;
        }

        .test-section {
            background: #fdfefe;
        }

        .doc-section h2,
        .test-section h2 {
            margin-top: 2px;
            margin-bottom: 12px;
            font-size: 1.04rem;
            border-left: 3px solid var(--brand-2);
            padding-left: 10px;
        }

        .doc-section ul,
        .test-section ul {
            margin: 0;
            padding-left: 0;
            list-style: none;
        }

        .doc-section li,
        .test-section li {
            background: #ffffff;
            border: 1px solid var(--line);
            border-radius: 10px;
            padding: 12px;
            margin-bottom: 12px;
        }

        .doc-section h3,
        .test-section h3 {
            margin: 2px 0 8px 0;
            font-size: 0.98rem;
        }

        .doc-section img,
        .test-section img {
            vertical-align: middle;
            margin-right: 6px;
        }

        @keyframes fade-in-up {
            from {
                opacity: 0;
                transform: translateY(8px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }

        @media (max-width: 1100px) {
            .container {
                grid-template-columns: 1fr;
            }

            .right-column {
                position: static;
            }
        }

        @media (max-width: 640px) {
            body {
                padding: 18px;
            }

            .graph-panel .mermaid svg {
                max-width: 100%;
            }

            .stat-grid {
                grid-template-columns: repeat(2, minmax(120px, 1fr));
            }
        }
    </style>
    </head>
    <body>
        <section class="page-hero">
            <h1>{{ metadata.get("http://purl.org/dc/elements/1.1/title", [{"@value":"Knowledge Object"}])[0]["@value"] }}</h1>
        </section>
        <details class="graph-panel" id="relationshipGraph" open>
            <summary>
                <span class="graph-summary-title">Relationship Graph</span>
                <div class="stat-grid graph-summary-stats">
                    <div class="stat-pill">Computable Knowledge: {{ knowledge_items|length }}</div>
                    <div class="stat-pill">Services: {{ services|length }}</div>
                    <div class="stat-pill">Documentation: {{ documentation|length }}</div>
                    <div class="stat-pill">Tests: {{ tests|length }}</div>
                </div>
            </summary>
            <div class="graph-legend-layout">
                <div class="graph-legend-group">
                    <ul class="graph-legend graph-node-legend">
                        <li class="graph-legend-inline-title">
                            <span class="graph-legend-group-title">Nodes:</span>
                        </li>
                        <li>
                            <label class="graph-legend-item">
                                <input type="checkbox" data-node-type="knowledge" checked>
                                <span>Computable Knowledge</span>
                                <span class="count">({{ graph_counts.get("knowledge", 0) }})</span>
                            </label>
                        </li>
                        <li>
                            <label class="graph-legend-item">
                                <input type="checkbox" data-node-type="service" checked>
                                <span>Service</span>
                                <span class="count">({{ graph_counts.get("service", 0) }})</span>
                            </label>
                        </li>
                        <li>
                            <label class="graph-legend-item">
                                <input type="checkbox" data-node-type="test" checked>
                                <span>Test</span>
                                <span class="count">({{ graph_counts.get("test", 0) }})</span>
                            </label>
                        </li>
                        <li>
                            <label class="graph-legend-item">
                                <input type="checkbox" data-node-type="doc" checked>
                                <span>Documentation</span>
                                <span class="count">({{ graph_counts.get("doc", 0) }})</span>
                            </label>
                        </li>
                    </ul>
                </div>
                <div class="graph-legend-group">
                    <ul class="graph-legend graph-edge-legend">
                        <li class="graph-legend-inline-title">
                            <span class="graph-legend-group-title">Relationship Arrows:</span>
                        </li>
                        <li>
                            <label class="graph-legend-item">
                                <input type="checkbox" data-edge-type="has" checked>
                                <span class="legend-arrow legend-arrow-has"></span>
                                <span>has</span>
                                <span class="count">({{ graph_edge_counts.get("has", 0) }})</span>
                            </label>
                        </li>
                        <li>
                            <label class="graph-legend-item">
                                <input type="checkbox" data-edge-type="depends">
                                <span class="legend-arrow legend-arrow-depends"></span>
                                <span>depends on</span>
                                <span class="count">({{ graph_edge_counts.get("depends", 0) }})</span>
                            </label>
                        </li>
                    </ul>
                </div>
            </div>
            <div class="mermaid" id="graphMermaid"></div>
        </details>
        <div class="container">
        <div class="left-column">
            <div class="metadata" id="metadata">
            <h2 class="metadata-title">Overview</h2>
            <p>{{ metadata.get("http://purl.org/dc/elements/1.1/description", [{"@value":"Untitled"}])[0]["@value"].replace("\n", "<br>") }}</p>
            <hr>
            <p><strong>ID:</strong> <a href="{{unexpanded_metadata.get("@id", "Undefined") if "http" in unexpanded_metadata.get("@id", "Undefined") else base_iri  }}" target='_blank' rel='noopener noreferrer'> 
                {{ unexpanded_metadata.get("@id", "Undefined") if "http" in unexpanded_metadata.get("@id", "Undefined") else metadata.get("@id", "Undefined").split("/")[-1] }}
            </a></p>
            <p><strong>Information page metadata:</strong> <a href="{{base_iri}}/metadata.json" target='_blank' rel='noopener noreferrer'> 
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
            
            
            
            <p><strong>Type:</strong> <a href="{{ expanded_metadata[0].get('@type', [''])[0] }}" target='_blank' rel='noopener noreferrer'>{{ metadata.get('@type', ['Undefined'])[0].replace("https://kgrid.org/koio#","") }}</a></p>
            <p><strong>Version:</strong> {{ metadata.get("http://purl.org/dc/elements/1.1/version", [{"@value":"Undefined"}])[0]["@value"] }}</p>
            <p><strong>Date:</strong> {{ metadata.get("http://purl.org/dc/elements/1.1/date", [{"@value":"Undefined"}])[0]["@value"] }}</p>
            {%if metadata.get("http://schema.org/funder", [{"@value":"Undefined"}]) != [{"@value":"Undefined"}]%}
                <p><strong>Funder:</strong> {{ metadata.get("http://schema.org/funder", [{"@value":"Undefined"}])[0]["@value"] }}</p>
            {% endif %}
            {% if metadata.get("http://purl.org/dc/elements/1.1/license") %}
            <p><strong>License:</strong> 
                    <a href="{{ metadata.get("http://purl.org/dc/elements/1.1/license", [{}])[0].get("@id", "undefined") }}" target='_blank' rel='noopener noreferrer'>
                        {{ metadata.get("http://purl.org/dc/elements/1.1/license", [{}])[0].get("@id", "undefined")| filename }}
                    </a></p>
            {% endif %}
            
            {% set sources = metadata.get("http://purl.org/dc/elements/1.1/source", [{}]) %}                  
            {% if sources != [{}] %}
                </p><b>Source:</b></p>
                {% set sources = [sources] if sources is mapping else sources %}   
                <ul>                 
                {% for source in sources %} 
                    <li>     
                    <a href="{{ source["@id"] }}" target='_blank' rel='noopener noreferrer'>
                        {{ source["http://purl.org/dc/elements/1.1/bibliographicCitation"][0]["@value"] }}
                    </a>
                    </li>
                {% endfor %}   
                </ul>
            {% endif %}
            
            {% set isReferencedBys = metadata.get("http://purl.org/dc/elements/1.1/isReferencedBy", [{}]) %}                  
            {% if isReferencedBys != [{}] %}
                </p><b>Is referenced by:</b></p>
                {% set isReferencedBys = [isReferencedBys] if isReferencedBys is mapping else isReferencedBys %}   
                <ul>                 
                {% for isReferencedBy in isReferencedBys %} 
                    <li>     
                    <a href="{{ isReferencedBy["@id"] }}" target='_blank' rel='noopener noreferrer'>
                        {{ isReferencedBy["http://purl.org/dc/elements/1.1/bibliographicCitation"][0]["@value"] }}
                    </a>
                    </li>
                {% endfor %}   
                </ul>
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
                                <a href="mailto:{{ creator.get('http://schema.org/email', [{"@value":"Undefined"}])[0]["@value"] }}" target='_blank' rel='noopener noreferrer'>
                                    {{ creator.get('http://schema.org/email', [{"@value":"Undefined"}])[0]["@value"] }}
                                </a>
                            </p>
                        {% endif %}
                        <p><strong>Website:</strong> 
                            <a href="{{ creator.get('@id', 'Undefined') }}" target='_blank' rel='noopener noreferrer'>
                                {{ creator.get('@id', 'Undefined') }}
                            </a>
                        </p>
                    </li>
                {% endfor %}   
                </ul>
            {% endif %}
            {% if metadata.get("http://schema.org/contributor") %}
                <h2 class="section-emphasis">Contributor</h2>
                <p><strong>Name:</strong> {{ metadata.get("http://schema.org/contributor",  [{}])[0].get("http://schema.org/givenName", [{"@value":""}])[0]["@value"] }}
                    {{ metadata.get("http://schema.org/contributor", [{}])[0].get("http://schema.org/familyName",[{"@value":""}])[0]["@value"] }} {{ metadata.get("http://schema.org/contributor", [{}])[0].get("http://schema.org/name", [{"@value":""}])[0]["@value"] }}</p>
                <p><strong>Affiliation:</strong> {{ metadata.get("http://schema.org/contributor", [{}])[0].get("http://schema.org/affiliation", [{"@value":"Undefined"}])[0]["@value"] }}</p>
                <p><strong>Email:</strong> 
                    <a href="mailto:{{ metadata.get('http://schema.org/contributor',  [{}])[0].get('http://schema.org/email', [{"@value":"Undefined"}])[0]["@value"] }}" target='_blank' rel='noopener noreferrer'>
                        {{ metadata.get('http://schema.org/contributor',  [{}])[0].get('http://schema.org/email', [{"@value":"Undefined"}])[0]["@value"] }}
                    </a>
                </p>
                <p><strong>Website:</strong> 
                    <a href="{{ metadata.get('http://schema.org/contributor', [{}])[0].get('@id', 'Undefined') }}" target='_blank' rel='noopener noreferrer'>
                        {{ metadata.get('http://schema.org/contributor',  [{}])[0].get('@id', 'Undefined') }}
                    </a>
                </p>
            {% endif %}
            
            {% if metadata.get("http://purl.org/dc/elements/1.1/publisher") %}
                <h2 class="section-emphasis">Publisher</h2>
                <p>
                    {{ metadata.get("http://purl.org/dc/elements/1.1/publisher", [{"@value":"Undefined"}])[0]["@value"] }}
                </p>
            {% endif %}           
            <br/>

            {% if knowledge_items!=[] %}
                <hr>
                <h2 class="section-emphasis section-knowledge">Knowledge</h2>
                {% for knowledge in knowledge_items %}
                    {% set hasKnowledgeObject = knowledge.get("https://kgrid.org/koio#hasKnowledgeObject", [{}]) %}
                    {% set knowledgeType = knowledge.get("@type", ["Undefined"])[0]%}
                    {% set knowledge_anchor = knowledge.get("@id", "").split('/')[-1] %}
                    <a id="graph-knowledge-{{ loop.index }}"></a>
                    <a id="{{ knowledge_anchor }}"></a>
                    {% if knowledgeType ==  "https://kgrid.org/koio#KnowledgeSet" and hasKnowledgeObject ==  [{}]%}  
                        <p><a href='{{ knowledge.get("@id", "") }}' target='_blank' rel='noopener noreferrer'>
                            <h3> {{ knowledge.get("http://purl.org/dc/elements/1.1/title", [{"@value": knowledge.get("@id", "").split('/')[-1]}])[0]["@value"] }}</h3>
                        </a>
                    {% else%}</p>
                        <p><h3> {{ knowledge.get("http://purl.org/dc/elements/1.1/title", [{"@value": knowledge.get("@id", "").split('/')[-1]}])[0]["@value"] }}</h3></p>
                    {% endif %}     
                    <p><strong>ID:</strong> 
                        {{ knowledge_anchor }}
                    </p>

                    <p><strong>Type:</strong> 
                            <a href="{{ knowledge.get("@type", ["Undefined"])[0] }}" target='_blank' rel='noopener noreferrer'>
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
                                    <a href="mailto:{{ creator.get("http://schema.org/email", [{"@value":"Undefined"}])[0]["@value"] }}" target='_blank' rel='noopener noreferrer'>
                                        {{ creator.get("http://schema.org/email", [{"@value":"Undefined"}])[0]["@value"] }}
                                    </a>
                                </p>
                                {% endif %}
                                {% if creator.get("@id")%}
                                <p><strong>Website:</strong> 
                                    <a href="mailto:{{ creator.get("@id", "Undefined") }}" target='_blank' rel='noopener noreferrer'>
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
                            <a href="{{ knowledge.get("http://purl.org/dc/elements/1.1/source", [{"@value":"Undefined"}])[0]["@value"] }}" target='_blank' rel='noopener noreferrer'>
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
                            <a href="{{ isReferencedBy["@value"] }}" target='_blank' rel='noopener noreferrer'>
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
                            <a href="{{ implementation.get("@id", "Undefined") }}" target='_blank' rel='noopener noreferrer'>
                                {{ implementation.get("http://purl.org/dc/elements/1.1/title") if implementation.get("http://purl.org/dc/elements/1.1/title") else implementation.get("@id", "Undefined") | filename}}
                            </a><br/>(type: 
                                {% set imp_types = implementation.get("@type", "Undefined")%}
                                {% for imp_type in imp_types %}<a href="{{ imp_type }}" target='_blank' rel='noopener noreferrer'>{{ imp_type.replace("http://www.ebi.ac.uk/swo/SWO_0000118","Python").replace("http://www.ebi.ac.uk/swo/SWO_0000108","JavaScript").split("/")[-1].split("#")[-1]}}</a>{% if not loop.last %}, {% endif %}{% endfor %})
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
                            <a href="{{ ko.get("@id", ko.get("@value", "Undefined")) }}" target='_blank' rel='noopener noreferrer'>
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
                    <br/>             
                {% endfor %}
            {% endif %}

            {% if services != [] %}
            <hr>
            <h2 class="section-emphasis section-service">Services</h2>
            
            {% for service in services %}

                <a id="graph-service-{{ loop.index }}"></a>

                <p><h3> {{ service.get("@id", "").split('/')[-1] }}</h3></p>
                {% if service.get("http://purl.org/dc/elements/1.1/description") %}
                    <p><strong>Description:</strong> {{ service.get("http://purl.org/dc/elements/1.1/description", [{"@value":""}])[0]["@value"] }}</p>
                {% endif %}
                <p><strong>Type:</strong> 
                        <a href="{{ service.get("@type", ["Undefined"])[0] }}" target='_blank' rel='noopener noreferrer'>
                            {{ service.get("@type", ["Undefined"])[0].replace("https://kgrid.org/koio#","") }}
                        </a>
                </p>
                <p><strong>Depends on:</strong> 
                {% set depends = service.get("http://purl.obolibrary.org/obo/RO_0002502", [{}]) %}
                {% if depends is mapping %}
                    {% set depends = [depends] %}
                {% endif %}
                {% for dep in depends %}
                    {% set dep_anchor = dep.get("@id", "Undefined").split('/')[-1] %}
                    <a href="#{{ dep_anchor }}">{{ dep_anchor }}</a>{% if not loop.last %}, {% endif %}
                {% endfor %}
                </p>
                {% if service.get("http://www.ebi.ac.uk/swo/SWO_0004001") %}
                        <p><strong>Has interface:</strong> 
                            <a href="{{ service.get("http://www.ebi.ac.uk/swo/SWO_0004001", [{"@id":"Undefined"}])[0]["@id"] }}" target='_blank' rel='noopener noreferrer'>
                                {{ service.get("http://www.ebi.ac.uk/swo/SWO_0004001", [{"@value":"Undefined"}])[0]["@id"] | filename }}
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
                                <a href="{{ implementation.get("@id", "Undefined") }}" target='_blank' rel='noopener noreferrer'>
                                    {{ service.get("@id", "").replace("_:","")}}
                                </a>
                            {% else%}
                                <a href="{{ implementation.get("@id", "Undefined") }}" target='_blank' rel='noopener noreferrer'>
                                    {{ implementation.get("@id", "Undefined") | filename}}
                                </a>                                 
                            {% endif %}  <br/>(type: 
                                {% set imp_types = implementation.get("@type", "Undefined")%}
                                {% for imp_type in imp_types %}<a href="{{ imp_type }}" target='_blank' rel='noopener noreferrer'>{{ imp_type.replace("http://www.ebi.ac.uk/swo/SWO_0000118","Python").replace("http://www.ebi.ac.uk/swo/SWO_0000108","JavaScript").split("/")[-1].split("#")[-1]}}</a>{% if not loop.last %}, {% endif %}{% endfor %}) 
                            </li>
                        {% endfor %}      
                        </ul>            
                    </p>
                {% endif %}
                <br/>
            {% endfor %}
            {% endif %}
        </div>            
        </div>
        <div class="right-column">
            <div class="doc-section" id="doc-section">
            {% if documentation %}
                <h2 class="section-emphasis section-doc">Documentation</h2>
                <ul>
                {% for doc in documentation %}
                    <li>
                        {% set imp_types = doc.get('@type', '#')%}
                        {% if imp_types is string %}
                            {% set imp_types = [imp_types] %}
                        {% endif %}
                        <h3>
                        <a href="{{ doc.get('@id', '#') }}" target='_blank' rel='noopener noreferrer'>{{ doc.get('http://purl.org/dc/elements/1.1/title', [{"@value":"Untitled"}])[0]["@value"] }}</a>
                        <br/>
                        {% for imp_type in imp_types %}
                            {% if "Google Colab Notebook" in imp_type %}
                                <a href="https://colab.research.google.com/github/{{doc.get('@id', '#').replace("https://github.com/","") }}" target="_blank" rel="noopener noreferrer"> <img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open In Colab"> </a>
                            {% endif %}
                            {% if "Binder Notebook" in imp_type %}
                                <a href="{{ doc.get('@id', '') | binder_url('javascript') }}"
                                    target="_blank" rel="noopener noreferrer">
                                    <img src="https://mybinder.org/badge_logo.svg" alt="Binder">
                                </a>
                            {% endif %}
                            {% if "Scribbler Notebook" in imp_type %}
                                <a href="{{ doc.get('@id', '') | scribbler_url }}" target="_blank" rel="noopener noreferrer"> <img src="https://img.shields.io/badge/Open%20In-Scribbler-2F9E44?logo=javascript&logoColor=white" alt="Open In Scribbler"> </a>
                            {% endif %}
                        {% endfor %}

                        </h3>
                        <p>{{ doc.get('http://purl.org/dc/elements/1.1/description', [{"@value":"No description"}])[0]["@value"] }}</p>
                        {% if doc.get("item_of","")!="" %}
                            <p><strong>Document of:</strong> {{doc.get("item_of","")[0]["@value"]}} ({{ doc.get("type","") }}) </p>
                        {% endif %}
                        <p><strong>Type:</strong> 
                        
                        {% for imp_type in imp_types %}  
                                <a href="{{ imp_type }}" target='_blank' rel='noopener noreferrer'>
                                    {{ imp_type.replace("https://kgrid.org/koio#","").split("/")[-1].split("#")[-1]}}
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
                <h2 class="section-emphasis section-test">Tests</h2>
                <ul>
                {% for test in tests %}
                    <a id="graph-test-{{ loop.index }}"></a>
                    <li>
                        <h3><a href="{{ test.get('http://www.ebi.ac.uk/swo/SWO_0000085', [{}])[0].get('@id', '#') }}" target='_blank' rel='noopener noreferrer'>{{ test.get('http://purl.org/dc/elements/1.1/title', [{"@value":"Untitled"}])[0]["@value"] }}</a></h3>
                        <p>{{ test.get('http://purl.org/dc/elements/1.1/description', [{"@value":"No description"}])[0]["@value"] }}</p>
                        {% if test.get("item_of","")!="" %}
                            <p><strong>Test of:</strong> {{test.get("item_of","")[0]["@value"]}} ({{ test.get("type","") }}) </p>
                        {% endif %}
                        <p><strong>Type:</strong> 
                        {% set imp_types = test.get('http://www.ebi.ac.uk/swo/SWO_0000085', [{}])[0].get('@type', '#')%}
                        {% for imp_type in imp_types %}  
                                <a href="{{ imp_type }}" target='_blank' rel='noopener noreferrer'>
                                    {{ imp_type.replace("http://www.ebi.ac.uk/swo/SWO_0000118","Python").replace("http://www.ebi.ac.uk/swo/SWO_0000108","JavaScript").split("/")[-1].split("#")[-1]}}
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
        <script type="module">
            import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";

            const graphData = {{ graph_data_json | safe }};
            const graphPanel = document.getElementById("relationshipGraph");
            const graphTarget = document.getElementById("graphMermaid");
            const legendCheckboxes = document.querySelectorAll(".graph-legend input[type='checkbox']");
            const nodeTypeCheckboxes = document.querySelectorAll(".graph-legend input[data-node-type]");
            const edgeTypeCheckboxes = document.querySelectorAll(".graph-edge-legend input[data-edge-type]");

            const classDefs = [
                "classDef ko fill:#fff3cd,stroke:#b08900,stroke-width:2px,color:#4a3a00,font-weight:bold;",
                "classDef knowledge fill:#ffd9b3,stroke:#cc7a00,stroke-width:1.5px,color:#3b2200;",
                "classDef service fill:#cde8ff,stroke:#2d6ea3,stroke-width:1.5px,color:#0f2f4a;",
                "classDef test fill:#d6f5df,stroke:#2b8a3e,stroke-width:1.5px,color:#13361d;",
                "classDef doc fill:#efe0ff,stroke:#7a4ab3,stroke-width:1.5px,color:#301943;",
                "classDef empty fill:#f4f4f4,stroke:#9aa7b5,stroke-width:1px,color:#3b4b5a;"
            ];

            function buildGraphDefinition() {
                const activeTypes = new Set(
                    Array.from(nodeTypeCheckboxes)
                        .filter((box) => box.checked)
                        .map((box) => box.getAttribute("data-node-type"))
                );
                activeTypes.add("ko");

                const activeEdgeTypes = new Set(
                    Array.from(edgeTypeCheckboxes)
                        .filter((box) => box.checked)
                        .map((box) => box.getAttribute("data-edge-type"))
                );

                const visibleNodes = graphData.nodes.filter((node) => activeTypes.has(node.type));
                const visibleNodeIds = new Set(visibleNodes.map((node) => node.id));
                const visibleEdges = graphData.edges.filter(
                    (edge) =>
                        visibleNodeIds.has(edge.source) &&
                        visibleNodeIds.has(edge.target) &&
                        activeEdgeTypes.has(edge.type)
                );

                const lines = ["graph TB", ...classDefs];

                if (visibleNodes.length === 0) {
                    lines.push('EMPTY["No node types selected"]');
                    lines.push("class EMPTY empty;");
                    return lines.join("\\n");
                }

                for (const node of visibleNodes) {
                    lines.push(`${node.id}["${node.label}"]`);
                }

                for (const edge of visibleEdges) {
                    lines.push(`${edge.source} --> ${edge.target}`);
                }

                visibleEdges.forEach((edge, index) => {
                    if (edge.type === "depends") {
                        lines.push(`linkStyle ${index} stroke:#cc7a00,stroke-width:2.2px,stroke-dasharray: 6 4;`);
                    } else {
                        lines.push(`linkStyle ${index} stroke:#000000,stroke-width:2.2px;`);
                    }
                });

                for (const node of visibleNodes) {
                    lines.push(`class ${node.id} ${node.type};`);
                }

                return lines.join("\\n");
            }

            function wireGraphNodeLinks() {
                const svg = graphTarget.querySelector("svg");
                if (!svg) {
                    return;
                }

                for (const node of graphData.nodes) {
                    // Mermaid renders flowchart nodes with IDs like flowchart-N1-0.
                    const nodeElement = svg.querySelector(`g.node[id*="-${node.id}-"]`);
                    if (!nodeElement) {
                        continue;
                    }

                    const fullLabel = node.full_label || node.label;
                    const titleText = node.link ? `${fullLabel}\nOpen artifact` : fullLabel;
                    let titleEl = nodeElement.querySelector("title");
                    if (!titleEl) {
                        titleEl = document.createElementNS("http://www.w3.org/2000/svg", "title");
                        nodeElement.prepend(titleEl);
                    }
                    titleEl.textContent = titleText;

                    if (node.link) {
                        nodeElement.style.cursor = "pointer";
                        nodeElement.addEventListener("click", () => {
                            window.open(node.link, "_blank", "noopener,noreferrer");
                        });
                    }
                }
            }

            function fitGraphToContainer() {
                const svg = graphTarget.querySelector("svg");
                if (!svg) {
                    return;
                }

                const box = svg.viewBox && svg.viewBox.baseVal;
                const naturalWidth = box && box.width ? box.width : svg.getBBox().width;
                const naturalHeight = box && box.height ? box.height : svg.getBBox().height;
                if (!naturalWidth || !naturalHeight) {
                    return;
                }

                const styles = getComputedStyle(graphTarget);
                const maxHeight = parseFloat(styles.maxHeight) || naturalHeight;
                const paddingX = (parseFloat(styles.paddingLeft) || 0) + (parseFloat(styles.paddingRight) || 0);
                const paddingY = (parseFloat(styles.paddingTop) || 0) + (parseFloat(styles.paddingBottom) || 0);
                const availableWidth = Math.max(1, graphTarget.clientWidth - paddingX);
                const availableHeight = Math.max(1, maxHeight - paddingY);
                const innerMargin = 10;
                const widthScale = Math.max(0.01, (availableWidth - innerMargin * 2) / naturalWidth);
                const heightScale = Math.max(0.01, (availableHeight - innerMargin * 2) / naturalHeight);
                const scale = Math.min(1, widthScale, heightScale);

                svg.style.maxWidth = "none";
                svg.style.width = `${naturalWidth * scale}px`;
                svg.style.height = `${naturalHeight * scale}px`;
            }

            async function renderRelationshipGraph() {
                if (!graphPanel.open) {
                    return;
                }

                const definition = buildGraphDefinition();
                const renderId = `relationship-graph-${Date.now()}`;
                const { svg } = await mermaid.render(renderId, definition);
                graphTarget.innerHTML = svg;
                fitGraphToContainer();
                requestAnimationFrame(fitGraphToContainer);
                wireGraphNodeLinks();
            }

            mermaid.initialize({
                startOnLoad: false,
                theme: "neutral",
                securityLevel: "loose",
                flowchart: { curve: "catmullRom", nodeSpacing: 10, rankSpacing: 100, padding: 5, useMaxWidth: false }
            });

            graphPanel.addEventListener("toggle", () => {
                if (graphPanel.open) {
                    renderRelationshipGraph();
                }
            });

            for (const box of legendCheckboxes) {
                box.addEventListener("change", renderRelationshipGraph);
            }

            window.addEventListener("resize", () => {
                fitGraphToContainer();
            });

            if (graphPanel.open) {
                renderRelationshipGraph();
            }
        </script>
    </body>
    </html>
    """)

    
    documentation = find_item(metadata, "https://kgrid.org/koio#hasDocumentation", [],metadata.get("http://purl.org/dc/elements/1.1/title", ""), metadata.get("@type", [])[0].split('/')[-1])
    tests = find_item(metadata, "https://kgrid.org/koio#hasTest", [],metadata.get("http://purl.org/dc/elements/1.1/title", ""), metadata.get("@type", {"@value":[]})[0].split('/')[-1])
    knowledge_items = metadata.get("https://kgrid.org/koio#hasKnowledge", [])
    services = metadata.get("https://kgrid.org/koio#hasService", [])
    graph_link_base = os.path.dirname(base_iri) if base_iri and base_iri != "." else "."
    graph_data = build_relationship_graph(
        metadata, knowledge_items, services, tests, documentation, graph_link_base
    )
    graph_data_json = json.dumps(graph_data)
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
        graph_data_json=graph_data_json,
        graph_counts=graph_data.get("counts", {}),
        graph_edge_counts=graph_data.get("edge_counts", {}),
    )
    with open(output, "w") as f:
        f.write(html)

    print(f"\033[32m- Knowledge object information page created\033[0m at {output}")
    print_link_validation_report(html, output)


def expand_metadata(data, base_context):
    return jsonld.expand(data, base_context)[0]  # Return as-is if not a dict or list


def find_item(obj, key, results: list, title, obj_type, parent_ref=None):
    """Recursively find all items with the given key in a nested dictionary."""

    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                if isinstance(v, (list)):
                    for item in v:
                        item["item_of"] = title
                        item["type"] = obj_type
                        item["parent_ref"] = parent_ref
                        results.append(item)
                else:
                    v["item_of"] = title
                    v["type"] = obj_type
                    v["parent_ref"] = parent_ref
                    results.append(v)
            elif isinstance(v, (dict, list)):
                obj_type = get_object_types(obj)
                next_parent_ref = obj.get(
                    "@id",
                    _to_text(
                        obj.get(
                            "http://purl.org/dc/elements/1.1/title",
                            [{"@value": obj.get("@id", "").split('/')[-1]}],
                        ),
                        obj.get("@id", ""),
                    ),
                )
                results = find_item(v, key, results, obj.get("http://purl.org/dc/elements/1.1/title", [{"@value": obj.get("@id", "").split('/')[-1]}]), obj_type, next_parent_ref)
    elif isinstance(obj, list):
        for item in obj:
            if not isinstance(item, str):
                obj_type = get_object_types(item)
                next_parent_ref = item.get(
                    "@id",
                    _to_text(
                        item.get(
                            "http://purl.org/dc/elements/1.1/title",
                            [{"@value": item.get("@id", "").split('/')[-1]}],
                        ),
                        item.get("@id", ""),
                    ),
                )
                results = find_item(item, key, results, item.get("http://purl.org/dc/elements/1.1/title", [{"@value": item.get("@id", "").split('/')[-1]}]),  obj_type, next_parent_ref)
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
            normalized_relative_path = relative_path.replace("\\", "/")
            branch_url = f"{origin_url}/blob/{branch}/{normalized_relative_path}"
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

# information_page(
#     "/home/faridsei/dev/code/ICPSR-ex1-MIHD/metadata.json",
#     "/home/faridsei/dev/code/ICPSR-ex1-MIHD/index.html",
#     False,
# )

# information_page(
#     "/home/faridsei/dev/code/EWS-Score-Analyzer-For-Patients-With-Diabetes/metadata.json",
#     "/home/faridsei/dev/code/EWS-Score-Analyzer-For-Patients-With-Diabetes/index.html",
#     False,
# )

# information_page(
#     "/home/faridsei/dev/code/nephroticsyndrome-computablephenotype/metadata.json",
#     "/home/faridsei/dev/code/nephroticsyndrome-computablephenotype/index.html",
#     False,
# )
# information_page(
#     "/home/faridsei/dev/code/knowledge-base/prioritization_algorithms/random_candidate_selector/metadata.json",
#     "/home/faridsei/dev/code/knowledge-base/prioritization_algorithms/random_candidate_selector/index.html",
#     False,
# )
# information_page(
#     "/home/faridsei/dev/code/agent_experiments/template_filler1/filled_template.jsonld",
#     "/home/faridsei/dev/code/agent_experiments/template_filler1/index.html",
#     False,
# )
# information_page(
#     "C:/dev/FAIR-DO-Workshop/collection/wagner/metadata.json",
#     "C:/dev/FAIR-DO-Workshop/collection/wagner/index.html",
#     False
# )
# information_page(
#     "C:/dev/FAIR-DO-Workshop/collection/dfu-hbo2-treatment-decision/metadata.json",
#     "C:/dev/FAIR-DO-Workshop/collection/dfu-hbo2-treatment-decision/index.html",
#     False
# )
# information_page(
#     "C:/dev/FAIR-DO-Workshop/collection/dfu-hbot-bounded-regimen-and-execution-burden/metadata.json",
#     "C:/dev/FAIR-DO-Workshop/collection/dfu-hbot-bounded-regimen-and-execution-burden/index.html",
#     False
# )
# information_page(
#     "C:/dev/FAIR-DO-Workshop/collection/margolis-dfu-prognostic/metadata.json",
#     "C:/dev/FAIR-DO-Workshop/collection/margolis-dfu-prognostic/index.html",
#     False
# )

# init("test")

if __name__ == "__main__":
    cli()

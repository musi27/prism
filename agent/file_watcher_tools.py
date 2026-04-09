import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import prism

WATCH_PATH = os.path.join(os.path.dirname(__file__), "watched_files")

# Track files we've already processed
_seen_files: set[str] = set()


@prism.watch
def watch_folder(path: str) -> str:
    """Poll a folder for new files. Returns any new filenames found."""
    os.makedirs(path, exist_ok=True)
    current = set()
    for name in os.listdir(path):
        full = os.path.join(path, name)
        if os.path.isfile(full) and not name.endswith("_summary.txt"):
            current.add(name)
    new_files = sorted(current - _seen_files)
    _seen_files.update(current)
    return ", ".join(new_files) if new_files else ""


@prism.watch
def read_file(filepath: str) -> str:
    """Read the contents of a file."""
    with open(filepath) as f:
        content = f.read()
    # Truncate for cost
    if len(content) > 3000:
        content = content[:3000] + "\n\n[truncated]"
    return content


@prism.watch(skill="file_summary")
def write_summary(filepath: str, summary: str) -> str:
    """Write a summary file next to the original, named {original}_summary.txt."""
    base, ext = os.path.splitext(filepath)
    summary_path = f"{base}_summary.txt"
    with open(summary_path, "w") as f:
        f.write(summary)
    return f"Summary written to {summary_path}"


TOOLS_SCHEMA = [
    {
        "name": "watch_folder",
        "description": "Poll a folder for new files. Returns any new filenames found.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Folder path to watch"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "read_file",
        "description": "Read the contents of a file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "Path to the file to read"},
            },
            "required": ["filepath"],
        },
    },
    {
        "name": "write_summary",
        "description": "Write a summary file next to the original, named {original}_summary.txt.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "Path to the original file"},
                "summary": {"type": "string", "description": "The plain English summary text"},
            },
            "required": ["filepath", "summary"],
        },
    },
]

TOOL_MAP = {
    "watch_folder": watch_folder,
    "read_file": read_file,
    "write_summary": write_summary,
}

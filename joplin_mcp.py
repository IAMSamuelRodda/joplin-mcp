#!/usr/bin/env python3
"""
MCP Server for Joplin Notes.

This server provides tools to interact with the Joplin Data API,
including note management, notebooks, tags, and search.

Requirements:
    - Joplin desktop or CLI must be running with the Web Clipper service enabled
    - API runs on localhost:41184 by default

Environment variables:
    JOPLIN_TOKEN: (Required) API token from Joplin's Web Clipper settings
    JOPLIN_PORT: (Optional) API port, defaults to 41184
    JOPLIN_AUTO_LAUNCH: (Optional) Set to 'true' (default) to auto-launch Joplin
                        desktop if not running. Set to 'false' to disable.
                        On connection failure, will attempt to launch Joplin and
                        retry once after a 2 second wait.
"""

import asyncio
import json
import os
import shutil
import subprocess
import time
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv()  # Load .env file if present

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, field_validator

# Initialize the MCP server
mcp = FastMCP("joplin_mcp")

# Constants
DEFAULT_PORT = 41184
CHARACTER_LIMIT = 25000
AUTO_LAUNCH_ENABLED = os.environ.get("JOPLIN_AUTO_LAUNCH", "true").lower() == "true"
LAUNCH_WAIT_SECONDS = 2.0
MAX_LAUNCH_RETRIES = 1  # Only retry once to avoid masking other issues
ENSURE_RUNNING_TIMEOUT = 25.0  # Max seconds to wait for Joplin to become ready (AppImage can be slow)
ENSURE_RUNNING_POLL_INTERVAL = 1.0  # Seconds between API readiness checks


# =============================================================================
# Auto-Launch Utilities
# =============================================================================


def _is_joplin_running() -> bool:
    """Check if Joplin desktop is running."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "joplin"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _launch_joplin() -> bool:
    """
    Attempt to launch Joplin desktop application.

    Returns True if launch command was issued successfully.
    """
    # Try common Joplin executable locations
    home = os.path.expanduser("~")
    joplin_commands = [
        f"{home}/.joplin/Joplin.AppImage",  # Default AppImage location
        "joplin-desktop",  # Standard Linux package
        "joplin",  # Alternative name
        "/usr/bin/joplin-desktop",
        "/usr/bin/joplin",
        "/snap/bin/joplin-desktop",  # Snap package
        "/opt/Joplin/joplin",  # Manual AppImage install
    ]

    # Also check for flatpak
    flatpak_cmd = ["flatpak", "run", "net.cozic.joplin_desktop"]

    # Build environment with DISPLAY for GUI apps on Linux
    env = os.environ.copy()
    if "DISPLAY" not in env:
        env["DISPLAY"] = ":0"  # Default X11 display
    # Also set WAYLAND_DISPLAY if available for Wayland systems
    if "WAYLAND_DISPLAY" not in env and os.path.exists("/run/user/1000/wayland-0"):
        env["WAYLAND_DISPLAY"] = "wayland-0"

    for cmd in joplin_commands:
        if shutil.which(cmd) or os.path.isfile(cmd):
            try:
                subprocess.Popen(
                    [cmd],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                    env=env,
                )
                return True
            except Exception:
                continue

    # Try flatpak as fallback
    if shutil.which("flatpak"):
        try:
            subprocess.Popen(
                flatpak_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env=env,
            )
            return True
        except Exception:
            pass

    return False


async def _wait_for_joplin_api_ready(timeout: float = ENSURE_RUNNING_TIMEOUT) -> bool:
    """
    Poll until Joplin API is responsive.

    Args:
        timeout: Maximum seconds to wait for API readiness.

    Returns:
        True if API became ready, False if timeout exceeded.
    """
    port = os.environ.get("JOPLIN_PORT", DEFAULT_PORT)
    token = os.environ.get("JOPLIN_TOKEN", "")
    base_url = f"http://localhost:{port}"

    start = time.time()
    while time.time() - start < timeout:
        try:
            async with httpx.AsyncClient() as client:
                # Use /ping endpoint to check API readiness
                resp = await client.get(
                    f"{base_url}/ping",
                    params={"token": token},
                    timeout=2.0,
                )
                if resp.status_code == 200:
                    return True
        except (httpx.ConnectError, httpx.ConnectTimeout):
            pass
        await asyncio.sleep(ENSURE_RUNNING_POLL_INTERVAL)
    return False


# =============================================================================
# Enums
# =============================================================================


class ResponseFormat(str, Enum):
    """Output format for tool responses."""

    MARKDOWN = "markdown"
    JSON = "json"


class NotesSortField(str, Enum):
    """Fields to sort notes by."""

    UPDATED_TIME = "updated_time"
    CREATED_TIME = "created_time"
    TITLE = "title"
    ORDER = "order"


# =============================================================================
# Pydantic Input Models
# =============================================================================


class ListNotebooksInput(BaseModel):
    """Input model for listing notebooks."""

    model_config = ConfigDict(str_strip_whitespace=True)

    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format: 'markdown' or 'json'",
    )


class ListNotesInput(BaseModel):
    """Input model for listing notes."""

    model_config = ConfigDict(str_strip_whitespace=True)

    notebook_id: Optional[str] = Field(
        default=None,
        description="Filter by notebook ID. If not set, lists all notes.",
    )
    limit: int = Field(
        default=50, description="Maximum notes to return", ge=1, le=100
    )
    order_by: NotesSortField = Field(
        default=NotesSortField.UPDATED_TIME,
        description="Field to sort by",
    )
    order_desc: bool = Field(
        default=True, description="Sort descending (newest first)"
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format: 'markdown' or 'json'",
    )


class GetNoteInput(BaseModel):
    """Input model for getting a single note."""

    model_config = ConfigDict(str_strip_whitespace=True)

    note_id: str = Field(
        ..., description="The note ID", min_length=1
    )
    include_body: bool = Field(
        default=True, description="Include the full note body/content"
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format: 'markdown' or 'json'",
    )


class CreateNoteInput(BaseModel):
    """Input model for creating a note."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(
        ...,
        description="Note title",
        min_length=1,
        max_length=500,
    )
    body: str = Field(
        default="",
        description="Note content in Markdown format",
        max_length=100000,
    )
    notebook_id: Optional[str] = Field(
        default=None,
        description="Notebook ID to create note in. Uses default notebook if not specified.",
    )
    tags: Optional[list[str]] = Field(
        default=None,
        description="List of tag names to apply (will be created if they don't exist)",
    )
    is_todo: bool = Field(
        default=False,
        description="Create as a to-do item instead of a regular note",
    )


class UpdateNoteInput(BaseModel):
    """Input model for updating a note."""

    model_config = ConfigDict(str_strip_whitespace=True)

    note_id: str = Field(..., description="The note ID to update", min_length=1)
    title: Optional[str] = Field(
        default=None,
        description="New note title",
        max_length=500,
    )
    body: Optional[str] = Field(
        default=None,
        description="New note content in Markdown",
        max_length=100000,
    )
    notebook_id: Optional[str] = Field(
        default=None,
        description="Move note to different notebook",
    )
    is_todo: Optional[bool] = Field(
        default=None,
        description="Convert to/from to-do item",
    )
    todo_completed: Optional[bool] = Field(
        default=None,
        description="Mark to-do as completed/incomplete",
    )


class DeleteNoteInput(BaseModel):
    """Input model for deleting a note."""

    model_config = ConfigDict(str_strip_whitespace=True)

    note_id: str = Field(..., description="The note ID to delete", min_length=1)


class SearchNotesInput(BaseModel):
    """Input model for searching notes."""

    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(
        ...,
        description="Search query. Supports: title:, body:, tag:, notebook:, created:, updated:, type: prefixes",
        min_length=1,
        max_length=500,
    )
    limit: int = Field(
        default=20, description="Maximum results to return", ge=1, le=100
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format: 'markdown' or 'json'",
    )


class ListTagsInput(BaseModel):
    """Input model for listing tags."""

    model_config = ConfigDict(str_strip_whitespace=True)

    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format: 'markdown' or 'json'",
    )


class CreateNotebookInput(BaseModel):
    """Input model for creating a notebook."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(
        ...,
        description="Notebook title",
        min_length=1,
        max_length=200,
    )
    parent_id: Optional[str] = Field(
        default=None,
        description="Parent notebook ID for creating a sub-notebook",
    )


class TagNoteInput(BaseModel):
    """Input model for adding a tag to a note."""

    model_config = ConfigDict(str_strip_whitespace=True)

    note_id: str = Field(..., description="The note ID to tag", min_length=1)
    tag: str = Field(
        ...,
        description="Tag name to add (will be created if it doesn't exist)",
        min_length=1,
        max_length=100,
    )


# =============================================================================
# Shared Utilities
# =============================================================================


def _get_api_config() -> tuple[str, str]:
    """Get API base URL and token."""
    token = os.environ.get("JOPLIN_TOKEN")
    if not token:
        raise ValueError(
            "JOPLIN_TOKEN environment variable not set. "
            "Get your token from: Joplin → Tools → Options → Web Clipper"
        )

    port = os.environ.get("JOPLIN_PORT", DEFAULT_PORT)
    base_url = f"http://localhost:{port}"

    return base_url, token


async def _make_api_request(
    endpoint: str,
    method: str = "GET",
    json_data: Optional[dict] = None,
    params: Optional[dict] = None,
    _retry_count: int = 0,
) -> dict | list | None:
    """Make request to Joplin API with auto-launch retry."""
    base_url, token = _get_api_config()

    # Add token to params
    if params is None:
        params = {}
    params["token"] = token

    try:
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method,
                f"{base_url}/{endpoint}",
                json=json_data,
                params=params,
                timeout=30.0,
            )
            response.raise_for_status()

            if response.status_code == 204 or not response.content:
                return None
            return response.json()

    except (httpx.ConnectError, httpx.ConnectTimeout) as e:
        # Auto-launch logic: only retry once
        if AUTO_LAUNCH_ENABLED and _retry_count < MAX_LAUNCH_RETRIES:
            if not _is_joplin_running():
                launched = _launch_joplin()
                if launched:
                    # Wait for Joplin to start and enable Web Clipper
                    await asyncio.sleep(LAUNCH_WAIT_SECONDS)
                    # Retry the request once
                    return await _make_api_request(
                        endpoint,
                        method,
                        json_data,
                        params,
                        _retry_count=_retry_count + 1,
                    )
        # Re-raise if auto-launch disabled, already retried, or launch failed
        raise


async def _get_all_paginated(
    endpoint: str,
    params: Optional[dict] = None,
    limit: int = 100,
) -> list:
    """Fetch all items with pagination."""
    if params is None:
        params = {}

    items = []
    page = 1

    while True:
        params["page"] = page
        params["limit"] = min(limit, 100)

        result = await _make_api_request(endpoint, params=params)

        if isinstance(result, dict) and "items" in result:
            items.extend(result["items"])
            if not result.get("has_more", False):
                break
        elif isinstance(result, list):
            items.extend(result)
            if len(result) < params["limit"]:
                break
        else:
            break

        page += 1

        # Safety limit
        if page > 50:
            break

    return items[:limit] if limit else items


def _handle_error(e: Exception) -> str:
    """Format errors with actionable messages."""
    error_str = str(e).lower()

    if "connection refused" in error_str or "connect" in error_str:
        auto_launch_note = ""
        if AUTO_LAUNCH_ENABLED:
            auto_launch_note = "\n\nNote: Auto-launch was attempted but Joplin may not have started in time."
        else:
            auto_launch_note = "\n\nTip: Set JOPLIN_AUTO_LAUNCH=true to auto-start Joplin."

        return (
            "Error: Cannot connect to Joplin. Make sure:\n"
            "1. Joplin desktop is running\n"
            "2. Web Clipper service is enabled (Tools → Options → Web Clipper)\n"
            f"3. The API port matches JOPLIN_PORT (default: 41184){auto_launch_note}"
        )
    elif "401" in error_str or "unauthorized" in error_str or "forbidden" in error_str:
        return "Error: Invalid API token. Check JOPLIN_TOKEN is correct."
    elif "404" in error_str:
        return "Error: Resource not found. Check the ID is correct."
    elif "timeout" in error_str:
        return "Error: Request timed out. Joplin may be busy or unresponsive."

    return f"Error: {type(e).__name__}: {str(e)}"


def _format_timestamp(ts: Optional[int]) -> str:
    """Format Unix timestamp (ms) to readable string."""
    if not ts:
        return "Unknown"
    try:
        dt = datetime.fromtimestamp(ts / 1000)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts)


def _truncate_response(result: str, item_count: int) -> str:
    """Truncate response if it exceeds character limit."""
    if len(result) > CHARACTER_LIMIT:
        truncated = result[: CHARACTER_LIMIT - 200]
        truncated += f"\n\n---\n**Response truncated** ({item_count} items). Use filters to narrow results."
        return truncated
    return result


# =============================================================================
# System Tools
# =============================================================================


@mcp.tool(
    name="joplin_ensure_running",
    annotations={
        "title": "Ensure Joplin is Running",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def joplin_ensure_running() -> str:
    """
    Ensure API ready. Launches Joplin if needed, waits for connection.

    Use proactively before batch operations to avoid cold-start delays.
    Returns immediately if already running. Useful for session pre-warming.

    Returns:
        Status message: 'already_running', 'launched', or error details.
    """
    # Check if already running and API responsive
    if _is_joplin_running():
        # Verify API is actually ready (Web Clipper enabled)
        if await _wait_for_joplin_api_ready(timeout=2.0):
            return "✅ Joplin is already running and API is ready."

    # Not running or API not ready - attempt launch
    if not AUTO_LAUNCH_ENABLED:
        return (
            "❌ Joplin is not running and auto-launch is disabled. "
            "Please start Joplin manually and enable Web Clipper."
        )

    launched = _launch_joplin()
    if not launched:
        return (
            "❌ Failed to launch Joplin. Could not find Joplin executable. "
            "Please start Joplin manually."
        )

    # Wait for API to become ready
    if await _wait_for_joplin_api_ready():
        return "✅ Joplin launched successfully and API is ready."

    return (
        "⚠️ Joplin was launched but API did not become ready within "
        f"{ENSURE_RUNNING_TIMEOUT} seconds. Please check that Web Clipper "
        "is enabled in Joplin (Tools → Options → Web Clipper)."
    )


# =============================================================================
# Notebook Tools
# =============================================================================


@mcp.tool(
    name="joplin_list_notebooks",
    annotations={
        "title": "List Joplin Notebooks",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def joplin_list_notebooks(params: ListNotebooksInput) -> str:
    """
    List notebooks with IDs and hierarchy. Use to find notebook_id for filtering.

    Returns tree structure showing parent/child relationships.
    Always list notebooks first before creating new ones to avoid duplicates.

    Args:
        params: ListNotebooksInput containing:
            - response_format: 'markdown' or 'json'

    Returns:
        List of notebooks with their IDs and structure.
    """
    try:
        notebooks = await _get_all_paginated(
            "folders",
            params={"fields": "id,title,parent_id"},
        )

        if not notebooks:
            return "No notebooks found."

        if params.response_format == ResponseFormat.JSON:
            return json.dumps(notebooks, indent=2)

        # Build tree structure for markdown
        def build_tree(parent_id: str = "", level: int = 0) -> list[str]:
            lines = []
            for nb in notebooks:
                if nb.get("parent_id", "") == parent_id:
                    indent = "  " * level
                    lines.append(f"{indent}- **{nb['title']}**")
                    lines.append(f"{indent}  ID: `{nb['id']}`")
                    lines.extend(build_tree(nb["id"], level + 1))
            return lines

        lines = ["# Joplin Notebooks", ""]
        lines.extend(build_tree())

        return "\n".join(lines)

    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="joplin_create_notebook",
    annotations={
        "title": "Create Joplin Notebook",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def joplin_create_notebook(params: CreateNotebookInput) -> str:
    """
    Create notebook or return existing. Checks for duplicates by title first.

    ⚠️ IMPORTANT: Always searches for existing notebook with same title before
    creating. Returns existing notebook ID if found to prevent duplicates.

    Args:
        params: CreateNotebookInput containing:
            - title: Notebook name
            - parent_id: Optional parent notebook for sub-notebook

    Returns:
        Notebook details with ID (existing or newly created).
    """
    try:
        # First, check if notebook with same title already exists
        existing_notebooks = await _get_all_paginated(
            "folders",
            params={"fields": "id,title,parent_id"},
        )

        # Search for exact title match (case-insensitive) at the same parent level
        target_parent = params.parent_id or ""
        for nb in existing_notebooks:
            nb_parent = nb.get("parent_id", "") or ""
            if (nb.get("title", "").lower() == params.title.lower()
                    and nb_parent == target_parent):
                return (
                    f"📁 Notebook **{nb['title']}** already exists "
                    f"(ID: `{nb['id']}`). Using existing notebook."
                )

        # No duplicate found, create new notebook
        data: dict[str, Any] = {"title": params.title}
        if params.parent_id:
            data["parent_id"] = params.parent_id

        notebook = await _make_api_request("folders", method="POST", json_data=data)

        return f"✅ Created notebook **{notebook['title']}** (ID: `{notebook['id']}`)"

    except Exception as e:
        return _handle_error(e)


# =============================================================================
# Note Tools
# =============================================================================


@mcp.tool(
    name="joplin_list_notes",
    annotations={
        "title": "List Joplin Notes",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def joplin_list_notes(params: ListNotesInput) -> str:
    """
    List notes with IDs, titles, dates. Filter by notebook_id, sort by date/title.

    Returns note metadata (not content). Use get_note for full content.
    Supports to-do status indicators in output.

    Args:
        params: ListNotesInput containing:
            - notebook_id: Filter by notebook (optional)
            - limit: Maximum notes to return (default 50)
            - order_by: Sort field (updated_time, created_time, title)
            - order_desc: Sort descending (default true)
            - response_format: 'markdown' or 'json'

    Returns:
        List of notes with titles, dates, and IDs.
    """
    try:
        request_params = {
            "fields": "id,title,parent_id,updated_time,created_time,is_todo,todo_completed",
            "order_by": params.order_by.value,
            "order_dir": "DESC" if params.order_desc else "ASC",
        }

        if params.notebook_id:
            endpoint = f"folders/{params.notebook_id}/notes"
        else:
            endpoint = "notes"

        notes = await _get_all_paginated(endpoint, params=request_params, limit=params.limit)

        if not notes:
            return "No notes found."

        if params.response_format == ResponseFormat.JSON:
            return json.dumps(notes, indent=2)

        # Markdown format
        lines = ["# Joplin Notes", f"*Showing {len(notes)} notes*", ""]

        for note in notes:
            # Todo indicator
            if note.get("is_todo"):
                status = "✅" if note.get("todo_completed") else "⬜"
                lines.append(f"### {status} {note['title']}")
            else:
                lines.append(f"### {note['title']}")

            lines.append(f"- **ID**: `{note['id']}`")
            lines.append(f"- **Updated**: {_format_timestamp(note.get('updated_time'))}")
            lines.append("")

        return _truncate_response("\n".join(lines), len(notes))

    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="joplin_get_note",
    annotations={
        "title": "Get Joplin Note",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def joplin_get_note(params: GetNoteInput) -> str:
    """
    Get note by ID with full Markdown content. Includes metadata and body.

    Use after list_notes or search_notes to retrieve full content.
    Set include_body=false for metadata only.

    Args:
        params: GetNoteInput containing:
            - note_id: The note ID (required)
            - include_body: Include full content (default true)
            - response_format: 'markdown' or 'json'

    Returns:
        Note details including content if requested.
    """
    try:
        fields = "id,title,parent_id,updated_time,created_time,is_todo,todo_completed,source_url"
        if params.include_body:
            fields += ",body"

        note = await _make_api_request(
            f"notes/{params.note_id}",
            params={"fields": fields},
        )

        if params.response_format == ResponseFormat.JSON:
            return json.dumps(note, indent=2)

        # Markdown format
        lines = [f"# {note['title']}", ""]

        if note.get("is_todo"):
            status = "Completed ✅" if note.get("todo_completed") else "Pending ⬜"
            lines.append(f"**Status**: {status}")

        lines.extend([
            f"- **ID**: `{note['id']}`",
            f"- **Notebook**: `{note.get('parent_id', 'Unknown')}`",
            f"- **Created**: {_format_timestamp(note.get('created_time'))}",
            f"- **Updated**: {_format_timestamp(note.get('updated_time'))}",
        ])

        if note.get("source_url"):
            lines.append(f"- **Source**: {note['source_url']}")

        if params.include_body and note.get("body"):
            lines.extend(["", "---", "", note["body"]])

        return "\n".join(lines)

    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="joplin_create_note",
    annotations={
        "title": "Create Joplin Note",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def joplin_create_note(params: CreateNoteInput) -> str:
    """
    Create note with Markdown body, optional tags, to-do support.

    Specify notebook_id to target specific notebook (list notebooks first).
    Tags are created automatically if they don't exist.

    Args:
        params: CreateNoteInput containing:
            - title: Note title (required)
            - body: Markdown content (default empty)
            - notebook_id: Target notebook ID (uses default if not set)
            - tags: List of tag names (auto-created if needed)
            - is_todo: Create as to-do item (default false)

    Returns:
        Created note details with ID.
    """
    try:
        data: dict[str, Any] = {
            "title": params.title,
            "body": params.body,
        }

        if params.notebook_id:
            data["parent_id"] = params.notebook_id
        if params.is_todo:
            data["is_todo"] = 1

        note = await _make_api_request("notes", method="POST", json_data=data)

        # Add tags if specified
        if params.tags:
            for tag_name in params.tags:
                try:
                    # Search for existing tag
                    tags = await _make_api_request(
                        "search",
                        params={"query": tag_name, "type": "tag"},
                    )

                    tag_id = None
                    if isinstance(tags, dict) and tags.get("items"):
                        for t in tags["items"]:
                            if t.get("title", "").lower() == tag_name.lower():
                                tag_id = t["id"]
                                break

                    # Create tag if not found
                    if not tag_id:
                        new_tag = await _make_api_request(
                            "tags",
                            method="POST",
                            json_data={"title": tag_name},
                        )
                        tag_id = new_tag["id"]

                    # Add tag to note
                    await _make_api_request(
                        f"tags/{tag_id}/notes",
                        method="POST",
                        json_data={"id": note["id"]},
                    )
                except Exception:
                    pass  # Continue even if tagging fails

        note_type = "to-do" if params.is_todo else "note"
        return f"✅ Created {note_type} **{note['title']}** (ID: `{note['id']}`)"

    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="joplin_update_note",
    annotations={
        "title": "Update Joplin Note",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def joplin_update_note(params: UpdateNoteInput) -> str:
    """
    Update note title, body, or move to different notebook. Partial updates OK.

    Only provided fields are changed. Can convert to/from to-do,
    mark complete, or move between notebooks.

    Args:
        params: UpdateNoteInput containing:
            - note_id: The note ID to update (required)
            - title: New title (optional)
            - body: New Markdown content (optional)
            - notebook_id: Move to different notebook (optional)
            - is_todo: Convert to/from to-do (optional)
            - todo_completed: Mark to-do complete (optional)

    Returns:
        Confirmation that the note was updated.
    """
    try:
        data: dict[str, Any] = {}

        if params.title is not None:
            data["title"] = params.title
        if params.body is not None:
            data["body"] = params.body
        if params.notebook_id is not None:
            data["parent_id"] = params.notebook_id
        if params.is_todo is not None:
            data["is_todo"] = 1 if params.is_todo else 0
        if params.todo_completed is not None:
            data["todo_completed"] = int(datetime.now().timestamp() * 1000) if params.todo_completed else 0

        if not data:
            return "Error: No fields to update. Provide at least one field to change."

        note = await _make_api_request(
            f"notes/{params.note_id}",
            method="PUT",
            json_data=data,
        )

        title = params.title or note.get("title", "Note")
        return f"✅ Updated note **{title}** (ID: `{params.note_id}`)"

    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="joplin_delete_note",
    annotations={
        "title": "Delete Joplin Note",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def joplin_delete_note(params: DeleteNoteInput) -> str:
    """
    ⚠️ Delete note permanently. Cannot be undone.

    Args:
        params: DeleteNoteInput containing:
            - note_id: The note ID to delete (required)

    Returns:
        Confirmation that the note was deleted.
    """
    try:
        await _make_api_request(f"notes/{params.note_id}", method="DELETE")
        return f"🗑️ Deleted note (ID: `{params.note_id}`)"

    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="joplin_search_notes",
    annotations={
        "title": "Search Joplin Notes",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def joplin_search_notes(params: SearchNotesInput) -> str:
    """
    Search notes. Supports title:, body:, tag:, notebook:, type: prefixes.

    Examples: "tag:work type:todo", "title:meeting", "notebook:Projects".
    Also supports created:, updated: date filters and iscompleted:1/0.

    Args:
        params: SearchNotesInput containing:
            - query: Search query with optional prefixes
            - limit: Maximum results (default 20)
            - response_format: 'markdown' or 'json'

    Returns:
        Matching notes with their details.
    """
    try:
        result = await _make_api_request(
            "search",
            params={
                "query": params.query,
                "type": "note",
                "fields": "id,title,parent_id,updated_time,is_todo,todo_completed",
                "limit": params.limit,
            },
        )

        items = result.get("items", []) if isinstance(result, dict) else result

        if not items:
            return f"No notes found matching '{params.query}'."

        if params.response_format == ResponseFormat.JSON:
            return json.dumps(items, indent=2)

        # Markdown format
        lines = [
            f"# Search Results: '{params.query}'",
            f"*Found {len(items)} notes*",
            "",
        ]

        for note in items:
            if note.get("is_todo"):
                status = "✅" if note.get("todo_completed") else "⬜"
                lines.append(f"### {status} {note['title']}")
            else:
                lines.append(f"### {note['title']}")

            lines.append(f"- **ID**: `{note['id']}`")
            lines.append(f"- **Updated**: {_format_timestamp(note.get('updated_time'))}")
            lines.append("")

        return _truncate_response("\n".join(lines), len(items))

    except Exception as e:
        return _handle_error(e)


# =============================================================================
# Tag Tools
# =============================================================================


@mcp.tool(
    name="joplin_list_tags",
    annotations={
        "title": "List Joplin Tags",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def joplin_list_tags(params: ListTagsInput) -> str:
    """
    List all tags with IDs. Use for tag: search prefix or tag_note operations.

    Returns alphabetically sorted list. Tags are reusable across notes.

    Args:
        params: ListTagsInput containing:
            - response_format: 'markdown' or 'json'

    Returns:
        List of tags with IDs.
    """
    try:
        tags = await _get_all_paginated(
            "tags",
            params={"fields": "id,title"},
        )

        if not tags:
            return "No tags found."

        if params.response_format == ResponseFormat.JSON:
            return json.dumps(tags, indent=2)

        # Markdown format
        lines = ["# Joplin Tags", ""]
        for tag in sorted(tags, key=lambda t: t.get("title", "").lower()):
            lines.append(f"- **{tag['title']}** (ID: `{tag['id']}`)")

        return "\n".join(lines)

    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="joplin_tag_note",
    annotations={
        "title": "Tag Joplin Note",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def joplin_tag_note(params: TagNoteInput) -> str:
    """
    Add tag to note. Creates tag automatically if it doesn't exist.

    Idempotent: adding existing tag has no effect. Case-insensitive matching.

    Args:
        params: TagNoteInput containing:
            - note_id: The note ID to tag (required)
            - tag: Tag name to add (auto-created if needed)

    Returns:
        Confirmation that the tag was added.
    """
    try:
        # Search for existing tag
        tags = await _make_api_request(
            "search",
            params={"query": params.tag, "type": "tag"},
        )

        tag_id = None
        if isinstance(tags, dict) and tags.get("items"):
            for t in tags["items"]:
                if t.get("title", "").lower() == params.tag.lower():
                    tag_id = t["id"]
                    break

        # Create tag if not found
        if not tag_id:
            new_tag = await _make_api_request(
                "tags",
                method="POST",
                json_data={"title": params.tag},
            )
            tag_id = new_tag["id"]

        # Add tag to note
        await _make_api_request(
            f"tags/{tag_id}/notes",
            method="POST",
            json_data={"id": params.note_id},
        )

        return f"✅ Added tag **{params.tag}** to note `{params.note_id}`"

    except Exception as e:
        return _handle_error(e)


# =============================================================================
# Main Entry Point
# =============================================================================


if __name__ == "__main__":
    mcp.run()

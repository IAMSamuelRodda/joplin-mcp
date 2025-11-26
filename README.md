# Joplin MCP Server

MCP (Model Context Protocol) server for Joplin Notes integration, allowing AI assistants to manage your notes, notebooks, and tags.

## Features

- **Notes**: List, create, update, search, and delete notes
- **Notebooks**: List and create notebooks (folders)
- **Tags**: List tags and tag notes
- **Search**: Full Joplin search syntax support
- **To-dos**: Create and manage to-do items

## Prerequisites

- **Joplin desktop app** must be running
- **Web Clipper service** must be enabled

## Setup

### 1. Enable Web Clipper in Joplin

1. Open Joplin desktop
2. Go to **Tools** → **Options** → **Web Clipper**
3. Click **Enable Web Clipper Service**
4. Copy the **Authorization token**

### 2. Install Dependencies

```bash
cd repos/joplin-mcp
uv venv .venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

### 3. Configure Claude Code

Add to your Claude Code MCP settings (`~/.claude/mcp_settings.json`):

```json
{
  "mcpServers": {
    "joplin": {
      "command": "/home/samuel/repos/joplin-mcp/.venv/bin/python",
      "args": ["/home/samuel/repos/joplin-mcp/joplin_mcp.py"],
      "env": {
        "JOPLIN_TOKEN": "your-api-token-here"
      }
    }
  }
}
```

## Available Tools

| Tool | Description |
|------|-------------|
| `joplin_list_notebooks` | List all notebooks |
| `joplin_create_notebook` | Create a new notebook |
| `joplin_list_notes` | List notes (filterable by notebook) |
| `joplin_get_note` | Get full note content |
| `joplin_create_note` | Create a new note |
| `joplin_update_note` | Update existing note |
| `joplin_delete_note` | Delete a note |
| `joplin_search_notes` | Search notes |
| `joplin_list_tags` | List all tags |
| `joplin_tag_note` | Add tag to note |

## Usage Examples

Once configured, you can ask Claude:

- "Show me my Joplin notebooks"
- "List my recent notes"
- "Create a note called 'Meeting Notes' in my Work notebook"
- "Search for notes about 'project plan'"
- "What notes are tagged with 'important'?"

## Search Syntax

The `joplin_search_notes` tool supports Joplin's query syntax:

- `title:meeting` - Search in title
- `body:action items` - Search in body
- `tag:work` - Filter by tag
- `notebook:Projects` - Filter by notebook
- `type:todo` - Only to-dos
- `iscompleted:0` - Incomplete to-dos
- `created:20240101` - Created after date
- `updated:20240101` - Updated after date

Combine: `tag:work type:todo iscompleted:0` finds incomplete work todos.

## Note

Joplin desktop must be running for the MCP server to work. The API connects to localhost:41184 (the Web Clipper service).

## License

MIT

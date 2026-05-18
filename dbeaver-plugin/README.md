# PlainDB DBeaver Plugin

This is the DBeaver integration layer for **PlainDB** – a database-agnostic safety pipeline for executing AI-generated SQL with multiple verification layers.

## What it does

### Main Capabilities
- **Verify SQL Intent** - Convert natural English requests into SQL queries
- **Backend-only architecture** - Calls PlainDB backend `/run` for verification, execution, and commit control
- **Database Support** - PostgreSQL, MySQL, SQLite, Oracle, SQL Server, etc.
- **Rollback Integration** - Uses backend rollback IDs (`/rollback/{rollback_id}`)
- **English Validation** - Ensures requests are in English only

### Architecture

The plugin is a **thin client** that:
1. Takes natural language SQL requests from users
2. Calls the PlainDB backend `/run`
3. Displays generated SQL and result status in DBeaver
4. Supports backend rollback actions when rollback IDs are returned

```
DBeaver Plugin
    ↓
Verify Request Dialog
    ↓
SqlGeneratorClient (Java)
    ↓ (HTTP)
Backend `/run`
    ↓
PlainDB Pipeline
    ↓
Database Adapter
    ↓
Execute SQL
```

## How to use it in DBeaver

### Initial Setup

Once installed and DBeaver is restarted:

1. **Open DBeaver**
2. **Run the command:**
   - Menu: **PlainDB → Verify database request**
   - Or search for "PlainDB" in command palette (Ctrl/Cmd+Shift+P)
3. **Configure Account (one-time):**
   - Click **Account** tab
   - **API Key**: Paste your Gemini API key (passed through to backend)
   - **Backend URL**: `http://localhost:8000` or remote URL
   - Click **Save**

### Verification Dialog

Once configured, the **Verify Request** dialog shows:

**Input Section:**
- **Database**: Select target database system
- **Request**: Write your SQL operation in English (e.g., "Show users older than 25")

**Output Section:**
- **Generated SQL**: The SQL candidate returned by backend pipeline
- **Verification Results**: Pass/fail stages (semantic, safety, effect, post-commit)
- **Execution Status**: Success/error with row count

**Buttons:**
- **Load Database**: Refresh connected database metadata
- **Generate SQL**: Run verification pipeline
- **Copy SQL**: Copy result to clipboard
- **Execute**: (future) Execute SQL in connected database

### Example Workflows

#### 1. Using PlainDB Backend

```
1. Account Tab:
   - Provider: "PlainDB (Backend)"
   - Backend URL: "http://localhost:8000"
   - Save

2. Verify Request Tab:
   - Database: "PostgreSQL"
   - Request: "Show all active users from 2024"
   - Click "Generate SQL"

3. Results:
   Output includes generated SQL, commit status, and optional rollback ID for mutating SQL.
```

### Configuration

#### Account Tab Settings

| Field | Usage | Notes |
|-------|-------|-------|
| **Backend URL** | Backend endpoint for all requests | Required; plugin calls backend `/run` and rollback endpoints |
| **LLM Model** | Model passed to backend | Default: `gemini-2.5-flash` |
| **API Key** | Authentication for provider used by backend | Required for backend requests that invoke Gemini |

#### Backend Configuration

**Local Backend:**
```bash
# Terminal 1: Start backend
cd backend
python -m uvicorn api.main:app --reload

# Terminal 2: Use in DBeaver
# Account Tab: Backend URL = http://localhost:8000
```

**Docker Backend:**
```bash
docker-compose up -d
# Backend at: http://localhost:8000
```

**Remote Backend:**
```
# Deploy to server
# Account Tab: Backend URL = https://your-server.com:8000
```

For detailed feature documentation, see [../FEATURES.md](../FEATURES.md)

## Installation Methods

### Method 1: Direct Install (Quickest)

For development and testing, install directly into your DBeaver application:

```bash
cd /path/to/plainDB
bash scripts/run-local-dbeaver.sh
```

This script:
1. Compiles the plugin from source
2. Installs it into `/Applications/DBeaver.app/Contents/Eclipse/plugins`
3. Quits and relaunches DBeaver

**Requirements:**
- DBeaver 26+ installed at `/Applications/DBeaver.app`
- Java 21 (via Homebrew: `/opt/homebrew/opt/openjdk@21/`)

**After restart:**
- Open any database connection and SQL editor
- Look for the **PlainDB** menu or "Verify database request" command

### Method 2: Local Update Site (User-Friendly)

For software installer–style installation through DBeaver's UI:

```bash
cd /path/to/plainDB
bash scripts/build-update-site.sh
```

This creates a local p2 update site in `update-site/`.

**Then in DBeaver:**

1. Go to **Help → Install New Software...**
2. Click **Add** and enter:
   - **Name:** `PlainDB Local`
   - **Location:** `file:///path/to/plainDB/update-site`
3. Select **PlainDB** from the category list
4. Click **Next → Finish**
5. Restart DBeaver

This method allows users unfamiliar with file system paths to install the plugin through DBeaver's standard UI.

For detailed update site documentation, see [update-site/README.md](../update-site/README.md)

### Configuration

If DBeaver is installed elsewhere, set the environment variable:

```bash
export DBEAVER_APP="/path/to/DBeaver.app"
bash scripts/run-local-dbeaver.sh
```

## User-facing rules

- All prompts, labels, errors, and status messages must be English only.
- SQL text must remain hidden from the user experience.
- The user should see intent, approval status, and high-level outcomes only.

## Recommended architecture

The current implementation follows this flow:

```
┌─────────────────┐
│  DBeaver UI     │
│ (PlainDbMain    │
│   Dialog)       │
└────────┬────────┘
         │
    [User enters:]
    - API key
    - Database type
    - Request (English)
         │
         ▼
┌─────────────────────────────────────┐
│ VerifyRequestHandler                │
│ - Validates English-only            │
│ - Creates SqlGeneratorClient        │
└────────┬────────────────────────────┘
         │
       [Backend call]
          │
          ▼
   ┌─────────────────────┐
   │ PlainDB Backend     │
   │ /run + rollback API │
   └────────┬────────────┘
          │
          ▼
┌─────────────────────┐
│ Generated SQL       │
│ (Displayed in       │
│  PlainDbMainDialog) │
└─────────────────────┘
         │
         ▼
┌─────────────────────┐
│ User copies SQL     │
│ and executes in     │
│ their database      │
└─────────────────────┘
```

### Implementation Details

1. **UI Layer**: `PlainDbMainDialog.java` - SWT-based interface with:
   - Password field for API key
   - Combo box for database selection
   - Multi-line text areas for input/output
   - Action buttons

2. **Service Layer**: `SqlGeneratorClient.java` - HTTP client supporting:
   - PlainDB backend `/run` request contract
   - PlainDB rollback API (`POST /rollback/{rollback_id}`)
   - JSON encoding/decoding and error handling

3. **Handler Layer**: `VerifyRequestHandler.java` - Orchestrates:
   - Dialog opening
   - Request validation (English-only)
   - Backend call wiring
   - Error messaging

## Local development

This repository does not yet include the full DBeaver SDK target platform.
The Java sources here are a starter scaffold that should be moved into a real
Eclipse/DBeaver plugin project and linked against the DBeaver API bundles.

## Next implementation step

Connect the handler to the exact DBeaver SQL execution interception point used
by your target DBeaver edition, then wire the PlainDB HTTP client into it.

# PlainDB DBeaver Plugin

This is the DBeaver integration layer for **PlainDB** – a database-agnostic safety pipeline for executing AI-generated SQL with multiple verification layers.

## What it does

### Main Capabilities
- **Verify SQL Intent** - Convert natural English requests into SQL queries
- **Multiple Providers**:
  - **Local PlainDB** - Verification pipeline only (no AI)
  - **OpenAI** - GPT-3.5, GPT-4 via OpenAI API
  - **Gemini** - Google Gemini 2.5 Flash via Generative Language API
  - **Remote Backend** - Connect to PlainDB backend service
- **Database Support** - PostgreSQL, MySQL, SQLite, Oracle, SQL Server, etc.
- **Verification Stages** - See semantic, safety, effect, and post-commit verification results
- **Transaction Safety** - Automatic rollback on verification failures
- **English Validation** - Ensures requests are in English only

### Architecture

The plugin is a **thin client** that:
1. Takes natural language SQL requests from users
2. Calls **AI providers** (OpenAI, Gemini) or a **PlainDB backend service** to generate SQL
3. Displays verification results and execution audit trail
4. Allows safe SQL execution through the verification pipeline

```
DBeaver Plugin
    ↓
Verify Request Dialog
    ↓
SqlGeneratorClient (Java)
    ↓ (HTTP)
Backend API or AI Provider
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
   - **Provider**: Select "PlainDB (Backend)", "OpenAI", or "Gemini (Google)"
   - **API Key** (if using AI): Paste your OpenAI or Gemini API key
   - **Backend URL** (if using backend): `http://localhost:8000` or remote URL
   - Click **Save**

### Verification Dialog

Once configured, the **Verify Request** dialog shows:

**Input Section:**
- **Database**: Select target database system
- **Request**: Write your SQL operation in English (e.g., "Show users older than 25")

**Output Section:**
- **Generated SQL**: The SQL candidate created by pipeline or AI
- **Verification Results**: Pass/fail stages (semantic, safety, effect, post-commit)
- **Execution Status**: Success/error with row count

**Buttons:**
- **Load Database**: Refresh connected database metadata
- **Generate SQL**: Run verification pipeline
- **Copy SQL**: Copy result to clipboard
- **Execute**: (future) Execute SQL in connected database

### Example Workflows

#### 1. Using PlainDB Backend (No AI)

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
   Output: SELECT * FROM users WHERE status='active' AND created_year=2024;
   Stages: semantic ✓, safety ✓, execution ✓, post-commit ✓
```

#### 2. Using OpenAI (GPT-4)

```
1. Account Tab:
   - Provider: "OpenAI (GPT-4)"
   - API Key: "sk-..."
   - Save

2. Verify Request Tab:
   - Database: "MySQL"
   - Request: "Count orders placed last month"
   - Click "Generate SQL"

3. Results:
   Output: SELECT COUNT(*) FROM orders WHERE MONTH(created_at)=MONTH(NOW())-1;
   Stages: semantic ✓, safety ✓, execution ✓, post-commit ✓
```

#### 3. Using Gemini (Google)

```
1. Account Tab:
   - Provider: "Gemini (Google)"
   - API Key: "AIza..." (from Google Cloud)
   - Custom Endpoint: (optional, leave blank for default)
   - Save

2. Verify Request Tab:
   - Database: "SQLite"
   - Request: "Get products with low stock"
   - Click "Generate SQL"

3. Results:
   Output: SELECT * FROM products WHERE stock_count < minimum_threshold;
   Stages: semantic ✓, safety ✓, execution ✓, post-commit ✓
```

### Configuration

#### Account Tab Settings

| Field | Usage | Notes |
|-------|-------|-------|
| **Provider** | Select API source | "PlainDB (Backend)", "OpenAI", "Gemini" |
| **API Key** | Authentication | Required for OpenAI/Gemini. Blank for backend. |
| **Custom Endpoint** | Alternative server | For Gemini Vertex AI or self-hosted backend |
| **Dry Run** | Test without commit | Rollback changes after verification |

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
    [Route based on API key:]
         │
    ┌────┴────┐
    │          │
    ▼          ▼
┌──────────┐  ┌──────────────┐
│ OpenAI   │  │ Local        │
│ API      │  │ PlainDB      │
│ (Cloud)  │  │ Service      │
└──────────┘  └──────────────┘
    │          │
    └────┬─────┘
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
   - OpenAI Chat Completions API (`gpt-3.5-turbo`)
   - Local PlainDB service (`/api/v1/generate-sql`)
   - JSON encoding/decoding
   - Error handling

3. **Handler Layer**: `VerifyRequestHandler.java` - Orchestrates:
   - Dialog opening
   - Request validation (English-only)
   - API selection logic
   - Error messaging

## Local development

This repository does not yet include the full DBeaver SDK target platform.
The Java sources here are a starter scaffold that should be moved into a real
Eclipse/DBeaver plugin project and linked against the DBeaver API bundles.

## Next implementation step

Connect the handler to the exact DBeaver SQL execution interception point used
by your target DBeaver edition, then wire the PlainDB HTTP client into it.

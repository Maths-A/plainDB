"""PlainDB REST API - FastAPI server for SQL generation and verification."""

import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from plain_db import PlainDBPipeline, PipelineConfig, SQLCandidate, UserIntent
from plain_db.adapters import SQLiteAdapter

# ============================================================================
# Configuration
# ============================================================================

DB_PATH = os.environ.get("PLAINDB_DB_PATH", ":memory:")
PORT = int(os.environ.get("PLAINDB_PORT", 8000))
HOST = os.environ.get("PLAINDB_HOST", "0.0.0.0")

# ============================================================================
# Global State
# ============================================================================

pipeline: Optional[PlainDBPipeline] = None
adapter: Optional[SQLiteAdapter] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and cleanup resources on startup/shutdown."""
    global pipeline, adapter
    
    # Startup
    print(f"[PlainDB] Initializing backend with database: {DB_PATH}")
    adapter = SQLiteAdapter(DB_PATH)
    pipeline = PlainDBPipeline(adapter)
    
    yield
    
    # Shutdown
    if adapter:
        adapter.close()
        print("[PlainDB] Backend shutdown complete")


app = FastAPI(
    title="PlainDB API",
    description="SQL generation and verification backend service",
    version="0.1.0",
    lifespan=lifespan,
)

# ============================================================================
# Request/Response Models
# ============================================================================


class GenerateSQLRequest(BaseModel):
    """Request model for SQL generation."""
    
    intent_text: str
    expected_tables: Optional[list[str]] = None
    expected_action: Optional[str] = None
    dry_run: bool = False
    watched_tables: Optional[list[str]] = None
    model_name: Optional[str] = None


class VerificationStageResponse(BaseModel):
    """Response model for a verification stage result."""
    
    stage: str
    passed: bool
    reason: str
    details: dict


class ExecutionResponse(BaseModel):
    """Response model for execution result."""
    
    success: bool
    rowcount: int
    error: Optional[str] = None


class GenerateSQLResponse(BaseModel):
    """Response model for SQL generation."""
    
    accepted: bool
    committed: bool
    sql: str
    execution: Optional[ExecutionResponse] = None
    stages: list[VerificationStageResponse]
    attempts: int


# ============================================================================
# Endpoints
# ============================================================================


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "plaindb-backend",
        "database": DB_PATH,
    }


@app.post("/api/v1/generate-sql")
async def generate_sql(request: GenerateSQLRequest) -> GenerateSQLResponse:
    """
    Generate and execute SQL based on natural language intent.
    
    This endpoint:
    1. Accepts natural language SQL intent
    2. Verifies semantic correctness
    3. Applies safety rules
    4. Executes with effect verification
    5. Optionally commits (or rolls back in dry-run mode)
    
    Args:
        request: GenerateSQLRequest with intent and configuration
    
    Returns:
        GenerateSQLResponse with execution results and audit trail
    """
    
    if not pipeline:
        raise HTTPException(
            status_code=500,
            detail="Pipeline not initialized. Service may be starting up."
        )
    
    # Build domain models from request
    intent = UserIntent(
        text=request.intent_text,
        expected_tables=request.expected_tables or [],
        expected_action=request.expected_action,
    )
    
    candidate = SQLCandidate(
        sql="",  # In real usage, this would come from LLM
        model_name=request.model_name,
    )
    
    config = PipelineConfig(
        dry_run_only=request.dry_run,
        watched_tables=request.watched_tables or [],
    )
    
    # Run pipeline
    try:
        result = pipeline.run(intent, candidate, config)
        
        # Convert result to response
        execution_response = None
        if result.execution:
            execution_response = ExecutionResponse(
                success=result.execution.success,
                rowcount=result.execution.rowcount,
                error=result.execution.error,
            )
        
        stages_response = [
            VerificationStageResponse(
                stage=s.stage,
                passed=s.passed,
                reason=s.reason,
                details=s.details,
            )
            for s in result.stages
        ]
        
        return GenerateSQLResponse(
            accepted=result.accepted,
            committed=result.committed,
            sql=candidate.sql,
            execution=execution_response,
            stages=stages_response,
            attempts=result.attempts,
        )
    
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Pipeline execution failed: {str(e)}",
        )


@app.get("/api/v1/info")
async def service_info():
    """Get service information and configuration."""
    return {
        "service": "plaindb-backend",
        "version": "0.1.0",
        "database_path": DB_PATH,
        "endpoints": [
            {"method": "GET", "path": "/health", "description": "Health check"},
            {"method": "GET", "path": "/api/v1/info", "description": "Service info"},
            {"method": "POST", "path": "/api/v1/generate-sql", "description": "Generate SQL"},
        ],
    }


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    print(f"[PlainDB] Starting server on {HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT)

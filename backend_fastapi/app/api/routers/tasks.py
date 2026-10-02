"""Endpoints for interacting with Celery tasks."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ...core.test_mode import is_production
from ...dependencies.powers import require_power
from ...models import User
from ...tasks import echo


class TestTaskRequest(BaseModel):
    """Request body for the test task endpoint."""

    message: str = Field(
        default="hello", description="Message to echo in the background job"
    )


class TestTaskResponse(BaseModel):
    """Response returned after the task is queued."""

    task_id: str


router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post(
    "/test", status_code=status.HTTP_202_ACCEPTED, response_model=TestTaskResponse
)
async def enqueue_test_task(
    payload: TestTaskRequest,
    _admin: User = Depends(require_power("view_system_health")),
) -> TestTaskResponse:
    """Queue a background job that echoes the provided message.

    F-68: this used to be unauthenticated, so anyone on the internet could
    enqueue unbounded Celery jobs and saturate the worker fleet. It is a
    diagnostic aid, so it is now both admin-gated *and* refused outright in
    production — nothing legitimate calls it against a live deployment.
    """

    if is_production():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="not_found"
        )

    result = echo.delay(payload.message)
    return TestTaskResponse(task_id=result.id)

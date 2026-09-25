"""Financial run API reusing the session-file authentication and envelopes."""

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from dbgpt_serve.core import Result
from dbgpt_serve.session_file.api.endpoints import (
    _SessionFileApiRoute,
    get_authenticated_owner,
)


class CreateRun(BaseModel):
    session_id: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$")
    file_ids: list[str] = Field(min_length=1, max_length=1)
    request_id: UUID = Field(default_factory=uuid4)


def make_router(service):
    router = APIRouter(route_class=_SessionFileApiRoute)

    @router.post("/runs", status_code=202)
    def create_run(body: CreateRun, owner: str = Depends(get_authenticated_owner)):
        return Result.succ(
            service.create(
                owner, body.session_id, body.file_ids[0], str(body.request_id)
            )
        )

    @router.get("/runs/{run_id}")
    def get_run(
        run_id: UUID,
        session_id: str = Query(min_length=1, max_length=255),
        owner: str = Depends(get_authenticated_owner),
    ):
        return Result.succ(service.get(owner, session_id, str(run_id)))

    @router.get("/runs/{run_id}/report")
    def get_report(
        run_id: UUID,
        session_id: str = Query(min_length=1, max_length=255),
        owner: str = Depends(get_authenticated_owner),
    ):
        return Result.succ(service.get(owner, session_id, str(run_id), report=True))

    return router

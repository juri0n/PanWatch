"""Mounted by the host behind its existing authentication boundary."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StrictBool

router = APIRouter()


def workflow(request):
    instance = getattr(request.app.state, "crypto_workflow", None)
    if instance is None:
        raise HTTPException(503, "Crypto workflow is unavailable")
    return instance


@router.get("")
async def state(request: Request):
    return workflow(request).view()


@router.put("/config")
async def configure(value: dict, request: Request):
    try:
        return await workflow(request).save(value)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post("/refresh")
async def refresh(request: Request):
    return await workflow(request).refresh()


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notify: StrictBool = False


@router.post("/reports", status_code=202)
async def report(value: ReportRequest, request: Request):
    try:
        return await workflow(request).start_report(value.notify)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None

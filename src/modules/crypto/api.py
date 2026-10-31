"""Mounted by the host behind its existing authentication boundary."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StrictBool
from .validation import ConfigFieldError

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
    except ConfigFieldError as exc:
        raise HTTPException(422, {"code": exc.code, "message": str(exc), "field": exc.field}) from None
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


@router.get('/opportunities')
async def opportunities(request:Request,timeframe:str='1d',strategy:str='all',holding:str='all',state:str='all',freshness:str='all',risk:str='all',min_score:float=0):
    try:
        return workflow(request).opportunities.view(timeframe=timeframe,strategy=strategy,holding=holding,state=state,freshness=freshness,risk=risk,min_score=min_score)
    except ValueError as exc:raise HTTPException(422,str(exc)) from None


@router.post('/opportunities/scans',status_code=202)
async def start_opportunity_scan(value:dict,request:Request):
    try:return await workflow(request).opportunities.start(value)
    except (ValueError,TypeError) as exc:raise HTTPException(422,str(exc)) from None
    except RuntimeError as exc:raise HTTPException(409,str(exc)) from None


@router.post('/opportunities/cancel',status_code=202)
async def cancel_opportunity_scan(request:Request):
    return await workflow(request).opportunities.cancel()

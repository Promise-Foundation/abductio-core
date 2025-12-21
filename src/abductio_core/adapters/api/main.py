from importlib.metadata import PackageNotFoundError, version

from fastapi import FastAPI


def _app_version() -> str:
    try:
        return version("abductio-core")
    except PackageNotFoundError:
        return "0.0.0"


app = FastAPI(title="abductio-core API", version=_app_version())


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}

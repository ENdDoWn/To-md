import os


def main() -> None:
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("to_md.app:app", host="0.0.0.0", port=port)

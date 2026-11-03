"""Start Crochet Studio: python run.py [--reload]"""

import argparse

import uvicorn

from app.config import settings

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Crochet Studio")
    parser.add_argument("--reload", action="store_true", help="restart automatically when code changes")
    args = parser.parse_args()
    print(f"Crochet Studio -> http://{'localhost' if settings.host in ('127.0.0.1', '0.0.0.0') else settings.host}:{settings.port}")
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=args.reload)

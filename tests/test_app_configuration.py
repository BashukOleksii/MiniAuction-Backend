"""Prevent accidental replacement of the FastAPI entry point with config code."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.main import app


def test_fastapi_app_is_exported():
    assert isinstance(app, FastAPI)



def test_cors_middleware_is_configured():
    assert any(
        middleware.cls is CORSMiddleware
        for middleware in app.user_middleware
    )

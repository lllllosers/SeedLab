"""Translate growth-domain failures to their existing HTTP responses."""
from fastapi import HTTPException, Request
from fastapi.exception_handlers import http_exception_handler

from app.contracts.errors import ApplicationError, ConflictError, NotFoundError, ValidationError


async def application_error_handler(request: Request, error: ApplicationError):
    for error_type, status in ((NotFoundError, 404), (ConflictError, 409), (ValidationError, 422)):
        if isinstance(error, error_type):
            return await http_exception_handler(request, HTTPException(status, error.detail))
    raise error  # Unclassified failures must not be guessed into a client error.

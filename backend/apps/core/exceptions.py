import logging
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger('apps.core')


def global_exception_handler(exc, context):
    # Let DRF handle its own exceptions first
    response = exception_handler(exc, context)

    request = context.get('request')
    request_id = getattr(request, 'request_id', None)

    # Map Django exceptions to DRF equivalents
    if isinstance(exc, Http404):
        exc = exceptions.NotFound()
        response = exception_handler(exc, context)
    elif isinstance(exc, PermissionDenied):
        exc = exceptions.PermissionDenied()
        response = exception_handler(exc, context)
    elif isinstance(exc, ValidationError):
        exc = exceptions.ValidationError(detail=exc.message_dict if hasattr(exc, 'message_dict') else exc.messages)
        response = exception_handler(exc, context)

    if response is not None:
        error_code = type(exc).__name__
        detail = response.data

        # Normalise detail into a flat errors list
        if isinstance(detail, dict) and 'detail' in detail:
            errors = [str(detail['detail'])]
        elif isinstance(detail, list):
            errors = [str(e) for e in detail]
        elif isinstance(detail, dict):
            errors = {k: [str(e) for e in v] if isinstance(v, list) else str(v)
                      for k, v in detail.items()}
        else:
            errors = [str(detail)]

        response.data = {
            'success': False,
            'error': {
                'code': error_code,
                'status': response.status_code,
                'errors': errors,
            },
            'request_id': request_id,
        }
        return response

    # Unhandled exception — 500
    logger.exception(
        'Unhandled exception on %s %s request_id=%s',
        request.method if request else 'UNKNOWN',
        request.path if request else 'UNKNOWN',
        request_id,
        exc_info=exc,
    )

    return Response(
        {
            'success': False,
            'error': {
                'code': 'InternalServerError',
                'status': 500,
                'errors': ['An unexpected error occurred. Please try again.'],
            },
            'request_id': request_id,
        },
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
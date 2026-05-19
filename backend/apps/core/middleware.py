import logging
import time
import uuid

logger = logging.getLogger('apps.core')


class RequestLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = str(uuid.uuid4())
        request.request_id = request_id

        start = time.monotonic()

        response = self.get_response(request)

        duration_ms = round((time.monotonic() - start) * 1000, 2)

        logger.info(
            '%s %s %s %sms id=%s user=%s',
            request.method,
            request.path,
            response.status_code,
            duration_ms,
            request_id,
            getattr(request.user, 'id', 'anonymous'),
        )

        response['X-Request-ID'] = request_id
        return response
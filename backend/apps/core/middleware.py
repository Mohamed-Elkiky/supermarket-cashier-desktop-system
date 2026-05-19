import logging
import time
import uuid
import re

logger = logging.getLogger('apps.core')

# Patterns that indicate SQL injection attempts
SQLI_PATTERNS = [
    r'(\%27)|(\')|(\-\-)|(\%23)|(#)',
    r'((\%3D)|(=))[^\n]*((\%27)|(\')|(\-\-)|(\%3B)|(;))',
    r'\w*((\%27)|(\'))((\%6F)|o|(\%4F))((\%72)|r|(\%52))',
    r'((\%27)|(\'))union',
    r'exec(\s|\+)+(s|x)p\w+',
    r'insert|update|delete|drop|create|alter|truncate',
]

SQLI_REGEX = re.compile('|'.join(SQLI_PATTERNS), re.IGNORECASE)


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


class SqlInjectionProtectionMiddleware:
    """
    Scans incoming request parameters for SQL injection patterns.
    Blocks and logs any suspicious requests before they reach the view.
    This is a defence-in-depth layer — Django ORM parameterised queries
    are the primary protection.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Check query string parameters
        for key, value in request.GET.items():
            if self._is_suspicious(key) or self._is_suspicious(value):
                logger.warning(
                    'SQL injection attempt detected in query params: key=%s value=%s ip=%s path=%s',
                    key, value,
                    request.META.get('REMOTE_ADDR'),
                    request.path,
                )
                from django.http import JsonResponse
                return JsonResponse(
                    {
                        'success': False,
                        'error': {
                            'code': 'BadRequest',
                            'status': 400,
                            'errors': ['Invalid input detected.'],
                        }
                    },
                    status=400,
                )

        return self.get_response(request)

    def _is_suspicious(self, value: str) -> bool:
        if not value:
            return False
        return bool(SQLI_REGEX.search(str(value)))
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.db import connection


class HealthCheckView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        db_ok = True
        try:
            connection.ensure_connection()
        except Exception:
            db_ok = False

        status_code = 200 if db_ok else 503
        return Response(
            {
                'success': True,
                'status': 'ok' if db_ok else 'degraded',
                'checks': {
                    'database': 'ok' if db_ok else 'error',
                },
            },
            status=status_code,
        )
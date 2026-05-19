from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.db import connection
from apps.accounts.permissions import IsStoreManager
from apps.accounts.decorators import role_required


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


class ManagerOnlyView(APIView):
    permission_classes = [IsAuthenticated, IsStoreManager]

    def get(self, request):
        return Response({'success': True, 'message': 'You are a manager or above.'})
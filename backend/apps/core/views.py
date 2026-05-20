from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.db import connection
from django.conf import settings
from drf_spectacular.utils import extend_schema, OpenApiResponse
from apps.accounts.permissions import IsStoreManager


class HealthCheckView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        summary="Health check",
        description="Returns the current health status of the API and its dependencies. Use this for uptime monitoring.",
        responses={
            200: OpenApiResponse(description="API is healthy"),
            503: OpenApiResponse(description="API is degraded — database unavailable"),
        },
        tags=["System"],
    )
    def get(self, request):
        db_ok = True
        try:
            connection.ensure_connection()
        except Exception:
            db_ok = False

        is_secure = request.is_secure()
        status_code = 200 if db_ok else 503
        return Response(
            {
                "success": True,
                "status": "ok" if db_ok else "degraded",
                "checks": {
                    "database": "ok" if db_ok else "error",
                    "tls": "ok" if is_secure else "not enforced in dev",
                },
                "environment": "production" if not settings.DEBUG else "development",
            },
            status=status_code,
        )


class ManagerOnlyView(APIView):
    permission_classes = [IsAuthenticated, IsStoreManager]

    @extend_schema(
        summary="Manager test endpoint",
        description="Test endpoint — returns 200 for store manager role and above, 403 for cashier.",
        responses={
            200: OpenApiResponse(description="Authorised"),
            403: OpenApiResponse(description="Insufficient role"),
        },
        tags=["System"],
    )
    def get(self, request):
        return Response({"success": True, "message": "You are a manager or above."})
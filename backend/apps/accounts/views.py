import logging

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from .rate_limiting import (clear_failed_attempts, get_lockout_remaining,
                            is_ip_rate_limited, is_user_locked,
                            record_failed_attempt)
from .serializers import LoginSerializer, LogoutSerializer, RefreshSerializer
from .services import blacklist_token, generate_tokens

logger = logging.getLogger("apps.accounts")


def get_client_ip(request) -> str:
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "0.0.0.0")


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        ip = get_client_ip(request)
        email = request.data.get("email", "").lower().strip()

        # Per-IP rate limit
        if is_ip_rate_limited(ip):
            logger.warning("IP rate limited: %s", ip)
            return Response(
                {
                    "success": False,
                    "error": {
                        "code": "RateLimitExceeded",
                        "status": 429,
                        "errors": [
                            "Too many login attempts from this IP. Try again later."
                        ],
                    },
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        # Per-user lockout
        if email and is_user_locked(email):
            remaining = get_lockout_remaining(email)
            logger.warning("Locked account login attempt: %s from IP %s", email, ip)
            return Response(
                {
                    "success": False,
                    "error": {
                        "code": "AccountLocked",
                        "status": 429,
                        "errors": [
                            f"Account locked due to too many failed attempts. "
                            f"Try again in {remaining // 60} minutes."
                        ],
                    },
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        serializer = LoginSerializer(data=request.data, context={"request": request})

        if not serializer.is_valid():
            if email:
                record_failed_attempt(ip, email)
            return Response(
                {
                    "success": False,
                    "error": {
                        "code": "ValidationError",
                        "status": 400,
                        "errors": serializer.errors,
                    },
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = serializer.validated_data["user"]

        # Clear failed attempts on successful login
        clear_failed_attempts(ip, email)

        tokens = generate_tokens(user)
        logger.info("User logged in: %s from IP %s", user.email, ip)
        return Response({"success": True, "data": tokens}, status=status.HTTP_200_OK)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            blacklist_token(serializer.validated_data["refresh"])
        except ValueError as e:
            return Response(
                {
                    "success": False,
                    "error": {"code": "InvalidToken", "errors": [str(e)]},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        logger.info("User logged out: %s", request.user.email)
        return Response({"success": True}, status=status.HTTP_200_OK)


class SilentRefreshView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            refresh = RefreshToken(serializer.validated_data["refresh"])
            new_access = str(refresh.access_token)
            new_refresh = str(refresh)
            return Response(
                {
                    "success": True,
                    "data": {"access": new_access, "refresh": new_refresh},
                },
                status=status.HTTP_200_OK,
            )
        except TokenError as e:
            return Response(
                {
                    "success": False,
                    "error": {"code": "InvalidToken", "errors": [str(e)]},
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

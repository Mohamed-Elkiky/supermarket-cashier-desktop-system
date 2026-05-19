
import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError

from .serializers import LoginSerializer, LogoutSerializer, RefreshSerializer
from .services import generate_tokens, blacklist_token

logger = logging.getLogger('apps.accounts')


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        tokens = generate_tokens(serializer.validated_data['user'])
        logger.info('User logged in: %s', serializer.validated_data['user'].email)
        return Response({'success': True, 'data': tokens}, status=status.HTTP_200_OK)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            blacklist_token(serializer.validated_data['refresh'])
        except ValueError as e:
            return Response(
                {'success': False, 'error': {'code': 'InvalidToken', 'errors': [str(e)]}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        logger.info('User logged out: %s', request.user.email)
        return Response({'success': True}, status=status.HTTP_200_OK)


class SilentRefreshView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            refresh = RefreshToken(serializer.validated_data['refresh'])
            new_access  = str(refresh.access_token)
            new_refresh = str(refresh)
            return Response(
                {'success': True, 'data': {'access': new_access, 'refresh': new_refresh}},
                status=status.HTTP_200_OK,
            )
        except TokenError as e:
            return Response(
                {'success': False, 'error': {'code': 'InvalidToken', 'errors': [str(e)]}},
                status=status.HTTP_401_UNAUTHORIZED,
            )
import logging
import json

from django.db import connection, transaction
from django.utils import timezone

logger = logging.getLogger("apps.core")


def log_activity(
    request,
    action: str,
    entity_type: str,
    entity_id,
    before_state: dict = None,
    after_state: dict = None,
):
    """
    Write a tamper-proof activity log entry.
    Call this after every successful write operation.

    Usage:
        log_activity(request, 'order.create', 'order', order.id, after_state=order_data)
        log_activity(request, 'product.update', 'product_variant', variant.id,
                     before_state=old_data, after_state=new_data)
    """
    try:
        actor_id = None
        actor_role = None

        if request and hasattr(request, "user") and request.user.is_authenticated:
            actor_id = request.user.id
            if hasattr(request.user, "staff_profile") and request.user.staff_profile:
                actor_role = request.user.staff_profile.role

        ip_address = _get_client_ip(request)
        device_identifier = _get_device_identifier(request)

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO activity_log (
                        actor_staff_id,
                        actor_role,
                        action,
                        entity_type,
                        entity_id,
                        before_state,
                        after_state,
                        device_identifier,
                        ip_address,
                        occurred_at
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s::jsonb, %s::jsonb,
                        %s, %s, %s
                    )
                    """,
                    [
                        actor_id,
                        actor_role,
                        action,
                        entity_type,
                        str(entity_id),
                        _to_json(before_state),
                        _to_json(after_state),
                        device_identifier,
                        ip_address,
                        timezone.now(),
                    ],
                )

    except Exception as e:
        # Never let activity logging break the main operation
        logger.error("Failed to write activity log: %s", str(e))


def _get_client_ip(request) -> str:
    if not request:
        return None
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _get_device_identifier(request) -> str:
    if not request:
        return None
    # Electron app sends X-Device-ID header
    return request.META.get("HTTP_X_DEVICE_ID") or request.META.get("HTTP_USER_AGENT", "")[:255]


def _to_json(data: dict):
    if data is None:
        return None
    return json.dumps(data)
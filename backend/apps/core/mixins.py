from .activity import log_activity


class ActivityLogMixin:
    """
    Mixin for APIView classes.
    Provides self.log() to write activity log entries.

    Usage in a view:
        class OrderCreateView(ActivityLogMixin, APIView):
            def post(self, request):
                # ... create order ...
                self.log(request, 'order.create', 'order', order.id,
                         after_state={'total': order.total_pence})
    """

    def log(self, request, action, entity_type, entity_id,
            before_state=None, after_state=None):
        log_activity(
            request=request,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before_state=before_state,
            after_state=after_state,
        )
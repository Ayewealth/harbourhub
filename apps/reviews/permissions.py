from rest_framework import permissions


class IsReviewerOrReadOnly(permissions.BasePermission):
    """Anyone may read; only the reviewer may edit or delete."""

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return obj.reviewer_id == request.user.id

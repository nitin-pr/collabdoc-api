import re

from rest_framework import serializers

from .models import User

PHONE_PATTERN = re.compile(r'^\+?\d{10,15}$')


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'first_name', 'last_name', 'email', 'phone', 'created_at']
        read_only_fields = ['id', 'created_at']
        # Drop DRF's automatic unique validators so a duplicate reaches the
        # database and the view can answer 409 instead of 400.
        extra_kwargs = {'email': {'validators': []}, 'phone': {'validators': []}}

    def validate_email(self, value):
        value = value.strip().lower()
        local, _, domain = value.partition('@')
        if not local or '.' not in domain or domain.startswith('.') or domain.endswith('.') or ' ' in value:
            raise serializers.ValidationError('Enter a valid email address.')
        return value

    def validate_phone(self, value):
        value = value.strip()
        if not PHONE_PATTERN.match(value):
            raise serializers.ValidationError(
                'Phone must contain only digits (optional leading +) and be 10-15 characters long.'
            )
        return value

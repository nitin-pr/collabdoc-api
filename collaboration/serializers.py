from rest_framework import serializers

from .models import AuditLog, Comment, Tag


class CommentSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    replies = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = ['id', 'document', 'author', 'author_name', 'content', 'parent', 'replies', 'created_at']
        read_only_fields = ['id', 'created_at']
        # author is nullable in the database (SET_NULL), but a new comment must name its author.
        extra_kwargs = {'author': {'required': True, 'allow_null': False}}

    def get_author_name(self, obj):
        if obj.author is None:
            return None
        return f'{obj.author.first_name} {obj.author.last_name}'

    def get_replies(self, obj):
        """
        Nested replies. The list view passes `children` (comment id -> list of replies) in the
        serializer context, built from a single query, so threading costs no extra queries.
        A freshly created comment has no replies yet.
        """
        children = self.context.get('children', {}).get(obj.id, [])
        return CommentSerializer(children, many=True, context=self.context).data

    def validate_content(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Comment cannot be blank.')
        return value

    def validate(self, attrs):
        parent = attrs.get('parent')
        if parent is not None and parent.document_id != attrs['document'].pk:
            raise serializers.ValidationError(
                {'parent': 'A reply must belong to the same document as the comment it replies to.'}
            )
        return attrs


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ['id', 'name']
        read_only_fields = ['id']
        # Drop the automatic unique validator so a duplicate reaches the database and becomes a 409.
        extra_kwargs = {'name': {'validators': []}}

    def validate_name(self, value):
        value = value.strip().lower()
        if not value:
            raise serializers.ValidationError('Tag name cannot be blank.')
        return value


class AuditLogSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = ['id', 'actor', 'actor_name', 'action', 'model_name', 'object_id', 'timestamp']
        read_only_fields = fields

    def get_actor_name(self, obj):
        if obj.actor is None:
            return None
        return f'{obj.actor.first_name} {obj.actor.last_name}'

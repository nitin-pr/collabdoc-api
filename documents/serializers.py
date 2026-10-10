from rest_framework import serializers

from users.models import User

from .models import Document, DocumentVersion


class DocumentSerializer(serializers.ModelSerializer):
    """Used for create and for every read. `version_count` is annotated by the view."""

    version_count = serializers.IntegerField(read_only=True)
    tag_names = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = [
            'id', 'title', 'content', 'workspace', 'created_by', 'status',
            'updated_at', 'version_count', 'tag_names',
        ]
        read_only_fields = ['id', 'updated_at']
        # created_by is nullable in the database (SET_NULL), but a new document must have an author.
        extra_kwargs = {'created_by': {'required': True, 'allow_null': False}}

    def get_tag_names(self, obj):
        # .all() reads the prefetch_related('tags') cache, so this adds no query per row.
        return sorted(tag.name for tag in obj.tags.all())

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Title cannot be blank.')
        return value

    def validate_workspace(self, value):
        if not value.is_active:
            raise serializers.ValidationError('Cannot add documents to an inactive workspace.')
        return value


class DocumentUpdateSerializer(serializers.Serializer):
    """Body of PUT /api/documents/{id}/. Workspace and author never change after creation."""

    title = serializers.CharField(max_length=255, required=False)
    content = serializers.CharField(trim_whitespace=False)
    status = serializers.ChoiceField(choices=Document.Status.choices, required=False)
    saved_by = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), required=False, allow_null=True)

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Title cannot be blank.')
        return value

    def validate_content(self, value):
        if not value.strip():
            raise serializers.ValidationError('Content cannot be blank.')
        return value


class DocumentVersionSerializer(serializers.ModelSerializer):
    saved_by_name = serializers.SerializerMethodField()

    class Meta:
        model = DocumentVersion
        fields = ['id', 'document', 'version_number', 'content', 'saved_by', 'saved_by_name', 'saved_at']

    def get_saved_by_name(self, obj):
        if obj.saved_by is None:
            return None
        return f'{obj.saved_by.first_name} {obj.saved_by.last_name}'


class AddTagsSerializer(serializers.Serializer):
    """`tags` is a list of tag names and/or tag IDs; a bare string is treated as a one-item list."""

    tags = serializers.ListField(child=serializers.CharField(max_length=100), allow_empty=False)

    def to_internal_value(self, data):
        raw = data.get('tags') if hasattr(data, 'get') else None
        if isinstance(raw, str):
            data = {'tags': [raw]}
        return super().to_internal_value(data)

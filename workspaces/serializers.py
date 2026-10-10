from rest_framework import serializers

from users.models import User

from .models import Workspace, WorkspaceMember


class WorkspaceSerializer(serializers.ModelSerializer):
    # Filled by annotate(Count('members')) in the view.
    member_count = serializers.IntegerField(read_only=True)
    owner_name = serializers.SerializerMethodField()

    class Meta:
        model = Workspace
        fields = ['id', 'name', 'owner', 'is_active', 'created_at', 'member_count', 'owner_name']
        read_only_fields = ['id', 'created_at']

    def get_owner_name(self, obj):
        return f'{obj.owner.first_name} {obj.owner.last_name}'

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Workspace name cannot be blank.')
        return value


class MemberUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'first_name', 'last_name', 'email']


class WorkspaceMemberSerializer(serializers.ModelSerializer):
    user = MemberUserSerializer(read_only=True)

    class Meta:
        model = WorkspaceMember
        fields = ['id', 'user', 'role', 'joined_at']


class AddMemberSerializer(serializers.Serializer):
    user = serializers.UUIDField()
    role = serializers.ChoiceField(choices=WorkspaceMember.Role.choices, default=WorkspaceMember.Role.VIEWER)

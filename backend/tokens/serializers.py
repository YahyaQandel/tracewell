from rest_framework import serializers

from tokens.models import ApiToken


class ApiTokenSerializer(serializers.ModelSerializer):
    masked_display = serializers.SerializerMethodField()

    class Meta:
        model = ApiToken
        fields = ['id', 'name', 'masked_display', 'created_at', 'last_used_at']

    def get_masked_display(self, token):
        return token.masked_display()


class CreateApiTokenSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, allow_blank=False)

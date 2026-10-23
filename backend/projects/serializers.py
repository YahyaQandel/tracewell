from rest_framework import serializers

from projects.models import Project


class ProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = ['id', 'organization', 'name', 'slug']


class ProjectListSerializer(serializers.ModelSerializer):
    """Read shape for GET .../projects/ (list) - distinct from
    ProjectSerializer (used by POST's create-response and the
    slug-preview endpoint) because this shape carries two computed,
    request-scoped fields neither of those endpoints need."""
    member_count = serializers.SerializerMethodField()
    latest_run = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = ['id', 'organization', 'name', 'slug', 'member_count', 'latest_run']

    def get_member_count(self, project):
        # Passed in via context by the view - one query per request,
        # not one per project (member count is organization-scoped, so
        # it's identical for every project in this list).
        return self.context.get('member_count', 0)

    def get_latest_run(self, project):
        # TW-26 (#36): Run.project is now a real FK. The view computes
        # the latest run per project in one query (not N+1) and passes
        # the map in via context - this just looks it up.
        run = self.context.get('latest_run_by_project_id', {}).get(project.id)
        return str(run.id) if run is not None else None

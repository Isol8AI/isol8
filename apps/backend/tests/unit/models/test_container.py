"""Tests for container dict structure (DynamoDB items)."""


class TestContainerDict:
    """Test container dict shape."""

    def test_create_container_dict(self):
        """Container dict can be created with ECS Fargate fields."""
        container = {
            "user_id": "user_test_123",
            "service_name": "openclaw-user_tes",
            "task_arn": "arn:aws:ecs:us-east-1:123456789:task/cluster/abc123",
            "gateway_token": "tok-abc123",
            "status": "running",
        }
        assert container["user_id"] == "user_test_123"
        assert container["status"] == "running"

    def test_container_default_fields(self):
        """Container dict can have optional fields set to None."""
        container = {
            "user_id": "user_test_123",
            "gateway_token": "tok-default",
            "status": "stopped",
            "service_name": None,
            "task_arn": None,
            "substatus": None,
        }
        assert container["status"] == "stopped"
        assert container["service_name"] is None
        assert container["substatus"] is None

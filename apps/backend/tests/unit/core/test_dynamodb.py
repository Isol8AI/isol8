from unittest.mock import patch

from core.dynamodb import table_name


def test_table_name_with_prefix():
    with patch("core.dynamodb._table_prefix", "isol8-dev-"):
        assert table_name("containers") == "isol8-dev-containers"


def test_table_name_without_prefix():
    with patch("core.dynamodb._table_prefix", ""):
        assert table_name("containers") == "containers"

from unittest.mock import MagicMock


def test_acquire_allows_under_limit():
    from sap_doc_agent.tasks.rate_limit import SAPRateLimiter

    mock_redis = MagicMock()
    mock_pipe = MagicMock()
    mock_pipe.execute.return_value = [0, 5, 1, 1]  # count_before_add=5, rps=10 → allowed
    mock_redis.pipeline.return_value = mock_pipe
    rl = SAPRateLimiter(mock_redis, rps=10)
    result = rl.acquire("DSP_PROD")
    assert result is True


def test_acquire_blocks_over_limit():
    from sap_doc_agent.tasks.rate_limit import SAPRateLimiter

    mock_redis = MagicMock()
    mock_pipe = MagicMock()
    mock_pipe.execute.return_value = [0, 10, 1, 1]  # count_before_add=10 == rps=10 → blocked
    mock_redis.pipeline.return_value = mock_pipe
    rl = SAPRateLimiter(mock_redis, rps=10)
    result = rl.acquire("DSP_PROD")
    assert result is False

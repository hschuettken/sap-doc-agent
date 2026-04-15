class AWSSecretsManagerBackend:
    def get(self, key: str):
        raise NotImplementedError(
            "AWS Secrets Manager backend not implemented. Install boto3 and implement AWSSecretsManagerBackend.get(). "
            "See docs/INSTALL.md for configuration."
        )

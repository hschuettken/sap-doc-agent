class AzureKVBackend:
    def get(self, key: str):
        raise NotImplementedError(
            "Azure Key Vault backend not implemented. Install azure-keyvault-secrets and implement AzureKVBackend.get(). "
            "See docs/INSTALL.md for configuration."
        )

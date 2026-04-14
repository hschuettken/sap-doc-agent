class VaultBackend:
    def get(self, key: str):
        raise NotImplementedError(
            "Vault backend not implemented. Install hvac and implement VaultBackend.get(). "
            "See docs/INSTALL.md for configuration."
        )

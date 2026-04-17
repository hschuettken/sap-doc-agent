"""
SAP Datasphere REST API scanner.

Scans Datasphere spaces for objects and converts them into the
canonical ScannedObject/ScanResult model.
"""

from __future__ import annotations

import fnmatch
from typing import Union

import httpx

from spec2sphere.scanner.dsp_auth import DSPAuth, DSPAuthType, DSPBasicAuth, DSPOAuthClient  # noqa: F401
from spec2sphere.scanner.models import (
    ObjectType,
    ScanResult,
    ScannedObject,
)

# Mapping from DSP technical type strings to internal ObjectType
_DSP_TYPE_MAP: dict[str, ObjectType] = {
    "VIEW": ObjectType.VIEW,
    "SQL_VIEW": ObjectType.VIEW,
    "GRAPHICAL_VIEW": ObjectType.VIEW,
    "ANALYTIC_MODEL": ObjectType.VIEW,
    "LOCAL_TABLE": ObjectType.TABLE,
    "REMOTE_TABLE": ObjectType.TABLE,
    "REPLICATION_FLOW": ObjectType.DATA_SOURCE,
    "DATA_FLOW": ObjectType.TRANSFORMATION,
    "TRANSFORMATION_FLOW": ObjectType.TRANSFORMATION,
    "TASK_CHAIN": ObjectType.PROCESS_CHAIN,
}


def _infer_layer(name: str) -> str:
    """Infer the data layer from object name prefix convention."""
    if name.startswith("01_"):
        return "raw"
    if name.startswith("02_"):
        return "harmonized"
    if name.startswith("03_"):
        return "mart"
    return ""


def _map_type(dsp_type: str) -> ObjectType:
    return _DSP_TYPE_MAP.get(dsp_type, ObjectType.OTHER)


class DSPScanner:
    """Scanner for SAP Datasphere via its catalog REST API.

    Accepts both DSPOAuthClient and DSPBasicAuth as the ``auth`` argument.
    On a 401 response the auth object's ``invalidate()`` is called so that
    the next request will obtain fresh credentials (meaningful for OAuth).
    """

    def __init__(
        self,
        base_url: str,
        auth: Union[DSPOAuthClient, DSPBasicAuth, DSPAuth],
        spaces: list[str],
        namespace_filter: list[str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth = auth
        self._spaces = spaces
        self._namespace_filter = namespace_filter
        self._timeout = timeout

    async def _get(self, url: str, params: dict | None = None) -> httpx.Response:
        """GET with automatic 401 → token invalidate → one retry."""
        headers = await self._auth.get_headers()
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(url, headers=headers, params=params)

        if response.status_code == 401:
            # Invalidate cached creds and retry once
            await self._auth.invalidate()
            headers = await self._auth.get_headers()
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url, headers=headers, params=params)

        return response

    async def list_spaces(self) -> list[dict]:
        """Return all spaces from the Datasphere catalog."""
        response = await self._get(f"{self._base_url}/api/v1/dwc/catalog/spaces")
        response.raise_for_status()
        return response.json()["value"]

    async def get_space_objects(self, space: str) -> list[dict]:
        """Return all assets in a given space."""
        params = {"$filter": f"SpaceName eq '{space}'"}
        response = await self._get(f"{self._base_url}/api/v1/dwc/catalog/assets", params=params)
        response.raise_for_status()
        return response.json()["value"]

    async def scan(self) -> ScanResult:
        """Scan all configured spaces and return a merged ScanResult."""
        objects: list[ScannedObject] = []

        for space in self._spaces:
            raw_objects = await self.get_space_objects(space)
            for raw in raw_objects:
                name: str = raw.get("technicalName") or raw.get("name", "")
                description: str = raw.get("description") or ""
                dsp_type: str = raw.get("type", "")
                object_id = f"{space}.{name}"

                # Apply namespace filter (fnmatch patterns)
                if self._namespace_filter is not None:
                    if not any(fnmatch.fnmatch(name, pat) for pat in self._namespace_filter):
                        continue

                obj = ScannedObject(
                    object_id=object_id,
                    object_type=_map_type(dsp_type),
                    name=name,
                    description=description,
                    package=space,
                    source_system="DSP",
                    layer=_infer_layer(name),
                    metadata={"dsp_type": dsp_type, "space": space},
                )
                objects.append(obj)

        return ScanResult(
            source_system="DSP",
            objects=objects,
            dependencies=[],
        )

"""MCP tools + signed HTTP routes for getting user files to/from a remote server.

Over HTTP the user's files live on their laptop. These tools mint short-lived,
HMAC-signed URLs; the bytes then move out-of-band over PUT/GET (never through the
LLM context), landing in the caller's isolated, sandboxed RUN_ROOT/<user>/uploads.
"""
from __future__ import annotations

from mcp_server.skills.file_transfer.operations import (
    delete_upload_op,
    get_upload_op,
    list_uploads_op,
    request_download_op,
    request_upload_op,
)
from mcp_server.skills.file_transfer.routes import download_route, upload_route


def register(mcp):
    @mcp.tool(tags={"core", "files"}, name="request_upload")
    def request_upload_tool(
        filename: str, size_bytes: int, sha256: str = "", kind: str = "auto",
    ):
        """Get a one-time URL to upload a LOCAL file to the remote server.

        Use when a file the server needs (an .osm model, custom measure .zip,
        weather .epw/.ddy/.stat, FloorspaceJS .json) lives on your machine, not
        on the server. Workflow:
          1. request_upload(filename, size_bytes[, sha256, kind])
          2. PUT the raw bytes to the returned upload_url, e.g.
             curl --upload-file model.osm "<upload_url>"
          3. get_upload(file_id) -> server_path (or extracted_path for a .zip)
          4. pass that path to load_osm_model / apply_measure / change_building_location

        A .zip (or kind="measure") is auto-extracted server-side, guarded against
        zip bombs and path escapes; extracted_path points at the measure dir.

        Args:
            filename: Original name (used for display + type detection; never as a path)
            size_bytes: Exact size of the file in bytes (enforced + quota-checked)
            sha256: Optional lowercase hex sha256; verified on upload if given
            kind: "auto" (default), "osm", "weather", "measure", "archive",
                "floorplan", "osw", "other"
        """
        return request_upload_op(filename=filename, size_bytes=size_bytes,
                                 sha256=sha256, kind=kind)

    @mcp.tool(tags={"files"}, name="get_upload")
    def get_upload_tool(file_id: str):
        """Check an upload's status and get its server-side path.

        Returns ready=True with server_path once the PUT completes. For an
        extracted archive, extracted_path is the measure/contents dir.

        Args:
            file_id: The id returned by request_upload
        """
        return get_upload_op(file_id=file_id)

    @mcp.tool(tags={"files"}, name="list_uploads")
    def list_uploads_tool():
        """List your uploaded files (file_id, filename, status, server_path)."""
        return list_uploads_op()

    @mcp.tool(tags={"files"}, name="delete_upload")
    def delete_upload_tool(file_id: str):
        """Delete an uploaded file and free its quota.

        Args:
            file_id: The id returned by request_upload
        """
        return delete_upload_op(file_id=file_id)

    @mcp.tool(tags={"files"}, name="request_download")
    def request_download_tool(
        path: str | None = None, run_id: str | None = None, bundle: bool = False,
    ):
        """Get a one-time URL to download a server file back to your machine.

        Use for binary/large outputs (saved .osm, HTML reports, CSVs). For small
        text, read_file is simpler. GET the returned download_url, e.g.
        curl -O -J "<download_url>".

        Args:
            path: Absolute server path to a single file (your run dir, or the
                shared read-only roots e.g. bundled measures)
            run_id: With bundle=True, zip this run's reports/ for download
            bundle: If True, bundle a run's reports into one .zip (requires run_id)
        """
        return request_download_op(path=path, run_id=run_id, bundle=bundle)

    # Out-of-band byte channel on the same app/port. Authorization is the signed
    # URL (these routes are NOT behind the MCP auth verifier). Guarded so skill
    # registration still works under the mock-MCP objects used by the tool-router
    # index and tag tests (which don't implement custom_route).
    if hasattr(mcp, "custom_route"):
        mcp.custom_route("/files/u/{file_id}", methods=["PUT"])(upload_route)
        mcp.custom_route("/files/d/{name}", methods=["GET"])(download_route)

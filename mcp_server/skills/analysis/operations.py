from __future__ import annotations

import json
import mimetypes
import os
import re
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


DONE_STATUSES = {"completed", "complete", "succeeded", "success", "finished"}
FAILED_STATUSES = {"failed", "error", "cancelled", "canceled"}
SUPPORTED_DISTRIBUTIONS = {"discrete", "uniform", "triangle", "normal", "lognormal", "integer_sequence"}


def _server_url(server_url: str | None = None) -> str:
    url = server_url or os.environ.get("OPENSTUDIO_SERVER_URL") or os.environ.get("OS_SERVER_URL")
    if not url:
        raise ValueError("Missing server_url. Pass server_url or set OPENSTUDIO_SERVER_URL.")
    return url.rstrip("/")


def _auth_headers() -> dict[str, str]:
    token = os.environ.get("OPENSTUDIO_API_TOKEN") or os.environ.get("OS_SERVER_API_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _url(server_url: str, path: str) -> str:
    return f"{server_url}/{path.lstrip('/')}"


def _read_json(path: str | Path) -> dict[str, Any]:
    p = Path(path).expanduser().resolve()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"JSON file not found: {p}") from None
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {p}: {e}") from None
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {p}")
    return data


def _write_json(path: str | Path, data: dict[str, Any]) -> str:
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return str(p)


def _text(parent: ET.Element, path: str, default: str | None = None) -> str | None:
    child = parent.find(path)
    if child is None or child.text is None:
        return default
    return child.text.strip()


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower() or "measure"


def _measure_type(root: ET.Element) -> str:
    for attr in root.findall("./attributes/attribute"):
        if _text(attr, "name") == "Measure Type":
            return _text(attr, "value", "ModelMeasure") or "ModelMeasure"
    return "ModelMeasure"


def _coerce_value(value_type: str, value: Any) -> Any:
    if value is None:
        return None
    kind = value_type.lower()
    if kind == "double":
        return float(value)
    if kind == "integer":
        return int(value)
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"true", "1", "yes", "y"}
    return str(value)


def _read_measure_metadata(measure_dir: str | Path) -> dict[str, Any]:
    measure_path = Path(measure_dir).expanduser().resolve()
    if not measure_path.is_dir():
        raise ValueError(f"Measure directory not found: {measure_path}")
    xml_path = measure_path / "measure.xml"
    if not xml_path.is_file():
        raise ValueError(f"measure.xml not found in measure directory: {measure_path}")

    root = ET.parse(xml_path).getroot()
    arguments: list[dict[str, Any]] = []
    for arg in root.findall("./arguments/argument"):
        raw_type = (_text(arg, "type", "String") or "String").lower()
        value_type = "string" if raw_type == "choice" else raw_type
        default_value = _coerce_value(value_type, _text(arg, "default_value"))
        display_name = _text(arg, "display_name") or _text(arg, "name", "Argument") or "Argument"
        arguments.append(
            {
                "display_name": display_name,
                "display_name_short": display_name,
                "name": _text(arg, "name", "") or "",
                "value_type": value_type,
                "default_value": default_value,
                "value": default_value,
            }
        )

    display_name = _text(root, "display_name") or _text(root, "name", measure_path.name) or measure_path.name
    return {
        "measure_path": measure_path,
        "name": _text(root, "name", measure_path.name) or measure_path.name,
        "display_name": display_name,
        "class_name": _text(root, "class_name"),
        "uid": _text(root, "uid") or str(uuid.uuid4()),
        "version_id": _text(root, "version_id") or str(uuid.uuid4()),
        "description": _text(root, "description"),
        "measure_type": _measure_type(root),
        "arguments": arguments,
    }


def _validate_distribution(distribution: dict[str, Any]) -> dict[str, Any]:
    dist = dict(distribution)
    if "mean" in dist and "mode" not in dist:
        dist["mode"] = dist["mean"]
    dist_type = str(dist.get("type", "")).lower()
    if dist_type not in SUPPORTED_DISTRIBUTIONS:
        raise ValueError(
            f"Unsupported distribution type '{dist.get('type')}'. "
            f"Use one of: {', '.join(sorted(SUPPORTED_DISTRIBUTIONS))}."
        )
    for key in ("minimum", "maximum", "mode"):
        if key not in dist:
            raise ValueError(f"Distribution '{dist_type}' is missing required key '{key}'.")
    if dist_type in {"normal", "lognormal"} and "standard_deviation" not in dist:
        raise ValueError(f"Distribution '{dist_type}' requires standard_deviation.")
    if dist_type == "discrete":
        values = dist.get("values")
        if not isinstance(values, list) or not values:
            raise ValueError("Discrete distribution requires a non-empty values list.")
        weights = dist.get("weights")
        if weights is None:
            dist["weights"] = [1 / len(values)] * len(values)
        elif not isinstance(weights, list) or len(weights) != len(values):
            raise ValueError("Discrete distribution weights must match values length.")
    return dist


def _variable_from_spec(argument: dict[str, Any], spec: dict[str, Any], workflow_index: int) -> dict[str, Any]:
    distribution = _validate_distribution(spec.get("distribution") or spec)
    static_value = spec.get("static_value", argument.get("default_value"))
    variable_type = spec.get("variable_type", "variable")
    variable: dict[str, Any] = {
        "argument": {**argument, "value": static_value},
        "display_name": spec.get("display_name") or argument["display_name"],
        "display_name_short": (
            spec.get("display_name_short") or spec.get("display_name") or argument["display_name_short"]
        ),
        "variable_type": variable_type,
        "static_value": static_value,
        "minimum": distribution["minimum"],
        "maximum": distribution["maximum"],
        "relation_to_output": distribution.get("relation_to_output"),
        "workflow_index": workflow_index,
        "uuid": str(uuid.uuid4()),
        "version_uuid": str(uuid.uuid4()),
        "uncertainty_description": {
            "type": distribution["type"],
            "attributes": [
                {"name": "lower_bounds", "value": distribution["minimum"]},
                {"name": "upper_bounds", "value": distribution["maximum"]},
                {"name": "modes", "value": distribution["mode"]},
                {"name": "delta_x", "value": distribution.get("step_size")},
                {"name": "stddev", "value": distribution.get("standard_deviation")},
            ],
        },
    }
    variable["pivot" if variable_type == "pivot" else "variable"] = True
    if distribution["type"] == "discrete":
        variable["uncertainty_description"]["attributes"].insert(
            0,
            {
                "name": "discrete",
                "values_and_weights": [
                    {"value": value, "weight": weight}
                    for value, weight in zip(distribution["values"], distribution["weights"])
                ],
            },
        )
    return variable


def build_measure_workflow_step(
    measure_dir: str,
    *,
    arguments: dict[str, Any] | None = None,
    variables: list[dict[str, Any]] | None = None,
    instance_name: str | None = None,
    display_name: str | None = None,
) -> dict[str, Any]:
    metadata = _read_measure_metadata(measure_dir)
    measure_path = metadata["measure_path"]
    arg_by_name = {arg["name"]: dict(arg) for arg in metadata["arguments"]}
    for name, value in (arguments or {}).items():
        if name not in arg_by_name:
            raise ValueError(f"Measure '{metadata['name']}' has no argument named '{name}'.")
        arg_by_name[name]["value"] = _coerce_value(arg_by_name[name]["value_type"], value)

    variable_names = set()
    workflow_variables = []
    for index, spec in enumerate(variables or []):
        arg_name = spec.get("argument_name") or spec.get("name")
        if not arg_name:
            raise ValueError("Each variable spec must include argument_name.")
        if arg_name not in arg_by_name:
            raise ValueError(f"Measure '{metadata['name']}' has no argument named '{arg_name}'.")
        variable_names.add(arg_name)
        workflow_variables.append(_variable_from_spec(arg_by_name[arg_name], spec, index))

    static_arguments = [arg for name, arg in arg_by_name.items() if name not in variable_names]
    return {
        "measure_type": metadata["measure_type"],
        "name": instance_name or _slug(metadata["name"]),
        "display_name": display_name or metadata["display_name"],
        "measure_definition_class_name": metadata["class_name"],
        "measure_definition_directory": f"./measures/{measure_path.name}",
        "measure_definition_directory_local": str(measure_path),
        "measure_definition_display_name": metadata["display_name"],
        "measure_definition_name": metadata["name"],
        "measure_definition_name_xml": metadata["name"],
        "measure_definition_uuid": metadata["uid"],
        "measure_definition_version_uuid": metadata["version_id"],
        "uuid": metadata["uid"],
        "version_uuid": metadata["version_id"],
        "description": metadata["description"],
        "arguments": static_arguments,
        "variables": workflow_variables,
    }


def _request_json(
    method: str,
    server_url: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    timeout: int = 600,
) -> dict[str, Any]:
    headers = {"Accept": "application/json", **_auth_headers()}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = Request(_url(server_url, path), data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            if not raw:
                return {}
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {"response": parsed}
    except HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenStudio Server HTTP {e.code} for {path}: {detail}") from None
    except URLError as e:
        raise RuntimeError(f"Could not reach OpenStudio Server at {server_url}: {e.reason}") from None


def _download(
    server_url: str,
    path: str,
    output_dir: str | Path,
    fallback_name: str,
    *,
    timeout: int = 3600,
) -> dict[str, Any]:
    req = Request(_url(server_url, path), headers={"Accept": "*/*", **_auth_headers()}, method="GET")
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            disposition = resp.headers.get("content-disposition", "")
            match = re.search(r'filename="?([^";]+)"?', disposition, flags=re.IGNORECASE)
            filename = match.group(1) if match else fallback_name
            safe_name = "".join(c if c.isalnum() or c in ("-", "_", ".", " ") else "_" for c in filename).strip()
            out_dir = Path(output_dir).expanduser().resolve()
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / (safe_name or fallback_name)
            out_path.write_bytes(body)
            return {
                "ok": True,
                "output_path": str(out_path),
                "bytes": len(body),
                "content_type": resp.headers.get("content-type"),
            }
    except HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        return {"ok": False, "error": f"OpenStudio Server HTTP {e.code} for {path}: {detail}"}
    except URLError as e:
        return {"ok": False, "error": f"Could not reach OpenStudio Server at {server_url}: {e.reason}"}


def _multipart_upload(server_url: str, path: str, file_path: str | Path, *, timeout: int = 1800) -> dict[str, Any]:
    p = Path(file_path).expanduser().resolve()
    if not p.exists():
        raise ValueError(f"Upload file not found: {p}")

    boundary = f"----openstudio-mcp-{uuid.uuid4().hex}"
    content_type = mimetypes.guess_type(str(p))[0] or "application/zip"
    parts = [
        f"--{boundary}\r\n".encode(),
        (
            f'Content-Disposition: form-data; name="file"; filename="{p.name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode(),
        p.read_bytes(),
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    body = b"".join(parts)
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body)),
        "Accept": "application/json",
        **_auth_headers(),
    }
    req = Request(_url(server_url, path), data=body, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw) if raw.strip() else {}
            return {"ok": True, "status": resp.status, "response": parsed}
    except HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        return {"ok": False, "error": f"OpenStudio Server HTTP {e.code} for upload: {detail}"}


def create_osa_json(
    output_path: str,
    analysis_name: str,
    analysis_type: str = "single_run",
    workflow: list[dict[str, Any]] | None = None,
    output_variables: list[dict[str, Any]] | None = None,
    algorithm: dict[str, Any] | None = None,
    extra_analysis_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    analysis_uuid = str(uuid.uuid4())
    machine_name = re.sub(r"[^a-zA-Z0-9_]+", "_", analysis_name).strip("_").lower() or "analysis"
    analysis = {
        "display_name": analysis_name,
        "name": machine_name,
        "uuid": analysis_uuid,
        "output_variables": output_variables or [],
        "problem": {
            "analysis_type": analysis_type,
            "algorithm": algorithm or {},
            "workflow": workflow or [],
        },
    }
    if extra_analysis_fields:
        analysis.update(extra_analysis_fields)

    path = _write_json(output_path, {"analysis": analysis})
    return {"ok": True, "osa_json_path": path, "analysis_id": analysis_uuid, "analysis": analysis}


def create_osa_json_from_measures(
    output_path: str,
    analysis_name: str,
    measure_specs: list[dict[str, Any]],
    analysis_type: str = "batch_run",
    algorithm: dict[str, Any] | None = None,
    output_variables: list[dict[str, Any]] | None = None,
    extra_analysis_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create an OSA JSON file from measure directories and variable specs."""
    try:
        workflow = [
            build_measure_workflow_step(
                spec["measure_dir"],
                arguments=spec.get("arguments"),
                variables=spec.get("variables"),
                instance_name=spec.get("instance_name"),
                display_name=spec.get("display_name"),
            )
            for spec in measure_specs
        ]
        return create_osa_json(
            output_path=output_path,
            analysis_name=analysis_name,
            analysis_type=analysis_type,
            workflow=workflow,
            output_variables=output_variables,
            algorithm=algorithm,
            extra_analysis_fields=extra_analysis_fields,
        )
    except (KeyError, ValueError) as e:
        return {"ok": False, "error": str(e)}


def add_measure_to_osa_json(
    osa_json_path: str,
    measure_dir: str,
    arguments: dict[str, Any] | None = None,
    variables: list[dict[str, Any]] | None = None,
    instance_name: str | None = None,
    display_name: str | None = None,
) -> dict[str, Any]:
    """Append a measure workflow step to an existing OSA JSON file."""
    try:
        data = _read_json(osa_json_path)
        analysis = data.setdefault("analysis", {})
        problem = analysis.setdefault("problem", {})
        workflow = problem.setdefault("workflow", [])
        if not isinstance(workflow, list):
            return {"ok": False, "error": "analysis.problem.workflow must be an array."}
        step = build_measure_workflow_step(
            measure_dir,
            arguments=arguments,
            variables=variables,
            instance_name=instance_name,
            display_name=display_name,
        )
        workflow.append(step)
        path = _write_json(osa_json_path, data)
        return {"ok": True, "osa_json_path": path, "workflow_count": len(workflow), "measure_step": step}
    except ValueError as e:
        return {"ok": False, "error": str(e)}


def validate_osa_json(osa_json_path: str) -> dict[str, Any]:
    issues: list[str] = []
    try:
        data = _read_json(osa_json_path)
    except ValueError as e:
        return {"ok": False, "error": str(e), "issues": [str(e)]}

    analysis = data.get("analysis")
    if not isinstance(analysis, dict):
        issues.append("Root object must contain an analysis object.")
        analysis = {}

    if not analysis.get("name"):
        issues.append("analysis.name is missing.")
    if not analysis.get("uuid"):
        issues.append("analysis.uuid is missing.")

    problem = analysis.get("problem")
    if not isinstance(problem, dict):
        issues.append("analysis.problem must be an object.")
        problem = {}

    if not problem.get("analysis_type"):
        issues.append("analysis.problem.analysis_type is missing.")
    if "workflow" in problem and not isinstance(problem["workflow"], list):
        issues.append("analysis.problem.workflow must be an array when present.")
    if "output_variables" in analysis and not isinstance(analysis["output_variables"], list):
        issues.append("analysis.output_variables must be an array when present.")

    return {
        "ok": not issues,
        "issues": issues,
        "osa_json_path": str(Path(osa_json_path).expanduser().resolve()),
        "analysis_id": analysis.get("uuid"),
        "analysis_type": problem.get("analysis_type"),
    }


def create_project(project_name: str, server_url: str | None = None) -> dict[str, Any]:
    base = _server_url(server_url)
    response = _request_json("POST", base, "/projects.json", body={"project": {"name": project_name}}, timeout=600)
    project_id = response.get("_id") or response.get("id") or response.get("uuid")
    if not project_id:
        return {"ok": False, "error": "Project response did not include _id/id/uuid.", "response": response}
    return {"ok": True, "project_id": str(project_id), "response": response}


def submit_analysis(
    project_id: str,
    osa_json_path: str,
    server_url: str | None = None,
    analysis_name: str | None = None,
    upload_zip_path: str | None = None,
) -> dict[str, Any]:
    validation = validate_osa_json(osa_json_path)
    if not validation["ok"]:
        return {"ok": False, "error": "OSA JSON validation failed.", "validation": validation}

    base = _server_url(server_url)
    formulation = _read_json(osa_json_path)
    if analysis_name:
        formulation["analysis"]["name"] = analysis_name

    response = _request_json(
        "POST",
        base,
        f"/projects/{quote(project_id)}/analyses.json",
        body=formulation,
        timeout=600,
    )
    analysis_id = response.get("_id") or response.get("id") or response.get("uuid") or validation.get("analysis_id")
    if not analysis_id:
        return {"ok": False, "error": "Analysis response did not include _id/id/uuid.", "response": response}

    upload = None
    if upload_zip_path:
        upload = _multipart_upload(base, f"/analyses/{quote(str(analysis_id))}/upload.json", upload_zip_path)
        if not upload.get("ok"):
            return {"ok": False, "error": "Analysis created but ZIP upload failed.", "analysis_id": analysis_id, "upload": upload}

    return {"ok": True, "analysis_id": str(analysis_id), "response": response, "upload": upload}


def get_analysis_status(
    analysis_id: str,
    server_url: str | None = None,
    analysis_type: str | None = None,
) -> dict[str, Any]:
    base = _server_url(server_url)
    response = _request_json("GET", base, f"/analyses/{quote(analysis_id)}/status.json", timeout=300)
    analysis = response.get("analysis") if isinstance(response.get("analysis"), dict) else {}
    status = str(analysis.get("status") or response.get("status") or "unknown").lower()
    response_analysis_type = analysis.get("analysis_type")
    type_matches = analysis_type is None or response_analysis_type in (analysis_type, "batch_run")
    return {
        "ok": True,
        "analysis_id": analysis_id,
        "status": status,
        "analysis_type": response_analysis_type,
        "type_matches": type_matches,
        "done": status in DONE_STATUSES,
        "failed": status in FAILED_STATUSES,
        "response": response,
    }


def wait_for_analysis(
    analysis_id: str,
    server_url: str | None = None,
    analysis_type: str | None = None,
    poll_interval_seconds: int = 60,
    timeout_seconds: int = 86400,
) -> dict[str, Any]:
    started = time.monotonic()
    last_status: dict[str, Any] | None = None
    while time.monotonic() - started <= timeout_seconds:
        last_status = get_analysis_status(analysis_id, server_url=server_url, analysis_type=analysis_type)
        if last_status["done"]:
            return {"ok": True, **last_status}
        if last_status["failed"]:
            return {"ok": False, "error": f"Analysis failed with status {last_status['status']}.", **last_status}
        time.sleep(poll_interval_seconds)

    return {
        "ok": False,
        "error": f"Timed out after {timeout_seconds}s waiting for analysis {analysis_id}.",
        "last_status": last_status,
    }


def download_analysis_data(
    analysis_id: str,
    output_dir: str,
    server_url: str | None = None,
    file_format: str = "csv",
) -> dict[str, Any]:
    base = _server_url(server_url)
    query = urlencode({"export": "true"})
    return _download(
        base,
        f"/analyses/{quote(analysis_id)}/download_data.{quote(file_format)}?{query}",
        output_dir,
        f"analysis_{analysis_id}_data.{file_format}",
    )


def get_analysis_results_json(analysis_id: str, server_url: str | None = None) -> dict[str, Any]:
    base = _server_url(server_url)
    return _request_json("GET", base, f"/analyses/{quote(analysis_id)}/analysis_data.json", timeout=600)


def submit_wait_download(
    project_id: str,
    osa_json_path: str,
    output_dir: str,
    server_url: str | None = None,
    analysis_name: str | None = None,
    upload_zip_path: str | None = None,
    analysis_type: str | None = None,
    poll_interval_seconds: int = 60,
    timeout_seconds: int = 86400,
    download_format: str = "csv",
) -> dict[str, Any]:
    submission = submit_analysis(
        project_id=project_id,
        osa_json_path=osa_json_path,
        server_url=server_url,
        analysis_name=analysis_name,
        upload_zip_path=upload_zip_path,
    )
    if not submission.get("ok"):
        return {"ok": False, "stage": "submit", "submission": submission}

    analysis_id = submission["analysis_id"]
    status = wait_for_analysis(
        analysis_id,
        server_url=server_url,
        analysis_type=analysis_type,
        poll_interval_seconds=poll_interval_seconds,
        timeout_seconds=timeout_seconds,
    )
    if not status.get("ok"):
        return {"ok": False, "stage": "wait", "submission": submission, "status": status}

    download = download_analysis_data(analysis_id, output_dir, server_url=server_url, file_format=download_format)
    return {
        "ok": bool(download.get("ok")),
        "stage": "complete" if download.get("ok") else "download",
        "submission": submission,
        "status": status,
        "download": download,
    }

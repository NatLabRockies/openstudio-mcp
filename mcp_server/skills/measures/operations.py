"""Measure operations — list arguments and apply measures.

Uses the OSW-based approach: save model → build OSW with measure step →
run `openstudio run -w` → reload resulting model. This avoids Ruby script
execution complexity and uses the well-tested OSW runner.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import zipfile
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urljoin, urlparse
from urllib.request import Request, urlopen
from pathlib import Path
from typing import Any

import openstudio

from mcp_server import sandbox
from mcp_server.config import (
    COMMON_MEASURES_DIR,
    COMSTOCK_MEASURES_DIR,
    INPUT_ROOT,
    OSCLI_GEM_PATH,
    OSCLI_GEMFILE,
    is_path_allowed,
    user_bcl_measures_dir,
    user_custom_measures_dir,
    user_measures_root,
    user_run_root,
)
from mcp_server.model_manager import get_model, load_model
from mcp_server.skills.measures.osw_weather import resolve_osw_weather
from mcp_server.util import create_run_dir, reject_escaping_symlinks, resolve_run_dir


MEASURE_DOWNLOAD_HOSTS = {"bcl.nrel.gov", "bcl.nlr.gov", "github.com", "raw.githubusercontent.com"}
BCL_SEARCH_HOST = "https://bcl.nlr.gov"
MATCH_STOPWORDS = {"measure", "details"}


class _BCLDownloadLinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.download_links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attr_map = dict(attrs)
        href = attr_map.get("href") or ""
        if "/api/download?" in href:
            self.download_links.append(href)


def _is_measure_dir(path: Path) -> bool:
    return path.is_dir() and ((path / "measure.rb").is_file() or (path / "measure.py").is_file())


def _measure_entry(path: Path, source: str) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "name": path.name,
        "measure_dir": str(path),
        "source": source,
        "has_measure_xml": (path / "measure.xml").is_file(),
    }
    try:
        bcl = openstudio.BCLMeasure(openstudio.toPath(str(path)))
        entry["display_name"] = bcl.name()
        entry["description"] = bcl.description()[:300]
        entry["measure_type"] = bcl.measureType().valueName()
        entry["num_arguments"] = len(bcl.arguments())
    except Exception:
        entry["display_name"] = path.name
        entry["description"] = ""
        entry["measure_type"] = None
        entry["num_arguments"] = -1
    return entry


def _iter_measure_dirs(root: Path, max_depth: int) -> list[Path]:
    if _is_measure_dir(root):
        return [root]

    found: list[Path] = []
    root = root.resolve()
    base_depth = len(root.parts)

    for dirpath, dirnames, _filenames in os.walk(root):
        depth = len(Path(dirpath).parts) - base_depth
        if depth > max_depth:
            dirnames[:] = []
            continue

        p = Path(dirpath)
        if _is_measure_dir(p):
            found.append(p)
            dirnames[:] = []  # don't descend into a measure dir

    return found


def _safe_extract_zip(zip_path: Path, output_dir: Path) -> list[Path]:
    extracted: list[Path] = []
    output_root = output_dir.resolve()
    max_members = 10_000
    max_uncompressed_bytes = 500 * 1024 * 1024  # 500 MiB

    with zipfile.ZipFile(zip_path) as archive:
        members = archive.infolist()
        if len(members) > max_members:
            raise ValueError(f"ZIP contains too many files ({len(members)} > {max_members})")

        total = 0
        for member in members:
            total += int(getattr(member, "file_size", 0) or 0)
            if total > max_uncompressed_bytes:
                raise ValueError("ZIP uncompressed size is too large")

            target = (output_root / member.filename).resolve()
            if not (str(target).startswith(str(output_root) + os.sep) or target == output_root):
                raise ValueError(f"ZIP member would extract outside destination: {member.filename}")

        archive.extractall(output_root)
        extracted = [(output_root / member.filename).resolve() for member in members]

    return extracted


def _guess_download_name(url: str, fallback: str = "downloaded_measure.zip") -> str:
    name = Path(unquote(urlparse(url).path)).name
    return name or fallback


def _read_url(url: str, timeout_seconds: int) -> tuple[bytes, str]:
    req = Request(url, headers={"User-Agent": "openstudio-mcp/measure-downloader"}, method="GET")
    with urlopen(req, timeout=timeout_seconds) as resp:
        final_url = getattr(resp, "geturl", lambda: url)()
        parsed = urlparse(final_url)
        if parsed.scheme != "https" or parsed.hostname not in MEASURE_DOWNLOAD_HOSTS:
            raise ValueError(f"Redirected download host not allowed: {parsed.hostname}")
        headers = getattr(resp, "headers", {})
        content_type = headers.get("Content-Type", "") if headers else ""
        return resp.read(), content_type


def _looks_like_html(payload: bytes, content_type: str) -> bool:
    head = payload[:500].lstrip().lower()
    return "html" in content_type.lower() or head.startswith(b"<!doctype html") or head.startswith(b"<html")


def _resolve_bcl_content_download(url: str, payload: bytes) -> str | None:
    parsed = urlparse(url)
    if parsed.hostname not in {"bcl.nrel.gov", "bcl.nlr.gov"}:
        return None
    parser = _BCLDownloadLinkParser()
    parser.feed(payload.decode("utf-8", errors="replace"))
    if not parser.download_links:
        return None
    return urljoin(url, parser.download_links[0])


def _search_text(value: Any) -> str:
    return str(value or "").lower().replace("_", " ").replace("-", " ")


def _search_tokens(value: Any) -> set[str]:
    token = ""
    tokens = set()
    for char in _search_text(value):
        if char.isalnum():
            token += char
        elif token:
            if token not in MATCH_STOPWORDS:
                tokens.add(token)
            token = ""
    if token and token not in MATCH_STOPWORDS:
        tokens.add(token)
    return tokens


def _measure_match_score(query: str, candidate: dict[str, Any]) -> float:
    query_tokens = _search_tokens(query)
    if not query_tokens:
        return 0.0

    query_norm = " ".join(sorted(query_tokens))
    best_norm_score = 0.0
    for key in ("display_name", "name", "class_name"):
        candidate_norm = " ".join(sorted(_search_tokens(candidate.get(key))))
        if not candidate_norm:
            continue
        matched = query_tokens & _search_tokens(candidate.get(key))
        coverage = len(matched) / len(query_tokens)
        extra_penalty = max(len(_search_tokens(candidate.get(key))) - len(query_tokens), 0) * 0.02
        norm_score = 1.0 if candidate_norm == query_norm else max(0.0, coverage - extra_penalty)
        best_norm_score = max(best_norm_score, norm_score)

    description_tokens = _search_tokens(candidate.get("description")) | _search_tokens(candidate.get("modeler_description"))
    description_bonus = min(len(query_tokens & description_tokens) / len(query_tokens), 0.25)
    return min(best_norm_score + description_bonus, 1.0)


def _rank_measure_matches(query: str, measures: list[dict[str, Any]], max_results: int) -> list[dict[str, Any]]:
    ranked = []
    for measure in measures:
        entry = dict(measure)
        entry["match_score"] = round(_measure_match_score(query, entry), 3)
        ranked.append(entry)
    ranked.sort(key=lambda m: m["match_score"], reverse=True)
    return ranked[:max_results]


def _measure_next_steps(measure_dir: str | None) -> dict[str, Any]:
    if not measure_dir:
        return {}
    return {
        "list_arguments": {
            "tool": "list_measure_arguments",
            "arguments": {"measure_dir": measure_dir},
        },
        "apply": {
            "tool": "apply_measure",
            "arguments": {"measure_dir": measure_dir},
        },
    }


def _selected_measure_response(
    *,
    source: str,
    query: str | None,
    match: dict[str, Any],
    downloaded: bool,
    measure_dir: str | None = None,
    download: dict[str, Any] | None = None,
    local_matches: list[dict[str, Any]] | None = None,
    bcl_matches: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    selected = dict(match)
    selected_measure_dir = measure_dir or selected.get("measure_dir")
    if selected_measure_dir:
        selected["measure_dir"] = selected_measure_dir

    response: dict[str, Any] = {
        "ok": True,
        "source": source,
        "query": query,
        "selected_measure": selected,
        "match": selected,
        "measure_dir": selected_measure_dir,
        "downloaded": downloaded,
        "next": _measure_next_steps(selected_measure_dir),
    }
    if selected_measure_dir:
        response["selected_measure_dir"] = selected_measure_dir
    if selected.get("download_url"):
        response["download_url"] = selected.get("download_url")
    if local_matches is not None:
        response["local_matches"] = local_matches
    if bcl_matches is not None:
        response["bcl_matches"] = bcl_matches
    if download is not None:
        response["download"] = download
    return response


def _bcl_measure_entry(raw: dict[str, Any]) -> dict[str, Any]:
    measure = raw.get("measure", raw)
    return {
        "name": measure.get("name"),
        "display_name": measure.get("display_name") or measure.get("name"),
        "description": (measure.get("description") or "")[:500],
        "modeler_description": (measure.get("modeler_description") or "")[:500],
        "class_name": measure.get("class_name"),
        "measure_type": _attribute_value(measure, "Measure Type"),
        "uuid": measure.get("uuid"),
        "version_id": measure.get("version_id"),
        "release_tag": measure.get("release_tag"),
        "repo": measure.get("repo"),
        "org": measure.get("org"),
        "measure_url": measure.get("measure_url"),
        "readme_url": measure.get("readme_url"),
        "download_url": measure.get("download_url"),
        "source": "bcl",
    }


def _attribute_value(measure: dict[str, Any], name: str) -> str | None:
    attrs = measure.get("attributes", {}).get("attribute", [])
    if isinstance(attrs, dict):
        attrs = [attrs]
    for attr in attrs:
        if attr.get("name") == name:
            return attr.get("value")
    return None


def _bcl_search_urls(term: str, *, page: int, show_rows: int) -> tuple[str, str]:
    wildcard_term = f"*{quote(term, safe='')}*"
    query = f"fq=bundle:measure&page={page}&show_rows={show_rows}"
    api_url = f"{BCL_SEARCH_HOST}/api/search/{wildcard_term}.json?{query}"
    results_url = f"{BCL_SEARCH_HOST}/results/{wildcard_term}?fq=bundle:measure&page={page}"
    return api_url, results_url


def search_bcl_measures(
    query: str,
    max_results: int = 10,
    timeout_seconds: int = 60,
    page: int = 0,
) -> dict[str, Any]:
    """Search BCL for measures and rank the returned candidates locally."""
    try:
        query = query.strip()
        if not query:
            return {"ok": False, "error": "query is required"}

        search_terms = [
            query,
            " ".join(token for token in _search_text(query).split() if token not in MATCH_STOPWORDS),
        ]
        seen_terms = set()
        candidates_by_uuid: dict[str, dict[str, Any]] = {}
        search_urls = []
        result_urls = []
        for term in search_terms:
            term = term.strip()
            if not term or term in seen_terms:
                continue
            seen_terms.add(term)
            url, results_url = _bcl_search_urls(term, page=page, show_rows=max(max_results * 3, 10))
            search_urls.append(url)
            result_urls.append(results_url)
            payload, _content_type = _read_url(url, timeout_seconds)
            data = json.loads(payload.decode("utf-8"))
            for item in data.get("result", []):
                entry = _bcl_measure_entry(item)
                key = entry.get("uuid") or entry.get("download_url") or entry.get("name")
                if key and key not in candidates_by_uuid:
                    candidates_by_uuid[key] = entry

        ranked = _rank_measure_matches(query, list(candidates_by_uuid.values()), max_results)
        best_match = ranked[0] if ranked else None
        return {
            "ok": True,
            "query": query,
            "count": len(ranked),
            "best_match": best_match,
            "download_url": best_match.get("download_url") if best_match else None,
            "search_urls": search_urls,
            "result_urls": result_urls,
            "measures": ranked,
        }
    except HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        return {"ok": False, "error": f"BCL search failed with HTTP {e.code}: {detail[:500]}"}
    except URLError as e:
        return {"ok": False, "error": f"Could not search BCL: {e.reason}"}
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"BCL search returned invalid JSON: {e}"}
    except Exception as e:
        return {"ok": False, "error": f"Failed to search BCL: {e}"}


def find_measure(
    query: str,
    download_if_bcl_match: bool = True,
    min_match_score: float = 0.72,
    max_results: int = 10,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    """Find a measure locally first, then in BCL, optionally downloading a good BCL match."""
    try:
        query = query.strip()
        if not query:
            return {"ok": False, "error": "query is required"}

        local = list_local_measures(max_results=500)
        if not local.get("ok"):
            return local

        local_matches = _rank_measure_matches(query, local.get("measures", []), max_results)
        best_local = local_matches[0] if local_matches else None
        if best_local and best_local["match_score"] >= min_match_score:
            return _selected_measure_response(
                source="local",
                query=query,
                match=best_local,
                downloaded=False,
                local_matches=local_matches,
            )

        bcl = search_bcl_measures(query=query, max_results=max_results, timeout_seconds=timeout_seconds)
        if not bcl.get("ok"):
            return {
                "ok": False,
                "error": bcl.get("error", "BCL search failed"),
                "query": query,
                "best_local_match": best_local,
                "local_matches": local_matches,
            }

        best_bcl = bcl["measures"][0] if bcl.get("measures") else None
        if not best_bcl or best_bcl["match_score"] < min_match_score:
            return {
                "ok": False,
                "error": "No local or BCL measure matched the query above the threshold.",
                "query": query,
                "min_match_score": min_match_score,
                "best_local_match": best_local,
                "bcl_matches": bcl.get("measures", []),
                "bcl_search_urls": bcl.get("search_urls", []),
            }

        if not download_if_bcl_match:
            return _selected_measure_response(
                source="bcl",
                query=query,
                match=best_bcl,
                downloaded=False,
                local_matches=local_matches,
                bcl_matches=bcl.get("measures", []),
            )

        download_url = best_bcl.get("download_url")
        if not download_url:
            return {
                "ok": False,
                "error": "Best BCL match did not include a download_url.",
                "query": query,
                "match": best_bcl,
                "bcl_matches": bcl.get("measures", []),
            }

        download = download_measure_archive(
            url=download_url,
            measure_name=best_bcl.get("name") or best_bcl.get("display_name"),
            timeout_seconds=timeout_seconds,
        )
        if not download.get("ok"):
            return {
                "ok": False,
                "error": download.get("error", "Failed to download BCL measure."),
                "query": query,
                "match": best_bcl,
                "download": download,
            }

        selected_download = download["measures"][0] if download.get("measures") else {}
        selected = dict(best_bcl)
        if selected_download.get("measure_dir"):
            selected["measure_dir"] = selected_download["measure_dir"]
        if selected_download.get("name"):
            selected["downloaded_name"] = selected_download["name"]
        return _selected_measure_response(
            source="bcl",
            query=query,
            match=selected,
            downloaded=True,
            measure_dir=selected_download.get("measure_dir"),
            download=download,
            local_matches=local_matches,
            bcl_matches=bcl.get("measures", []),
        )
    except Exception as e:
        return {"ok": False, "error": f"Failed to find measure: {e}"}


def list_local_measures(
    root_dir: str | None = None,
    max_depth: int = 3,
    max_results: int = 200,
) -> dict[str, Any]:
    """List measures in mounted/user/bundled measure directories."""
    try:
        if root_dir:
            requested = Path(root_dir).expanduser().resolve()
            if not is_path_allowed(requested):
                return {"ok": False, "error": f"Directory not allowed: {requested}"}
            roots = [(requested, "requested")]
        else:
            # Per-user roots first (the caller's own authored + downloaded measures),
            # then bundled libraries, then the caller's BCL cache. Custom comes before
            # bundled/BCL so an agent prefers a measure the user authored; BCL last so
            # bundled checkouts win over a downloaded copy. All identity-scoped — no
            # tenant's measures appear in another's listing.
            roots = [
                (user_custom_measures_dir(), "custom"),
                ((user_run_root() / "custom_measures").resolve(), "legacy_custom"),
                (COMMON_MEASURES_DIR.resolve(), "common"),
                (COMSTOCK_MEASURES_DIR.resolve(), "comstock"),
                ((INPUT_ROOT / "measures").resolve(), "inputs"),
                (user_bcl_measures_dir(), "bcl"),
                ((INPUT_ROOT / "measures" / "bcl").resolve(), "legacy_bcl"),
            ]

        results = []
        seen = set()
        for root, source in roots:
            if not root.is_dir():
                continue
            # Internal default roots are the caller's own or shared-readable, so skip
            # any that resolve as not-allowed rather than erroring (an error would also
            # leak that another tenant's dir exists). A user-supplied root_dir is
            # validated up front above.
            if not is_path_allowed(root):
                continue
            for measure_dir in _iter_measure_dirs(root, max_depth=max_depth):
                resolved = measure_dir.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                results.append(_measure_entry(resolved, source))
                if len(results) >= max_results:
                    return {"ok": True, "count": len(results), "truncated": True, "measures": results}

        return {"ok": True, "count": len(results), "truncated": False, "measures": results}
    except Exception as e:
        return {"ok": False, "error": f"Failed to list local measures: {e}"}


def download_measure_archive(
    url: str,
    output_dir: str | None = None,
    measure_name: str | None = None,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    """Download and safely extract a measure ZIP into a writable measure directory."""
    try:
        parsed = urlparse(url)
        if parsed.scheme != "https":
            return {"ok": False, "error": "Only HTTPS measure downloads are allowed."}
        if parsed.hostname not in MEASURE_DOWNLOAD_HOSTS:
            allowed = ", ".join(sorted(MEASURE_DOWNLOAD_HOSTS))
            return {"ok": False, "error": f"Download host not allowed: {parsed.hostname}. Allowed: {allowed}"}

        destination_root = Path(output_dir).expanduser().resolve() if output_dir else user_bcl_measures_dir()
        measures_root = user_measures_root()
        if not (destination_root == measures_root or str(destination_root).startswith(str(measures_root) + os.sep)):
            return {"ok": False, "error": f"Output directory must be under {measures_root}: {destination_root}"}
        if not is_path_allowed(destination_root, write=True):
            return {"ok": False, "error": f"Output directory not allowed: {destination_root}"}
        destination_root.mkdir(parents=True, exist_ok=True)

        download_url = url
        payload, content_type = _read_url(download_url, timeout_seconds)
        if _looks_like_html(payload, content_type):
            resolved_url = _resolve_bcl_content_download(download_url, payload)
            if resolved_url:
                download_url = resolved_url
                payload, content_type = _read_url(download_url, timeout_seconds)

        archive_name = _guess_download_name(download_url)
        archive_path = destination_root / archive_name
        archive_path.write_bytes(payload)

        extract_root = destination_root / (measure_name or archive_path.stem)
        extract_root.mkdir(parents=True, exist_ok=True)
        _safe_extract_zip(archive_path, extract_root)

        measures = list_local_measures(root_dir=str(extract_root), max_depth=4)
        if not measures.get("ok"):
            return measures
        if measures.get("count", 0) == 0:
            return {
                "ok": False,
                "error": "Downloaded archive did not contain a measure directory with measure.rb or measure.py.",
                "archive_path": str(archive_path),
                "extract_dir": str(extract_root),
            }
        selected_measure = measures["measures"][0] if measures["measures"] else {}
        selected_measure_dir = selected_measure.get("measure_dir")
        return {
            "ok": True,
            "download_url": download_url,
            "archive_path": str(archive_path),
            "extract_dir": str(extract_root),
            "count": measures["count"],
            "selected_measure": selected_measure,
            "measure_dir": selected_measure_dir,
            "selected_measure_dir": selected_measure_dir,
            "next": _measure_next_steps(selected_measure_dir),
            "measures": measures["measures"],
        }
    except zipfile.BadZipFile:
        return {"ok": False, "error": "Downloaded file is not a valid ZIP archive."}
    except HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        return {"ok": False, "error": f"Download failed with HTTP {e.code}: {detail[:500]}"}
    except URLError as e:
        return {"ok": False, "error": f"Could not download measure archive: {e.reason}"}
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to download measure archive: {e}"}


def list_measure_arguments(measure_dir: str) -> dict[str, Any]:
    """List a measure's arguments with names, types, defaults, and choices.

    Args:
        measure_dir: Path to the measure directory (contains measure.rb)
    """
    try:
        measure_path = Path(measure_dir)
        if not measure_path.is_dir():
            return {"ok": False, "error": f"Measure directory not found: {measure_dir}"}

        # Load BCLMeasure to read metadata
        bcl = openstudio.BCLMeasure(openstudio.toPath(str(measure_path)))

        # Extract arguments from the measure XML
        args = []
        for arg in bcl.arguments():
            arg_info: dict[str, Any] = {
                "name": arg.name(),
                "display_name": arg.displayName(),
            }
            # type() may return string or enum depending on OS version
            try:
                arg_info["type"] = arg.type()
            except Exception:
                pass
            # Default value — attribute name varies by OS version
            try:
                dv = arg.defaultValue()
                if dv is not None:
                    arg_info["default_value"] = str(dv)
            except Exception:
                pass
            # Required
            try:
                arg_info["required"] = arg.required()
            except Exception:
                pass
            # Choice values
            try:
                choices = arg.choiceValues()
                if choices:
                    arg_info["choices"] = [str(c) for c in choices]
            except Exception:
                pass

            args.append(arg_info)

        return {
            "ok": True,
            "measure_name": bcl.name(),
            "measure_type": bcl.measureType().valueName(),
            "description": bcl.description(),
            "arguments": args,
        }

    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to list measure arguments: {e}"}


def _parse_runner_messages(out_osw_path: Path) -> dict[str, Any] | None:
    """Extract runner messages from out.osw step results.

    Returns dict with result, initial_condition, final_condition,
    info, warnings, errors — or None on parse failure.
    """
    try:
        if not out_osw_path.is_file():
            return None
        osw = json.loads(out_osw_path.read_text(encoding="utf-8", errors="replace"))
        steps = osw.get("steps", [])
        if not steps:
            return None
        step = steps[0]
        result = step.get("result", {})
        msgs: dict[str, Any] = {
            "result": result.get("step_result", ""),
        }
        for key in ("step_initial_condition", "step_final_condition"):
            val = result.get(key)
            if val:
                # Strip "step_" prefix for cleaner output
                msgs[key.replace("step_", "")] = val
        for key, osw_key in [("info", "step_info"), ("warnings", "step_warnings"), ("errors", "step_errors")]:
            items = result.get(osw_key, [])
            if items:
                msgs[key] = items
        return msgs
    except Exception:
        return None


def apply_measure(
    measure_dir: str,
    arguments: dict[str, Any] | None = None,
    run_id: str | None = None,
    use_bundle: bool = True,
) -> dict[str, Any]:
    """Apply an OpenStudio measure to the in-memory model.

    For ModelMeasures (default): saves model → builds OSW → runs
    `openstudio run --measures_only` → reloads model.

    For ReportingMeasures (when run_id provided): copies simulation
    artifacts (SQL, IDF) from a completed run into the measure dir,
    then runs `openstudio run --postprocess_only` so only reporting
    measures execute against the existing results.

    Args:
        measure_dir: Path to the measure directory
        arguments: Optional dict of argument_name -> value overrides
        run_id: Optional completed simulation run_id (for reporting measures)
    """
    try:
        model = get_model()
        measure_path = Path(measure_dir)
        if not measure_path.is_dir():
            return {"ok": False, "error": f"Measure directory not found: {measure_dir}"}
        # Access control: only run measures from allowed roots (own run area or a
        # shared read root — repo, inputs, bundled measures). Refuses arbitrary
        # filesystem paths / another user's area before any copy or execution.
        if not is_path_allowed(measure_path):
            return {"ok": False, "error": f"Measure directory not allowed: {measure_dir}"}

        # Reject symlinks that escape the measure dir: copytree(symlinks=True)
        # below preserves links instead of inlining target content, but a link
        # pointing outside the measure root (e.g. -> /etc/shadow) must not be
        # staged at all (it would leak host files into the readable run dir).
        err = reject_escaping_symlinks(measure_path)
        if err:
            return {"ok": False, "error": err}

        # Check measure script exists (Ruby or Python)
        has_rb = (measure_path / "measure.rb").is_file()
        has_py = (measure_path / "measure.py").is_file()
        if not has_rb and not has_py:
            return {"ok": False, "error": f"No measure.rb or measure.py found in {measure_dir}"}

        # Create temp directory for the run
        _measure_run_id, run_dir = create_run_dir(user_run_root(), "measure", measure_path.name)

        # Save current model to temp OSM
        temp_osm = run_dir / "in.osm"
        model.save(str(temp_osm), True)

        # Copy measure into run dir so OSW can reference it by relative path
        measures_dir = run_dir / "measures"
        measures_dir.mkdir(exist_ok=True)
        local_measure = measures_dir / measure_path.name
        # symlinks=True: copy links AS links (don't follow → no host-file content
        # inlined into the run dir); escaping links already rejected above.
        shutil.copytree(str(measure_path), str(local_measure), dirs_exist_ok=True, symlinks=True)

        # Build measure step arguments
        measure_args = {}
        if arguments:
            measure_args = {k: str(v) for k, v in arguments.items()}

        # Resolve the model's weather reference so the OSW runner's
        # Initialization state doesn't abort on a bare/stale EPW url —
        # the runner validates weather even for --measures_only.
        # Tiers: resolvable url -> file_paths; basename in known weather
        # dirs -> staged into files/; unfindable -> stripped from seed
        # (snapshot restored onto the reloaded model below)
        weather = resolve_osw_weather(model, run_dir, temp_osm)
        file_paths = weather["file_paths"]
        osw_weather_file = weather["weather_file"]

        # Also add directories of any EPW paths passed as arguments
        # (e.g. ChangeBuildingLocation's weather_file_name argument).
        # An explicit argument EPW overrides model-based resolution.
        if arguments:
            for v in arguments.values():
                v_str = str(v)
                if v_str.endswith(".epw") and Path(v_str).is_file():
                    parent = str(Path(v_str).parent)
                    if parent not in file_paths:
                        file_paths.append(parent)
                    osw_weather_file = v_str

        # Build minimal OSW — use relative path to local copy
        osw = {
            "seed_file": str(temp_osm),
            "file_paths": file_paths,
            "measure_paths": [str(measures_dir)],
            "steps": [
                {
                    "measure_dir_name": measure_path.name,
                    "arguments": measure_args,
                },
            ],
        }
        # If an EPW was found in arguments, set it in the OSW so the runner
        # doesn't fail trying to resolve a stale weather reference from the model
        if osw_weather_file:
            osw["weather_file"] = osw_weather_file

        osw_path = run_dir / "workflow.osw"
        osw_path.write_text(json.dumps(osw, indent=2), encoding="utf-8")

        # Determine run mode: --postprocess_only for reporting measures,
        # --measures_only for model/energyplus measures
        postprocess = False
        if run_id:
            try:
                sim_dir = resolve_run_dir(user_run_root(), run_id)
            except FileNotFoundError:
                return {"ok": False, "error": f"Simulation run not found: {run_id}"}
            sql_src = sim_dir / "run" / "eplusout.sql"
            if not sql_src.is_file():
                return {"ok": False, "error": f"No eplusout.sql in run {run_id} — simulation may not have completed"}
            # Stage simulation artifacts so the reporting measure can find them.
            # The OSW runner expects run/eplusout.sql, run/in.osm, run/in.idf
            ep_run = run_dir / "run"
            ep_run.mkdir(exist_ok=True)
            shutil.copy2(str(sql_src), str(ep_run / "eplusout.sql"))
            osm_src = sim_dir / "run" / "in.osm"
            if osm_src.is_file():
                shutil.copy2(str(osm_src), str(ep_run / "in.osm"))
            idf_src = sim_dir / "run" / "in.idf"
            if idf_src.is_file():
                shutil.copy2(str(idf_src), str(ep_run / "in.idf"))
            postprocess = True

        run_flag = "--postprocess_only" if postprocess else "--measures_only"
        cmd = ["openstudio"]
        if use_bundle:
            cmd += ["--bundle", OSCLI_GEMFILE,
                    "--bundle_path", OSCLI_GEM_PATH,
                    "--bundle_without", "native_ext"]
        cmd += ["run", run_flag, "-w", str(osw_path)]
        log_path = run_dir / "openstudio.log"
        # Build env first (it creates run_dir/tmp for TMPDIR as root), THEN hand
        # the whole run dir — tmp included — to the sandbox uid, so the dropped
        # process can write its temp/output. Order matters.
        run_env = sandbox.build_env(run_dir)
        sandbox.prepare_workdir(run_dir)
        with open(log_path, "w", encoding="utf-8") as log_f:
            proc = subprocess.run(
                sandbox.wrap_cmd(cmd, run_dir),
                cwd=str(run_dir),
                stdout=log_f,
                stderr=subprocess.STDOUT,
                env=run_env,
                timeout=300,  # 5 minute timeout
                check=False,
            )

        if proc.returncode != 0:
            # Read last 50 lines of log for error details
            log_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            tail = "\n".join(log_lines[-50:])
            return {
                "ok": False,
                "error": f"Measure run failed (exit code {proc.returncode})",
                "log_tail": tail,
            }

        # Parse runner messages from out.osw
        runner_messages = _parse_runner_messages(run_dir / "out.osw")

        # For reporting measures, don't reload model — just return artifacts
        if postprocess:
            result = {
                "ok": True,
                "measure_dir": str(measure_path),
                "run_dir": str(run_dir),
                "arguments_applied": measure_args,
            }
            if runner_messages:
                result["runner_messages"] = runner_messages
            return result

        # Find the output model — OpenStudio puts it in run/in.osm
        output_osm = run_dir / "run" / "in.osm"
        if not output_osm.is_file():
            # Try the original location
            output_osm = temp_osm
        if not output_osm.is_file():
            return {"ok": False, "error": "Output OSM not found after measure run"}

        # Reload model
        load_model(output_osm)

        result = {
            "ok": True,
            "measure_dir": str(measure_path),
            "run_dir": str(run_dir),
            "arguments_applied": measure_args,
        }

        # If weather was stripped from the seed, restore the original
        # reference — unless the measure set a new one (e.g.
        # ChangeBuildingLocation)
        if weather["stripped_idf"] is not None:
            reloaded = get_model()
            if reloaded.weatherFile().is_initialized():
                result["weather_note"] = (
                    "model weather reference was unresolvable; measure set a new weather file"
                )
            else:
                reloaded.addObject(weather["stripped_idf"])
                result["weather_note"] = (
                    "model weather reference was unresolvable; removed for the "
                    "measures_only run and restored afterward"
                )

        if runner_messages:
            result["runner_messages"] = runner_messages
        return result

    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Measure run timed out (5 min)"}
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to apply measure: {e}"}

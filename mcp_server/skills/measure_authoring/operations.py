"""Measure authoring operations — create, test, and edit custom measures.

Uses openstudio.BCLMeasure() for scaffolding, then patches the generated
script with user-provided arguments and run() body.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import openstudio

from mcp_server.config import INPUT_ROOT, RUN_ROOT

CUSTOM_MEASURES_DIR = RUN_ROOT / "custom_measures"

# Default test model for measure tests — rich model with HVAC, plant loops,
# constructions, schedules.  Searched in order; first hit wins.
_TEST_MODEL_CANDIDATES = [
    Path("/repo/tests/assets/SystemD_baseline.osm"),   # Docker (CI / dev)
    INPUT_ROOT / "SystemD_baseline.osm",                # Claude Desktop
]

_MEASURE_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,99}$")

# Argument type -> SDK factory method name suffix
_ARG_MAKERS = {
    "Boolean": "Bool",
    "Double": "Double",
    "Integer": "Integer",
    "String": "String",
    "Choice": "Choice",
}

# Maximum run_body size (20 KB)
_MAX_BODY_SIZE = 20 * 1024

# Markers for replaceable sections
_BEGIN_MARKER = "# --- begin user logic ---"
_END_MARKER = "# --- end user logic ---"


def _validate_measure_name(name: str) -> str | None:
    """Validate measure name is a safe identifier. Returns error string or None."""
    if not _MEASURE_NAME_RE.fullmatch(name):
        return (
            "name must be alphanumeric + underscores, start with a letter, "
            "max 100 chars (e.g. 'set_lights_8w')"
        )
    return None


def _find_test_model() -> Path | None:
    """Find the best available test model OSM for measure tests."""
    # 1. Currently loaded model — save to temp file
    try:
        from mcp_server.model_manager import get_model
        model = get_model()
        tmp = CUSTOM_MEASURES_DIR / "_test_model.osm"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        model.save(openstudio.toPath(str(tmp)), True)
        return tmp
    except Exception:
        pass
    # 2. Search known locations for SystemD_baseline.osm
    for p in _TEST_MODEL_CANDIDATES:
        if p.is_file():
            return p
    return None


def _to_class_name(snake: str) -> str:
    """Convert snake_case to PascalCase class name."""
    return "".join(w.capitalize() for w in snake.split("_"))


def _generate_ruby_arguments(args: list[dict]) -> str:
    """Generate Ruby arguments() method body."""
    lines = [
        "  def arguments(model)",
        "    args = OpenStudio::Measure::OSArgumentVector.new",
    ]
    for a in args:
        name = a["name"]
        atype = a.get("type", "String")
        required = a.get("required", True)
        req_str = "true" if required else "false"
        maker = _ARG_MAKERS.get(atype, "String")
        lines.append(f'    {name} = OpenStudio::Measure::OSArgument.make{maker}Argument("{name}", {req_str})')
        if "display_name" in a:
            lines.append(f'    {name}.setDisplayName("{a["display_name"]}")')
        else:
            display = name.replace("_", " ").title()
            lines.append(f'    {name}.setDisplayName("{display}")')
        if "default_value" in a:
            dv = a["default_value"]
            if atype == "Double":
                lines.append(f"    {name}.setDefaultValue({float(dv)})")
            elif atype == "Integer":
                lines.append(f"    {name}.setDefaultValue({int(dv)})")
            elif atype == "Boolean":
                lines.append(f"    {name}.setDefaultValue({str(dv).lower()})")
            else:
                lines.append(f'    {name}.setDefaultValue("{dv}")')
        lines.append(f"    args << {name}")
    lines += ["    return args", "  end"]
    return "\n".join(lines)


def _generate_python_arguments(args: list[dict]) -> str:
    """Generate Python arguments() method body."""
    lines = [
        "    def arguments(self, model=None):",
        "        args = openstudio.measure.OSArgumentVector()",
    ]
    for a in args:
        name = a["name"]
        atype = a.get("type", "String")
        required = a.get("required", True)
        req_str = "True" if required else "False"
        maker = _ARG_MAKERS.get(atype, "String")
        lines.append(f'        {name} = openstudio.measure.OSArgument.make{maker}Argument("{name}", {req_str})')
        if "display_name" in a:
            lines.append(f'        {name}.setDisplayName("{a["display_name"]}")')
        else:
            display = name.replace("_", " ").title()
            lines.append(f'        {name}.setDisplayName("{display}")')
        if "default_value" in a:
            dv = a["default_value"]
            if atype == "Double":
                lines.append(f"        {name}.setDefaultValue({float(dv)})")
            elif atype == "Integer":
                lines.append(f"        {name}.setDefaultValue({int(dv)})")
            elif atype == "Boolean":
                lines.append(f"        {name}.setDefaultValue({dv!s})")
            else:
                lines.append(f'        {name}.setDefaultValue("{dv}")')
        lines.append(f"        args.append({name})")
    lines += ["        return args"]
    return "\n".join(lines)


def _generate_ruby_extraction(args: list[dict]) -> str:
    """Generate Ruby argument extraction lines for run() method."""
    lines = []
    for a in args:
        name = a["name"]
        atype = a.get("type", "String")
        getter = _ARG_MAKERS.get(atype, "String")
        lines.append(f'    {name} = runner.get{getter}ArgumentValue("{name}", user_arguments)')
    return "\n".join(lines)


def _generate_python_extraction(args: list[dict]) -> str:
    """Generate Python argument extraction lines for run() method."""
    lines = []
    for a in args:
        name = a["name"]
        atype = a.get("type", "String")
        getter = _ARG_MAKERS.get(atype, "String")
        lines.append(f'        {name} = runner.get{getter}ArgumentValue("{name}", user_arguments)')
    return "\n".join(lines)


def _build_ruby_run(args: list[dict], run_body: str) -> str:
    """Build complete Ruby run() method for ModelMeasure."""
    extraction = _generate_ruby_extraction(args)
    lines = [
        "  def run(model, runner, user_arguments)",
        "    super(model, runner, user_arguments)",
        "    if !runner.validateUserArguments(arguments(model), user_arguments)",
        "      return false",
        "    end",
    ]
    if extraction:
        lines.append(extraction)
    lines += [
        f"    {_BEGIN_MARKER}",
        run_body,
        f"    {_END_MARKER}",
        "    return true",
        "  end",
    ]
    return "\n".join(lines)


def _build_ruby_reporting_run(args: list[dict], run_body: str) -> str:
    """Build complete Ruby run() method for ReportingMeasure."""
    extraction = _generate_ruby_extraction(args)
    lines = [
        "  def run(runner, user_arguments)",
        "    super(runner, user_arguments)",
        "    if !runner.validateUserArguments(arguments, user_arguments)",
        "      return false",
        "    end",
    ]
    if extraction:
        lines.append(extraction)
    lines += [
        "    model = runner.lastOpenStudioModel",
        "    if model.is_initialized",
        "      model = model.get",
        "    end",
        "    sql_path = runner.lastEnergyPlusSqlFilePath",
        "    if sql_path.is_initialized",
        "      sql = OpenStudio::SqlFile.new(sql_path.get)",
        "      model.setSqlFile(sql) if model",
        "    end",
        f"    {_BEGIN_MARKER}",
        run_body,
        f"    {_END_MARKER}",
        "    return true",
        "  end",
    ]
    return "\n".join(lines)


def _build_python_run(args: list[dict], run_body: str) -> str:
    """Build complete Python run() method for ModelMeasure."""
    extraction = _generate_python_extraction(args)
    lines = [
        "    def run(self, model, runner, user_arguments):",
        "        super().run(model, runner, user_arguments)",
        "        if not runner.validateUserArguments(self.arguments(model), user_arguments):",
        "            return False",
    ]
    if extraction:
        lines.append(extraction)
    lines += [
        f"        {_BEGIN_MARKER}",
        run_body,
        f"        {_END_MARKER}",
        "        return True",
    ]
    return "\n".join(lines)


def _build_python_reporting_run(args: list[dict], run_body: str) -> str:
    """Build complete Python run() method for ReportingMeasure."""
    extraction = _generate_python_extraction(args)
    lines = [
        "    def run(self, runner, user_arguments):",
        "        super().run(runner, user_arguments)",
        "        if not runner.validateUserArguments(self.arguments(), user_arguments):",
        "            return False",
    ]
    if extraction:
        lines.append(extraction)
    lines += [
        "        model_opt = runner.lastOpenStudioModel()",
        "        model = model_opt.get() if model_opt.is_initialized() else None",
        "        sql_path = runner.lastEnergyPlusSqlFilePath()",
        "        if sql_path.is_initialized():",
        "            sql = openstudio.SqlFile(sql_path.get())",
        "            if model:",
        "                model.setSqlFile(sql)",
        f"        {_BEGIN_MARKER}",
        run_body,
        f"        {_END_MARKER}",
        "        return True",
    ]
    return "\n".join(lines)


def _build_ruby_script(class_name: str, name: str, description: str,
                        modeler_description: str, args: list[dict],
                        run_body: str) -> str:
    """Build complete Ruby measure script."""
    arguments_method = _generate_ruby_arguments(args)
    run_method = _build_ruby_run(args, run_body)
    return f"""class {class_name} < OpenStudio::Measure::ModelMeasure
  def name
    return "{name}"
  end

  def description
    return "{description}"
  end

  def modeler_description
    return "{modeler_description}"
  end

{arguments_method}

{run_method}
end

{class_name}.new.registerWithApplication
"""


def _build_python_script(class_name: str, name: str, description: str,
                          modeler_description: str, args: list[dict],
                          run_body: str) -> str:
    """Build complete Python measure script."""
    arguments_method = _generate_python_arguments(args)
    run_method = _build_python_run(args, run_body)
    return f"""import openstudio


class {class_name}(openstudio.measure.ModelMeasure):
    def name(self):
        return "{name}"

    def description(self):
        return "{description}"

    def modeler_description(self):
        return "{modeler_description}"

{arguments_method}

{run_method}


{class_name}().registerWithApplication()
"""


def _build_ruby_reporting_script(class_name: str, name: str, description: str,
                                  modeler_description: str, args: list[dict],
                                  run_body: str) -> str:
    """Build complete Ruby ReportingMeasure script."""
    arguments_method = _generate_ruby_arguments(args)
    # ReportingMeasure arguments() takes no args (not model)
    arguments_method = arguments_method.replace(
        "  def arguments(model)", "  def arguments",
    )
    run_method = _build_ruby_reporting_run(args, run_body)
    return f"""class {class_name} < OpenStudio::Measure::ReportingMeasure
  def name
    return "{name}"
  end

  def description
    return "{description}"
  end

  def modeler_description
    return "{modeler_description}"
  end

{arguments_method}

  def energyPlusOutputRequests(runner, user_arguments)
    super(runner, user_arguments)
    result = OpenStudio::IdfObjectVector.new
    # Add output requests here if needed, e.g.:
    # request = OpenStudio::IdfObject.load('Output:Variable,,Site Outdoor Air Drybulb Temperature,Timestep;').get
    # result << request
    return result
  end

{run_method}
end

{class_name}.new.registerWithApplication
"""


def _build_python_reporting_script(class_name: str, name: str, description: str,
                                    modeler_description: str, args: list[dict],
                                    run_body: str) -> str:
    """Build complete Python ReportingMeasure script."""
    arguments_method = _generate_python_arguments(args)
    # ReportingMeasure arguments() takes no model param
    arguments_method = arguments_method.replace(
        "    def arguments(self, model=None):", "    def arguments(self):",
    )
    run_method = _build_python_reporting_run(args, run_body)
    return f"""import openstudio


class {class_name}(openstudio.measure.ReportingMeasure):
    def name(self):
        return "{name}"

    def description(self):
        return "{description}"

    def modeler_description(self):
        return "{modeler_description}"

{arguments_method}

    def energyPlusOutputRequests(self, runner, user_arguments):
        super().energyPlusOutputRequests(runner, user_arguments)
        result = openstudio.IdfObjectVector()
        # Add output requests here if needed
        return result

{run_method}


{class_name}().registerWithApplication()
"""


def _syntax_check(script_path: Path, language: str) -> dict | None:
    """Run syntax check. Returns error dict or None if OK."""
    try:
        if language == "Ruby":
            proc = subprocess.run(
                ["ruby", "-c", str(script_path)],
                capture_output=True, text=True, timeout=10, check=False,
            )
        else:
            code = script_path.read_text(encoding="utf-8")
            proc = subprocess.run(
                ["python3", "-c", f"compile({code!r}, {str(script_path)!r}, 'exec')"],
                capture_output=True, text=True, timeout=10, check=False,
            )
        if proc.returncode != 0:
            return {"syntax_ok": False, "syntax_error": proc.stderr.strip()}
    except FileNotFoundError:
        pass  # interpreter not available — skip check
    except subprocess.TimeoutExpired:
        return {"syntax_ok": False, "syntax_error": "Syntax check timed out"}
    return None


def _update_measure_xml(measure_dir: Path, language: str):
    """Run `openstudio measure -u` to sync XML with script arguments.

    For Ruby measures, this executes arguments() and updates measure.xml.
    For Python measures, openstudio measure -u doesn't work (issue #4907),
    so we skip it — list_measure_arguments won't reflect custom args.
    """
    if language != "Ruby":
        return
    try:
        subprocess.run(
            ["openstudio", "measure", "-u", str(measure_dir)],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


def _generate_ruby_test(class_name: str, args: list[dict]) -> str:
    """Generate a Ruby minitest file for the custom measure.

    Uses tests/test_model.osm if present (copied by test_measure_op),
    falls back to empty model.
    """
    args_hash_lines = []
    for a in args:
        dv = a.get("default_value", "")
        atype = a.get("type", "String")
        if atype == "Double":
            args_hash_lines.append(f"    args_hash['{a['name']}'] = {float(dv)}")
        elif atype == "Integer":
            args_hash_lines.append(f"    args_hash['{a['name']}'] = {int(dv)}")
        elif atype == "Boolean":
            args_hash_lines.append(f"    args_hash['{a['name']}'] = {str(dv).lower()}")
        else:
            args_hash_lines.append(f"    args_hash['{a['name']}'] = '{dv}'")
    args_hash = "\n".join(args_hash_lines) if args_hash_lines else "    # no arguments"

    return f"""require 'openstudio'
require 'openstudio/measure/ShowRunnerOutput'
require 'minitest/autorun'
require_relative '../measure'

class {class_name}Test < Minitest::Test
  def load_test_model
    test_model = File.join(File.dirname(__FILE__), 'test_model.osm')
    if File.exist?(test_model)
      vt = OpenStudio::OSVersion::VersionTranslator.new
      model = vt.loadModel(OpenStudio::Path.new(test_model))
      return model.get if model.is_initialized
    end
    OpenStudio::Model::Model.new
  end

  def test_number_of_arguments
    measure = {class_name}.new
    model = load_test_model
    arguments = measure.arguments(model)
    assert_equal({len(args)}, arguments.size)
  end

  def test_good_argument_values
    measure = {class_name}.new
    osw = OpenStudio::WorkflowJSON.new
    runner = OpenStudio::Measure::OSRunner.new(osw)
    model = load_test_model
    arguments = measure.arguments(model)
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)
    args_hash = {{}}
{args_hash}
    arguments.each do |arg|
      temp_arg_var = arg.clone
      if args_hash.key?(arg.name)
        assert(temp_arg_var.setValue(args_hash[arg.name]))
      end
      argument_map[arg.name] = temp_arg_var
    end
    measure.run(model, runner, argument_map)
    result = runner.result
    result.showOutput
    assert_equal('Success', result.value.valueName)
  end
end
"""


def _generate_python_test(class_name: str, args: list[dict]) -> str:
    """Generate a Python pytest file for the custom measure.

    Uses tests/test_model.osm if present (copied by test_measure_op),
    falls back to empty model.
    """
    args_dict_lines = []
    for a in args:
        dv = a.get("default_value", "")
        args_dict_lines.append(f'        "{a["name"]}": "{dv}",')
    args_dict = "\n".join(args_dict_lines) if args_dict_lines else "        # no arguments"

    return f"""import openstudio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from measure import {class_name}


def load_test_model():
    test_model = os.path.join(os.path.dirname(__file__), "test_model.osm")
    if os.path.exists(test_model):
        vt = openstudio.osversion.VersionTranslator()
        result = vt.loadModel(openstudio.toPath(test_model))
        if result.is_initialized():
            return result.get()
    return openstudio.model.Model()


class Test{class_name}:
    def test_number_of_arguments(self):
        measure = {class_name}()
        model = load_test_model()
        arguments = measure.arguments(model)
        assert len(arguments) == {len(args)}

    def test_good_argument_values(self):
        measure = {class_name}()
        model = load_test_model()
        osw = openstudio.WorkflowJSON()
        runner = openstudio.measure.OSRunner(osw)
        arguments = measure.arguments(model)
        argument_map = openstudio.measure.convertOSArgumentVectorToMap(arguments)
        args_dict = {{
{args_dict}
        }}
        for arg in arguments:
            temp = arg.clone()
            if arg.name() in args_dict:
                temp.setValue(str(args_dict[arg.name()]))
            argument_map[arg.name()] = temp
        measure.run(model, runner, argument_map)
        result = runner.result()
        assert str(result.value().valueName()) == "Success"
"""


def _ruby_arg_name_assertions(args: list[dict]) -> str:
    """Build Ruby assertion lines checking argument names exist."""
    if not args:
        return "# no arguments to check"
    lines = []
    for a in args:
        lines.append(
            f'    assert(arguments.any? {{ |a| a.name == "{a["name"]}" }})',
        )
    return "\n".join(lines)


def _generate_ruby_reporting_test(class_name: str, args: list[dict]) -> str:
    """Generate a Ruby minitest file for a ReportingMeasure.

    Tests argument count only — full run() test requires SQL artifacts
    and must be done via test_measure_op with run_id.
    """
    return f"""require 'openstudio'
require 'openstudio/measure/ShowRunnerOutput'
require 'minitest/autorun'
require_relative '../measure'

class {class_name}Test < Minitest::Test
  def test_number_of_arguments
    measure = {class_name}.new
    arguments = measure.arguments
    assert_equal({len(args)}, arguments.size)
  end

  def test_argument_names
    measure = {class_name}.new
    arguments = measure.arguments
    {_ruby_arg_name_assertions(args)}
  end
end
"""


def _generate_python_reporting_test(class_name: str, args: list[dict]) -> str:
    """Generate a Python pytest file for a ReportingMeasure.

    Tests argument count only — full run() requires SQL artifacts.
    """
    arg_names_check = "\n".join(
        f'        assert any(a.name() == "{a["name"]}" for a in arguments)'
        for a in args
    ) if args else "        pass  # no arguments to check"

    return f"""import openstudio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from measure import {class_name}


class Test{class_name}:
    def test_number_of_arguments(self):
        measure = {class_name}()
        arguments = measure.arguments()
        assert len(arguments) == {len(args)}

    def test_argument_names(self):
        measure = {class_name}()
        arguments = measure.arguments()
{arg_names_check}
"""


def _write_test_file(measure_dir: Path, class_name: str, args: list[dict],
                     language: str, measure_type: str = "ModelMeasure"):
    """Write a custom test file replacing the SDK-generated one.

    Filename uses the measure dir name (snake_case), not class_name.lower(),
    so it matches what `openstudio measure -u` writes into measure.xml.
    """
    test_dir = measure_dir / "tests"
    test_dir.mkdir(exist_ok=True)
    # Use snake_case dir name so filename matches measure.xml <files> section
    base_name = measure_dir.name
    is_reporting = measure_type == "ReportingMeasure"
    if language == "Ruby":
        # Remove SDK-generated tests
        for f in test_dir.glob("*_test.rb"):
            f.unlink()
        test_path = test_dir / f"{base_name}_test.rb"
        gen = _generate_ruby_reporting_test if is_reporting else _generate_ruby_test
        test_path.write_text(gen(class_name, args), encoding="utf-8")
    else:
        for f in test_dir.glob("test_*.py"):
            f.unlink()
        test_path = test_dir / f"test_{base_name}.py"
        gen = _generate_python_reporting_test if is_reporting else _generate_python_test
        test_path.write_text(gen(class_name, args), encoding="utf-8")


# ── Public operations ────────────────────────────────────────────────

def create_measure_op(
    name: str,
    description: str,
    run_body: str,
    language: str,
    arguments: list[dict] | None = None,
    taxonomy_tag: str = "Whole Building.Space Types",
    modeler_description: str = "",
    measure_type: str = "ModelMeasure",
) -> dict[str, Any]:
    """Scaffold a new OpenStudio measure and inject user code."""
    try:
        err = _validate_measure_name(name)
        if err:
            return {"ok": False, "error": err}
        if len(run_body) > _MAX_BODY_SIZE:
            return {"ok": False, "error": f"run_body exceeds {_MAX_BODY_SIZE} bytes"}
        if language not in ("Ruby", "Python"):
            return {"ok": False, "error": "language must be 'Ruby' or 'Python'"}
        if measure_type not in ("ModelMeasure", "ReportingMeasure"):
            return {"ok": False, "error": "measure_type must be 'ModelMeasure' or 'ReportingMeasure'"}

        args = arguments or []
        class_name = _to_class_name(name)
        measure_dir = CUSTOM_MEASURES_DIR / name
        # Clean existing dir for idempotent re-creation (safe: name is validated)
        if measure_dir.exists():
            shutil.rmtree(measure_dir)
        measure_dir.mkdir(parents=True)

        # SDK scaffold
        lang_args = []
        if language == "Python":
            lang_args = [openstudio.MeasureLanguage("Python")]
        bcl = openstudio.BCLMeasure(
            name.replace("_", " ").title(),  # display name
            class_name,
            openstudio.toPath(str(measure_dir)),
            taxonomy_tag,
            openstudio.MeasureType(measure_type),
            description,
            modeler_description or description,
            *lang_args,
        )
        bcl.save()

        # Determine script file — dispatch to reporting variants if needed
        is_reporting = measure_type == "ReportingMeasure"
        display_name = name.replace("_", " ").title()
        mod_desc = modeler_description or description
        if language == "Ruby":
            script_path = measure_dir / "measure.rb"
            builder = _build_ruby_reporting_script if is_reporting else _build_ruby_script
            script = builder(class_name, display_name, description, mod_desc, args, run_body)
        else:
            script_path = measure_dir / "measure.py"
            builder = _build_python_reporting_script if is_reporting else _build_python_script
            script = builder(class_name, display_name, description, mod_desc, args, run_body)

        script_path.write_text(script, encoding="utf-8")

        # Write custom test file BEFORE updating XML (order matters —
        # _update_measure_xml re-hashes all files, so test must exist first)
        _write_test_file(measure_dir, class_name, args, language, measure_type)

        # Sync measure.xml checksums with all current files
        _update_measure_xml(measure_dir, language)

        # Syntax check
        validation = {"syntax_ok": True}
        err = _syntax_check(script_path, language)
        if err:
            validation = err

        return {
            "ok": True,
            "measure_dir": str(measure_dir),
            "class_name": class_name,
            "language": language,
            "measure_type": measure_type,
            "script_file": script_path.name,
            "validation": validation,
        }

    except Exception as e:
        return {"ok": False, "error": f"Failed to create measure: {e}"}


def _test_reporting_measure_with_run(
    mdir: Path, language: str, run_id: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run a ReportingMeasure against completed simulation artifacts via OSW.

    Builds a minimal OSW, stages SQL/OSM/IDF from the completed run,
    and runs ``openstudio run --postprocess_only``.
    """
    import json
    import os
    import uuid as _uuid

    from mcp_server.config import OSCLI_GEM_PATH, OSCLI_GEMFILE, RUN_ROOT
    from mcp_server.util import resolve_run_dir

    try:
        sim_dir = resolve_run_dir(RUN_ROOT, run_id)
    except FileNotFoundError:
        return {"ok": False, "error": f"Simulation run not found: {run_id}"}

    sql_src = sim_dir / "run" / "eplusout.sql"
    if not sql_src.is_file():
        return {"ok": False, "error": f"No eplusout.sql in run {run_id} — simulation may not have completed"}

    # Build temp run dir
    test_run_id = _uuid.uuid4().hex[:12]
    runs_dir = Path(os.environ.get("MCP_RUNS_DIR", "/runs"))
    run_dir = runs_dir / f"measure_test_{test_run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # Stage simulation artifacts
    ep_run = run_dir / "run"
    ep_run.mkdir(exist_ok=True)
    shutil.copy2(str(sql_src), str(ep_run / "eplusout.sql"))
    for fname in ["in.osm", "in.idf"]:
        src = sim_dir / "run" / fname
        if src.is_file():
            shutil.copy2(str(src), str(ep_run / fname))

    # Copy seed model for OSW
    osm_src = sim_dir / "run" / "in.osm"
    temp_osm = run_dir / "in.osm"
    if osm_src.is_file():
        shutil.copy2(str(osm_src), str(temp_osm))
    else:
        # Fallback: create empty model
        import openstudio as _os
        m = _os.model.Model()
        m.save(str(temp_osm), True)

    # Copy measure
    measures_dir = run_dir / "measures"
    measures_dir.mkdir(exist_ok=True)
    local_measure = measures_dir / mdir.name
    shutil.copytree(str(mdir), str(local_measure), dirs_exist_ok=True)

    # Build OSW
    measure_args = {}
    if arguments:
        measure_args = {k: str(v) for k, v in arguments.items()}
    osw = {
        "seed_file": str(temp_osm),
        "measure_paths": [str(measures_dir)],
        "steps": [{
            "measure_dir_name": mdir.name,
            "arguments": measure_args,
        }],
    }
    osw_path = run_dir / "workflow.osw"
    osw_path.write_text(json.dumps(osw, indent=2), encoding="utf-8")

    # Run postprocess
    cmd = [
        "openstudio",
        "--bundle", OSCLI_GEMFILE,
        "--bundle_path", OSCLI_GEM_PATH,
        "--bundle_without", "native_ext",
        "run", "--postprocess_only", "-w", str(osw_path),
    ]
    log_path = run_dir / "openstudio.log"
    with log_path.open("w", encoding="utf-8") as log_f:
        proc = subprocess.run(
            cmd, cwd=str(run_dir),
            stdout=log_f, stderr=subprocess.STDOUT,
            env=os.environ.copy(), timeout=120, check=False,
        )

    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    display = log_text[-2000:] if len(log_text) > 2000 else log_text

    if proc.returncode != 0:
        return {
            "ok": False,
            "passed": 0, "failed": 1, "errors": 0,
            "test_output": f"ReportingMeasure test failed (exit {proc.returncode}):\n{display}",
        }

    return {
        "ok": True,
        "passed": 1, "failed": 0, "errors": 0,
        "test_output": f"ReportingMeasure ran successfully via --postprocess_only:\n{display}",
    }


def _detect_measure_type(mdir: Path) -> str:
    """Detect measure type from script content."""
    for script in [mdir / "measure.rb", mdir / "measure.py"]:
        if script.is_file():
            content = script.read_text(encoding="utf-8", errors="replace")
            if "ReportingMeasure" in content:
                return "ReportingMeasure"
    return "ModelMeasure"


def test_measure_op(
    measure_dir: str,
    arguments: dict[str, Any] | None = None,
    model_path: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Run tests for a measure using the appropriate test framework.

    For ModelMeasures: copies a real model into tests/test_model.osm.
    For ReportingMeasures: run_id required — builds OSW and runs
    ``openstudio run --postprocess_only`` against simulation artifacts.

    Model priority (ModelMeasure only):
    1. Explicit model_path argument
    2. Currently loaded model (via model_manager)
    3. SystemD_baseline.osm from tests/assets or /inputs
    4. No test_model.osm → test template falls back to empty Model.new()
    """
    try:
        mdir = Path(measure_dir)
        if not mdir.is_dir():
            return {"ok": False, "error": f"Measure directory not found: {measure_dir}"}

        # Detect language
        if (mdir / "measure.py").is_file():
            language = "Python"
        elif (mdir / "measure.rb").is_file():
            language = "Ruby"
        else:
            return {"ok": False, "error": "No measure.rb or measure.py found"}

        detected_type = _detect_measure_type(mdir)

        # ReportingMeasure with run_id: OSW-based integration test
        if detected_type == "ReportingMeasure" and run_id:
            return _test_reporting_measure_with_run(mdir, language, run_id, arguments)

        test_dir = mdir / "tests"
        if not test_dir.is_dir():
            return {"ok": False, "error": "No tests/ directory found"}

        # Copy test model into tests/ so the test template can load it
        test_model_dst = test_dir / "test_model.osm"
        src_model = None
        if model_path:
            src = Path(model_path)
            if src.is_file():
                src_model = src
        if not src_model:
            src_model = _find_test_model()
        if src_model:
            shutil.copy2(str(src_model), str(test_model_dst))

        if language == "Python":
            proc = subprocess.run(
                ["python3", "-m", "pytest", "tests/", "-v", "--tb=short"],
                cwd=str(mdir),
                capture_output=True, text=True, timeout=60, check=False,
            )
        else:
            # Run minitest directly (openstudio measure -r doesn't run minitest)
            test_files = list(test_dir.glob("*_test.rb"))
            if not test_files:
                return {"ok": False, "error": "No Ruby test files found"}
            proc = subprocess.run(
                ["ruby", "-I", ".", str(test_files[0])],
                cwd=str(mdir),
                capture_output=True, text=True, timeout=60, check=False,
            )

        output = proc.stdout + proc.stderr
        passed = failed = errors = 0

        if language == "Python":
            # Parse pytest output: "X passed, Y failed, Z errors"
            m = re.search(r"(\d+) passed", output)
            if m:
                passed = int(m.group(1))
            m = re.search(r"(\d+) failed", output)
            if m:
                failed = int(m.group(1))
            m = re.search(r"(\d+) error", output)
            if m:
                errors = int(m.group(1))
        else:
            # Parse minitest: "X runs, Y assertions, Z failures, W errors"
            # Must parse FULL output before truncating (Rubocop floods the end)
            m = re.search(r"(\d+) runs.*?(\d+) failures.*?(\d+) errors", output)
            if m:
                passed = int(m.group(1)) - int(m.group(2)) - int(m.group(3))
                failed = int(m.group(2))
                errors = int(m.group(3))

        # Truncate for display but keep minitest summary if found
        display = output
        if len(display) > 2000:
            # For Ruby, try to include the minitest summary line
            minitest_line = ""
            ml = re.search(r"^\d+ runs,.*$", output, re.MULTILINE)
            if ml:
                minitest_line = f"[minitest] {ml.group(0)}\n...\n"
            display = minitest_line + output[-1500:]

        # Update measure.xml checksums — test_model.osm was added to tests/,
        # and any new files must be registered for OS App Measure Manager.
        _update_measure_xml(mdir, language)

        return {
            "ok": proc.returncode == 0,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "test_output": display,
        }

    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Test run timed out (60s)"}
    except Exception as e:
        return {"ok": False, "error": f"Failed to test measure: {e}"}


def edit_measure_op(
    measure_name: str,
    run_body: str | None = None,
    arguments: list[dict] | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Edit an existing custom measure's code, arguments, or description."""
    try:
        err = _validate_measure_name(measure_name)
        if err:
            return {"ok": False, "error": err}
        measure_dir = CUSTOM_MEASURES_DIR / measure_name
        if not measure_dir.is_dir():
            return {"ok": False, "error": f"Measure not found: {measure_name}"}

        # Detect language
        if (measure_dir / "measure.py").is_file():
            language = "Python"
            script_path = measure_dir / "measure.py"
        elif (measure_dir / "measure.rb").is_file():
            language = "Ruby"
            script_path = measure_dir / "measure.rb"
        else:
            return {"ok": False, "error": "No measure script found"}

        content = script_path.read_text(encoding="utf-8")
        detected_type = _detect_measure_type(measure_dir)
        is_reporting = detected_type == "ReportingMeasure"
        changes = []

        # Replace run() body between markers
        if run_body is not None:
            if len(run_body) > _MAX_BODY_SIZE:
                return {"ok": False, "error": f"run_body exceeds {_MAX_BODY_SIZE} bytes"}
            pattern = re.compile(
                rf"({re.escape(_BEGIN_MARKER)}).*?({re.escape(_END_MARKER)})",
                re.DOTALL,
            )
            if pattern.search(content):
                content = pattern.sub(rf"\1\n{run_body}\n\2", content)
                changes.append("run_body")
            else:
                return {"ok": False, "error": "Cannot find user logic markers in script"}

        # Replace arguments() method
        if arguments is not None:
            if language == "Ruby":
                new_args = _generate_ruby_arguments(arguments)
                if is_reporting:
                    new_args = new_args.replace("  def arguments(model)", "  def arguments")
                # Match both ModelMeasure and ReportingMeasure signatures
                pattern = re.compile(
                    r"  def arguments(?:\(model\))?.*?  end",
                    re.DOTALL,
                )
                content = pattern.sub(new_args, content)
                # Also update extraction in run()
                new_extraction = _generate_ruby_extraction(arguments)
                # Replace extraction block between validate and begin marker
                pattern = re.compile(
                    r"(    end\n)(.*?)(\n    " + re.escape(_BEGIN_MARKER) + ")",
                    re.DOTALL,
                )
                if new_extraction:
                    content = pattern.sub(rf"\1{new_extraction}\3", content)
                else:
                    content = pattern.sub(r"\1\3", content)
            else:
                new_args = _generate_python_arguments(arguments)
                if is_reporting:
                    new_args = new_args.replace(
                        "    def arguments(self, model=None):", "    def arguments(self):",
                    )
                # Match both ModelMeasure and ReportingMeasure signatures
                pattern = re.compile(
                    r"    def arguments\(self(?:, model=None)?\):.*?(?=\n    def )",
                    re.DOTALL,
                )
                content = pattern.sub(new_args + "\n", content)
                # Update extraction
                new_extraction = _generate_python_extraction(arguments)
                pattern = re.compile(
                    r"(            return False\n)(.*?)(\n        " + re.escape(_BEGIN_MARKER) + ")",
                    re.DOTALL,
                )
                if new_extraction:
                    content = pattern.sub(rf"\1{new_extraction}\3", content)
                else:
                    content = pattern.sub(r"\1\3", content)

            _write_test_file(measure_dir, _to_class_name(measure_name), arguments,
                             language, detected_type)
            changes.append("arguments")

        # Update description in script
        if description is not None:
            if language == "Ruby":
                content = re.sub(
                    r'(  def description\n    return ").*?(")',
                    rf"\g<1>{description}\2",
                    content,
                )
            else:
                content = re.sub(
                    r'(    def description\(self\):\n        return ").*?(")',
                    rf"\g<1>{description}\2",
                    content,
                )
            changes.append("description")
            # Also update measure.xml via BCLMeasure
            try:
                bcl = openstudio.BCLMeasure(openstudio.toPath(str(measure_dir)))
                bcl.setDescription(description)
                bcl.save()
            except Exception:
                pass

        script_path.write_text(content, encoding="utf-8")

        # Always sync measure.xml checksums — any file change (run_body,
        # arguments, description) invalidates checksums.  Stale checksums
        # cause OS App Measure Manager to silently reject the measure.
        _update_measure_xml(measure_dir, language)

        # Syntax check
        validation = {"syntax_ok": True}
        err = _syntax_check(script_path, language)
        if err:
            validation = err

        return {
            "ok": True,
            "measure_dir": str(measure_dir),
            "changes_made": changes,
            "validation": validation,
        }

    except Exception as e:
        return {"ok": False, "error": f"Failed to edit measure: {e}"}


def list_custom_measures_op() -> dict[str, Any]:
    """List all custom measures in /runs/custom_measures/."""
    try:
        if not CUSTOM_MEASURES_DIR.is_dir():
            return {"ok": True, "count": 0, "measures": []}

        measures = []
        for d in sorted(CUSTOM_MEASURES_DIR.iterdir()):
            if not d.is_dir():
                continue
            has_rb = (d / "measure.rb").is_file()
            has_py = (d / "measure.py").is_file()
            if not has_rb and not has_py:
                continue
            measures.append({
                "name": d.name,
                "language": "Python" if has_py else "Ruby",
                "measure_dir": str(d),
            })

        return {"ok": True, "count": len(measures), "measures": measures}

    except Exception as e:
        return {"ok": False, "error": f"Failed to list measures: {e}"}

"""Measure authoring operations — create, test, and edit custom measures.

Uses openstudio.BCLMeasure() for scaffolding, then patches the generated
script with user-provided arguments and run() body.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import openstudio

from mcp_server.config import RUN_ROOT
from mcp_server.stdout_suppression import suppress_openstudio_warnings

CUSTOM_MEASURES_DIR = RUN_ROOT / "custom_measures"

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
    """Build complete Ruby run() method."""
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


def _build_python_run(args: list[dict], run_body: str) -> str:
    """Build complete Python run() method."""
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
    """Generate a Ruby minitest file for the custom measure."""
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
  def test_number_of_arguments
    measure = {class_name}.new
    model = OpenStudio::Model::Model.new
    arguments = measure.arguments(model)
    assert_equal({len(args)}, arguments.size)
  end

  def test_good_argument_values
    measure = {class_name}.new
    osw = OpenStudio::WorkflowJSON.new
    runner = OpenStudio::Measure::OSRunner.new(osw)
    model = OpenStudio::Model::Model.new
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
    """Generate a Python pytest file for the custom measure."""
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


class Test{class_name}:
    def test_number_of_arguments(self):
        measure = {class_name}()
        model = openstudio.model.Model()
        arguments = measure.arguments(model)
        assert len(arguments) == {len(args)}

    def test_good_argument_values(self):
        measure = {class_name}()
        model = openstudio.model.Model()
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


def _write_test_file(measure_dir: Path, class_name: str, args: list[dict],
                     language: str):
    """Write a custom test file replacing the SDK-generated one."""
    test_dir = measure_dir / "tests"
    test_dir.mkdir(exist_ok=True)
    if language == "Ruby":
        # Remove SDK-generated tests
        for f in test_dir.glob("*_test.rb"):
            f.unlink()
        test_path = test_dir / f"{class_name.lower()}_test.rb"
        test_path.write_text(_generate_ruby_test(class_name, args), encoding="utf-8")
    else:
        for f in test_dir.glob("test_*.py"):
            f.unlink()
        test_path = test_dir / f"test_{class_name.lower()}.py"
        test_path.write_text(_generate_python_test(class_name, args), encoding="utf-8")


# ── Public operations ────────────────────────────────────────────────

def create_measure_op(
    name: str,
    description: str,
    run_body: str,
    language: str,
    arguments: list[dict] | None = None,
    taxonomy_tag: str = "Whole Building.Space Types",
    modeler_description: str = "",
) -> dict[str, Any]:
    """Scaffold a new OpenStudio measure and inject user code."""
    try:
        if len(run_body) > _MAX_BODY_SIZE:
            return {"ok": False, "error": f"run_body exceeds {_MAX_BODY_SIZE} bytes"}
        if language not in ("Ruby", "Python"):
            return {"ok": False, "error": "language must be 'Ruby' or 'Python'"}

        args = arguments or []
        class_name = _to_class_name(name)
        measure_dir = CUSTOM_MEASURES_DIR / name
        measure_dir.mkdir(parents=True, exist_ok=True)

        # SDK scaffold
        with suppress_openstudio_warnings():
            lang_args = []
            if language == "Python":
                lang_args = [openstudio.MeasureLanguage("Python")]
            bcl = openstudio.BCLMeasure(
                name.replace("_", " ").title(),  # display name
                class_name,
                openstudio.toPath(str(measure_dir)),
                taxonomy_tag,
                openstudio.MeasureType("ModelMeasure"),
                description,
                modeler_description or description,
                *lang_args,
            )
            bcl.save()

        # Determine script file
        if language == "Ruby":
            script_path = measure_dir / "measure.rb"
            script = _build_ruby_script(
                class_name, name.replace("_", " ").title(),
                description, modeler_description or description,
                args, run_body,
            )
        else:
            script_path = measure_dir / "measure.py"
            script = _build_python_script(
                class_name, name.replace("_", " ").title(),
                description, modeler_description or description,
                args, run_body,
            )

        script_path.write_text(script, encoding="utf-8")

        # Sync measure.xml with script's arguments()
        _update_measure_xml(measure_dir, language)

        # Write custom test file (replaces SDK-generated one)
        _write_test_file(measure_dir, class_name, args, language)

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
            "script_file": script_path.name,
            "validation": validation,
        }

    except Exception as e:
        return {"ok": False, "error": f"Failed to create measure: {e}"}


def test_measure_op(
    measure_dir: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run tests for a measure using the appropriate test framework."""
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

        test_dir = mdir / "tests"
        if not test_dir.is_dir():
            return {"ok": False, "error": "No tests/ directory found"}

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
                pattern = re.compile(
                    r"  def arguments\(model\).*?  end",
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
                pattern = re.compile(
                    r"    def arguments\(self, model=None\):.*?(?=\n    def )",
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

            _write_test_file(measure_dir, _to_class_name(measure_name), arguments, language)
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
                with suppress_openstudio_warnings():
                    bcl = openstudio.BCLMeasure(openstudio.toPath(str(measure_dir)))
                    bcl.setDescription(description)
                    bcl.save()
            except Exception:
                pass

        script_path.write_text(content, encoding="utf-8")

        # Sync measure.xml if arguments changed
        if arguments is not None:
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

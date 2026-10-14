# Test measure: proves a model resource (a file in the model's companion
# files/ dir) is reachable through the workflow's file search paths during a
# measure run, the way the OpenStudio Application's Apply Measure Now sets
# them up. Fails loudly when the file cannot be found.
class ReadResourceFile < OpenStudio::Measure::ModelMeasure
  def name
    return "Read Resource File"
  end

  def description
    return "Fails unless the named resource file is reachable through the workflow file search paths."
  end

  def modeler_description
    return "Calls runner.workflow.findFile(file_name) and sets the building name to the file's first line."
  end

  def arguments(model)
    args = OpenStudio::Measure::OSArgumentVector.new

    file_name = OpenStudio::Measure::OSArgument.makeStringArgument("file_name", true)
    file_name.setDisplayName("Resource file name")
    args << file_name

    return args
  end

  def run(model, runner, user_arguments)
    super(model, runner, user_arguments)

    if !runner.validateUserArguments(arguments(model), user_arguments)
      return false
    end

    file_name = runner.getStringArgumentValue("file_name", user_arguments)
    found = runner.workflow.findFile(file_name)
    if found.empty?
      searched = runner.workflow.absoluteFilePaths.map(&:to_s)
      runner.registerError("Resource file '#{file_name}' not found; searched #{searched}")
      return false
    end

    first_line = File.open(found.get.to_s, &:readline).strip
    model.getBuilding.setName("resource:#{first_line}")
    runner.registerInfo("Found '#{file_name}' at #{found.get}")

    return true
  end
end

ReadResourceFile.new.registerWithApplication

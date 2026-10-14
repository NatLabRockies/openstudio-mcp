# Test measure: generates a resource file the way real measures do (write it,
# register it with ExternalFile.getExternalFile so the CLI places it in the
# workflow's generated files dir) and makes the model depend on it through a
# Schedule:File assigned to every Lights object, so a later simulation can
# only succeed if the generated file travels with the model.
require "fileutils"
require "tmpdir"

class WriteGeneratedFile < OpenStudio::Measure::ModelMeasure
  def name
    return "Write Generated File"
  end

  def description
    return "Creates an hourly CSV, registers it as an ExternalFile and uses it as the lighting schedule."
  end

  def modeler_description
    return "ExternalFile.getExternalFile copies the CSV into the workflow's first file path (generated_files under the CLI)."
  end

  def arguments(model)
    args = OpenStudio::Measure::OSArgumentVector.new

    file_name = OpenStudio::Measure::OSArgument.makeStringArgument("file_name", true)
    file_name.setDisplayName("Generated CSV file name")
    file_name.setDefaultValue("generated_schedule.csv")
    args << file_name

    return args
  end

  def run(model, runner, user_arguments)
    super(model, runner, user_arguments)

    if !runner.validateUserArguments(arguments(model), user_arguments)
      return false
    end

    file_name = runner.getStringArgumentValue("file_name", user_arguments)

    # Write the CSV somewhere disposable inside the run dir, then let the SDK
    # copy it into the workflow's file path like a real measure would.
    scratch = File.join(runner.workflow.absoluteRootDir.to_s, "tmp")
    FileUtils.mkdir_p(scratch)
    staged = File.join(scratch, file_name)
    File.open(staged, "w") do |f|
      8760.times { |i| f.puts(((i % 24) >= 8 && (i % 24) < 18) ? "1" : "0.1") }
    end

    external = OpenStudio::Model::ExternalFile.getExternalFile(model, staged)
    if external.empty?
      runner.registerError("ExternalFile.getExternalFile failed for #{staged}")
      return false
    end
    runner.registerInfo("ExternalFile placed at #{external.get.filePath}")

    schedule = OpenStudio::Model::ScheduleFile.new(external.get, 1, 0)
    schedule.setName("Generated Lighting Schedule")
    schedule.setNumberofHoursofData(8760)
    schedule.setMinutesperItem(60)

    count = 0
    model.getLightss.each do |lights|
      lights.setSchedule(schedule)
      count += 1
    end
    runner.registerInfo("Assigned '#{file_name}' schedule to #{count} Lights objects")

    return true
  end
end

WriteGeneratedFile.new.registerWithApplication

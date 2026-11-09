# Bundled with openstudio-mcp for the parallel-annual skill (issue #247).

class HardSizeFromSizingSql < OpenStudio::Measure::ModelMeasure
  def name
    return 'Hard Size From Sizing SQL'
  end

  def description
    return 'Applies sizing results from a sizing-run SQL file to the model and turns sizing off when nothing is left autosized.'
  end

  def modeler_description
    return 'Attaches the SQL with Model::setSqlFile, calls Model::applySizingValues, counts fields still set to Autosize, and turns zone, system and plant sizing (and sizing-period simulation) off only when that count is zero.'
  end

  def arguments(model)
    args = OpenStudio::Measure::OSArgumentVector.new
    sql_path = OpenStudio::Measure::OSArgument.makeStringArgument('sql_path', true)
    sql_path.setDisplayName('Sizing SQL path')
    sql_path.setDescription('eplusout.sql from a sizing run of this same model. An absolute path, or a file name found on the workflow file search path (e.g. the model files/ folder).')
    args << sql_path
    return args
  end

  # Fields still holding "Autosize", as "Type 'name' field" labels. Sizing:Zone/System/Plant
  # are skipped: they are inputs to the sizing calculations, unused once those are off.
  def autosized_fields(model)
    left = []
    model.modelObjects.each do |obj|
      type = obj.iddObject.name
      next if type.start_with?('OS:Sizing:')
      (0...obj.numFields).each do |i|
        value = obj.getString(i)
        next unless value.is_initialized && value.get.casecmp('autosize').zero?
        field = obj.iddObject.getField(i)
        left << "#{type} '#{obj.nameString}' #{field.is_initialized ? field.get.name : "field #{i}"}"
      end
    end
    return left
  end

  def run(model, runner, user_arguments)
    super(model, runner, user_arguments)
    return false unless runner.validateUserArguments(arguments(model), user_arguments)

    requested = runner.getStringArgumentValue('sql_path', user_arguments).strip
    path = File.file?(requested) ? requested : nil
    if path.nil?
      found = runner.workflow.findFile(requested)
      path = found.get.to_s if found.is_initialized
    end
    if path.nil?
      runner.registerError("Sizing SQL not found: #{requested}. A sandboxed measure reads only its own run directory; put the SQL in the model's files/ folder and pass its file name.")
      return false
    end

    before = autosized_fields(model).size
    runner.registerInitialCondition("#{before} fields are set to Autosize.")
    sql = OpenStudio::SqlFile.new(OpenStudio::Path.new(path))
    unless sql.connectionOpen
      runner.registerError("Could not open #{path} as an EnergyPlus SQL file.")
      return false
    end
    model.setSqlFile(sql)
    model.applySizingValues
    model.resetSqlFile

    left = autosized_fields(model)
    runner.registerValue('autosize_fields_before', before)
    runner.registerValue('autosize_fields_left', left.size)
    if left.empty?
      sc = model.getSimulationControl
      sc.setDoZoneSizingCalculation(false)
      sc.setDoSystemSizingCalculation(false)
      sc.setDoPlantSizingCalculation(false)
      sc.setRunSimulationforSizingPeriods(false)
      runner.registerFinalCondition("Hard-sized #{before} fields; zone, system and plant sizing turned off.")
    else
      runner.registerWarning("#{left.size} fields are still Autosize, so sizing stays on: #{left.first(5).join('; ')}")
      runner.registerFinalCondition("Hard-sized #{before - left.size} of #{before} fields; sizing left on.")
    end
    return true
  end
end

HardSizeFromSizingSql.new.registerWithApplication

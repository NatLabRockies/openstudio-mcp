# Bundled with openstudio-mcp for the parallel-annual skill (issue #247).

class SetWarmupDays < OpenStudio::Measure::ModelMeasure
  def name
    return 'Set Warmup Days'
  end

  def description
    return 'Fixes the number of EnergyPlus warmup days.'
  end

  def modeler_description
    return 'Sets SimulationControl minimum and maximum number of warmup days to the same value.'
  end

  def arguments(model)
    args = OpenStudio::Measure::OSArgumentVector.new
    warmup_days = OpenStudio::Measure::OSArgument.makeIntegerArgument('warmup_days', true)
    warmup_days.setDisplayName('Warmup days')
    warmup_days.setDescription('Used as both the minimum and maximum number of warmup days (1 or more).')
    warmup_days.setDefaultValue(1)
    args << warmup_days
    return args
  end

  def run(model, runner, user_arguments)
    super(model, runner, user_arguments)
    return false unless runner.validateUserArguments(arguments(model), user_arguments)

    days = runner.getIntegerArgumentValue('warmup_days', user_arguments)
    if days < 1
      runner.registerError("warmup_days must be 1 or more, got #{days}.")
      return false
    end

    sc = model.getSimulationControl
    runner.registerInitialCondition("Warmup days: min #{sc.minimumNumberofWarmupDays}, max #{sc.maximumNumberofWarmupDays}.")
    unless sc.setMinimumNumberofWarmupDays(days) && sc.setMaximumNumberofWarmupDays(days)
      runner.registerError("SimulationControl rejected #{days} warmup days.")
      return false
    end
    runner.registerFinalCondition("Warmup days: min #{days}, max #{days}.")
    return true
  end
end

SetWarmupDays.new.registerWithApplication

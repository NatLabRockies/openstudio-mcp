# Bundled with openstudio-mcp for the parallel-annual skill (issue #247).

require 'date'

class SetRunPeriodAndSave < OpenStudio::Measure::ModelMeasure
  def name
    return 'Set Run Period And Save'
  end

  def description
    return 'Sets the RunPeriod begin and end dates, optionally saving the model to a file.'
  end

  def modeler_description
    return 'Sets RunPeriod begin/end month and day. When save_path is not empty, also saves the changed model there.'
  end

  def arguments(model)
    args = OpenStudio::Measure::OSArgumentVector.new
    [['begin_month', 1], ['begin_day', 1], ['end_month', 12], ['end_day', 31]].each do |arg_name, default|
      arg = OpenStudio::Measure::OSArgument.makeIntegerArgument(arg_name, true)
      arg.setDisplayName(arg_name.split('_').map(&:capitalize).join(' '))
      arg.setDefaultValue(default)
      args << arg
    end
    save_path = OpenStudio::Measure::OSArgument.makeStringArgument('save_path', false)
    save_path.setDisplayName('Save path')
    save_path.setDescription('Optional .osm path to save the changed model to; relative paths resolve in the measure working directory. Empty: do not save.')
    save_path.setDefaultValue('')
    args << save_path
    return args
  end

  def run(model, runner, user_arguments)
    super(model, runner, user_arguments)
    return false unless runner.validateUserArguments(arguments(model), user_arguments)

    bm = runner.getIntegerArgumentValue('begin_month', user_arguments)
    bd = runner.getIntegerArgumentValue('begin_day', user_arguments)
    em = runner.getIntegerArgumentValue('end_month', user_arguments)
    ed = runner.getIntegerArgumentValue('end_day', user_arguments)
    save_path = runner.getStringArgumentValue('save_path', user_arguments).strip

    # Checked against a leap year so Feb 29 is accepted; EnergyPlus handles the calendar.
    begin
      first = Date.new(2024, bm, bd)
      last = Date.new(2024, em, ed)
    rescue ArgumentError
      runner.registerError("Invalid date: #{bm}/#{bd} to #{em}/#{ed}.")
      return false
    end
    if last < first
      runner.registerError("End date #{em}/#{ed} is before begin date #{bm}/#{bd}; a run period cannot wrap the year.")
      return false
    end

    rp = model.getRunPeriod
    runner.registerInitialCondition("Run period #{rp.getBeginMonth}/#{rp.getBeginDayOfMonth} to #{rp.getEndMonth}/#{rp.getEndDayOfMonth}.")
    ok = rp.setBeginMonth(bm) && rp.setBeginDayOfMonth(bd) && rp.setEndMonth(em) && rp.setEndDayOfMonth(ed)
    unless ok
      runner.registerError("RunPeriod rejected #{bm}/#{bd} to #{em}/#{ed}.")
      return false
    end

    unless save_path.empty?
      unless model.save(OpenStudio::Path.new(save_path), true)
        runner.registerError("Could not save the model to #{save_path}.")
        return false
      end
      runner.registerInfo("Saved the model to #{File.expand_path(save_path)}.")
    end
    runner.registerFinalCondition("Run period #{bm}/#{bd} to #{em}/#{ed}.")
    return true
  end
end

SetRunPeriodAndSave.new.registerWithApplication

require 'openstudio'
require 'minitest/autorun'
require 'json'
require 'tmpdir'
require_relative '../measure'

class HardSizeFromSizingSqlTest < Minitest::Test
  # One sizing-only run of the example model (design days, no weather file needed), shared by the tests.
  def self.sizing_sql
    @sizing_sql ||= begin
      dir = Dir.mktmpdir('hard_size_test')
      model = OpenStudio::Model.exampleModel
      model.getSimulationControl.setRunSimulationforWeatherFileRunPeriods(false)
      model.save(File.join(dir, 'sizing.osm'), true)
      File.write(File.join(dir, 'sizing.osw'), JSON.generate('seed_file' => 'sizing.osm', 'steps' => []))
      system(OpenStudio.getOpenStudioCLI.to_s, 'run', '-w', File.join(dir, 'sizing.osw'), out: File::NULL, err: File::NULL)
      File.join(dir, 'run', 'eplusout.sql')
    end
  end

  def run_measure(model, sql_path)
    measure = HardSizeFromSizingSql.new
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)
    arguments = measure.arguments(model)
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)
    arg = arguments[0].clone
    assert(arg.setValue(sql_path))
    argument_map['sql_path'] = arg
    measure.run(model, runner, argument_map)
    runner.result
  end

  def sizing_flags(model)
    sc = model.getSimulationControl
    [sc.doZoneSizingCalculation, sc.doSystemSizingCalculation, sc.doPlantSizingCalculation, sc.runSimulationforSizingPeriods]
  end

  def test_missing_sql_fails_with_hint
    # Validates: a path the sandboxed measure cannot see fails loudly instead of leaving the model autosized
    result = run_measure(OpenStudio::Model.exampleModel, 'no_such_sizing.sql')
    assert_equal('Fail', result.value.valueName)
    assert_match(/Sizing SQL not found: no_such_sizing.sql/, result.errors.map(&:logMessage).join)
  end

  def test_leftover_autosize_keeps_sizing_on
    # Validates: fields applySizingValues cannot fill (the example DX coil's evaporative condenser
    # fields) leave the sizing settings untouched, or EnergyPlus would stop on the autosized field
    assert(File.file?(self.class.sizing_sql), 'sizing run produced no SQL')
    model = OpenStudio::Model.exampleModel
    before = sizing_flags(model)
    result = run_measure(model, self.class.sizing_sql)
    assert_equal('Success', result.value.valueName)
    left = result.stepValues.find { |v| v.name == 'autosize_fields_left' }
    assert_equal(2, left.valueAsInteger)
    assert_equal(1, result.warnings.size)
    assert_equal(before, sizing_flags(model))
    coil = model.getCoilCoolingDXSingleSpeeds.first
    assert(coil.ratedTotalCoolingCapacity.is_initialized, 'cooling capacity should be hard-sized')
  end

  def test_fully_hard_sized_model_turns_sizing_off
    # Validates: with nothing left autosized, sizing calculations and sizing-period runs are turned off
    model = OpenStudio::Model.exampleModel
    coil = model.getCoilCoolingDXSingleSpeeds.first
    coil.setEvaporativeCondenserAirFlowRate(0.1)
    coil.setEvaporativeCondenserPumpRatedPowerConsumption(0.0)
    result = run_measure(model, self.class.sizing_sql)
    assert_equal('Success', result.value.valueName)
    assert_equal(0, result.stepValues.find { |v| v.name == 'autosize_fields_left' }.valueAsInteger)
    assert_equal([false, false, false, false], sizing_flags(model))
  end
end

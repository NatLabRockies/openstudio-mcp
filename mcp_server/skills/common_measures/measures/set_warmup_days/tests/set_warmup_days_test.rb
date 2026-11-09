require 'openstudio'
require 'minitest/autorun'
require_relative '../measure'

class SetWarmupDaysTest < Minitest::Test
  def run_measure(model, days)
    measure = SetWarmupDays.new
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)
    arguments = measure.arguments(model)
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)
    arg = arguments[0].clone
    assert(arg.setValue(days))
    argument_map['warmup_days'] = arg
    measure.run(model, runner, argument_map)
    runner.result
  end

  def test_sets_min_and_max_warmup_days
    # Validates: segment 1 gets exactly 7 warmup days (min = max), later segments exactly 1
    model = OpenStudio::Model::Model.new
    [7, 1].each do |days|
      assert_equal('Success', run_measure(model, days).value.valueName)
      sc = model.getSimulationControl
      assert_equal([days, days], [sc.minimumNumberofWarmupDays, sc.maximumNumberofWarmupDays])
    end
  end

  def test_rejects_zero_days
    # Validates: 0 warmup days is refused instead of being written to SimulationControl
    model = OpenStudio::Model::Model.new
    result = run_measure(model, 0)
    assert_equal('Fail', result.value.valueName)
    assert_match(/must be 1 or more/, result.errors.map(&:logMessage).join)
  end
end

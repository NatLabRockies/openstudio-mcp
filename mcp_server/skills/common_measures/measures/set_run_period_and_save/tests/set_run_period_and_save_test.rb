require 'openstudio'
require 'minitest/autorun'
require 'tmpdir'
require_relative '../measure'

class SetRunPeriodAndSaveTest < Minitest::Test
  def run_measure(model, values)
    measure = SetRunPeriodAndSave.new
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)
    arguments = measure.arguments(model)
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)
    arguments.each do |arg|
      copy = arg.clone
      assert(copy.setValue(values[arg.name])) if values.key?(arg.name)
      argument_map[arg.name] = copy
    end
    measure.run(model, runner, argument_map)
    runner.result
  end

  def test_sets_run_period_and_saves
    # Validates: a segment's run period (lead-in start to kept end) is written and the model saved when asked
    Dir.mktmpdir do |dir|
      path = File.join(dir, 'segment.osm')
      model = OpenStudio::Model::Model.new
      result = run_measure(model, 'begin_month' => 1, 'begin_day' => 24, 'end_month' => 3, 'end_day' => 1, 'save_path' => path)
      assert_equal('Success', result.value.valueName)
      rp = model.getRunPeriod
      assert_equal([1, 24, 3, 1], [rp.getBeginMonth, rp.getBeginDayOfMonth, rp.getEndMonth, rp.getEndDayOfMonth])
      saved = OpenStudio::Model::Model.load(path).get.getRunPeriod
      assert_equal([1, 24, 3, 1], [saved.getBeginMonth, saved.getBeginDayOfMonth, saved.getEndMonth, saved.getEndDayOfMonth])
    end
  end

  def test_rejects_wrapped_and_invalid_dates
    # Validates: a period that wraps the year or names a day that does not exist fails, leaving the run period alone
    model = OpenStudio::Model::Model.new
    result = run_measure(model, 'begin_month' => 12, 'begin_day' => 1, 'end_month' => 1, 'end_day' => 31)
    assert_equal('Fail', result.value.valueName)
    assert_match(/before begin date/, result.errors.map(&:logMessage).join)
    result = run_measure(model, 'begin_month' => 4, 'begin_day' => 31, 'end_month' => 5, 'end_day' => 1)
    assert_match(/Invalid date/, result.errors.map(&:logMessage).join)
    assert_equal([1, 1], [model.getRunPeriod.getBeginMonth, model.getRunPeriod.getBeginDayOfMonth])
  end
end

require 'openstudio'
require 'minitest/autorun'
require 'date'
require 'json'
require 'tmpdir'
require_relative '../measure'

class WriteSegmentOswsTest < Minitest::Test
  def run_measure(model, values)
    measure = WriteSegmentOsws.new
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

  def model_2006
    model = OpenStudio::Model::Model.new
    model.getYearDescription.setCalendarYear(2006)
    model
  end

  def read_osw(dir, label)
    JSON.parse(File.read(File.join(dir, label, "#{label}.osw")))
  end

  def step_args(osw, name)
    osw['steps'].find { |s| s['measure_dir_name'] == name }['arguments']
  end

  def test_twelve_segments_cover_the_year_with_seasonal_lead_in
    # Validates: segments tile the run period exactly once, segment 1 gets 7 warmup days and no lead-in,
    # later segments 1 warmup day plus 7 lead-in days (2 in Jun-Sep), and each OSW names the seed, weather and measures
    Dir.mktmpdir do |dir|
      result = run_measure(model_2006, 'seed_osm_path' => '/runs/u/hard.osm', 'weather_file' => '/inputs/w.epw',
                                       'number_of_segments' => 12, 'output_dir' => dir)
      assert_equal('Success', result.value.valueName)
      kept = []
      (1..12).each do |k|
        osw = read_osw(dir, format('segment_%02d', k))
        assert_equal('/runs/u/hard.osm', osw['seed_file'])
        assert_equal('/inputs/w.epw', osw['weather_file'])
        assert_equal(['/opt/common-measures'], osw['measure_paths'])
        assert_equal(['set_run_period_and_save', 'set_warmup_days', 'segment_results_summary'], osw['steps'].map { |s| s['measure_dir_name'] })
        keep = step_args(osw, 'segment_results_summary')
        first = Date.new(2006, keep['keep_begin_month'], keep['keep_begin_day'])
        last = Date.new(2006, keep['keep_end_month'], keep['keep_end_day'])
        kept.concat((first..last).to_a)
        rp = step_args(osw, 'set_run_period_and_save')
        run_first = Date.new(2006, rp['begin_month'], rp['begin_day'])
        assert_equal(last, Date.new(2006, rp['end_month'], rp['end_day']))
        lead = if k == 1 then 0 elsif (6..9).cover?(first.month) then 2 else 7 end
        assert_equal(lead, (first - run_first).to_i, "segment #{k} lead-in")
        assert_equal(k == 1 ? 7 : 1, step_args(osw, 'set_warmup_days')['warmup_days'])
      end
      assert_equal((Date.new(2006, 1, 1)..Date.new(2006, 12, 31)).to_a, kept)
    end
  end

  def test_lead_in_stops_at_january_first
    # Validates: a segment whose 7-day lead-in would reach back past Jan 1 (kept from Jan 6) starts on Jan 1, not in the prior year
    Dir.mktmpdir do |dir|
      model = model_2006
      model.getRunPeriod.setEndMonth(1)
      model.getRunPeriod.setEndDayOfMonth(10)
      assert_equal('Success', run_measure(model, 'seed_osm_path' => 's.osm', 'number_of_segments' => 2, 'output_dir' => dir).value.valueName)
      rp = step_args(read_osw(dir, 'segment_02'), 'set_run_period_and_save')
      assert_equal([1, 1], [rp['begin_month'], rp['begin_day']])
      refute(read_osw(dir, 'segment_02').key?('weather_file'), 'empty weather_file must be left out of the OSW')
    end
  end

  def test_rejects_bad_segment_count_and_months
    # Validates: more segments than days, and a month outside 1-12, fail before any OSW is written
    Dir.mktmpdir do |dir|
      result = run_measure(model_2006, 'seed_osm_path' => 's.osm', 'number_of_segments' => 366, 'output_dir' => dir)
      assert_match(/between 1 and 365/, result.errors.map(&:logMessage).join)
      result = run_measure(model_2006, 'seed_osm_path' => 's.osm', 'short_lead_in_months' => '6,13', 'output_dir' => dir)
      assert_match(/months 1-12/, result.errors.map(&:logMessage).join)
      assert_empty(Dir.children(dir))
    end
  end
end
